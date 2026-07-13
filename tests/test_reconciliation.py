import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from reconciliation import (
    resolve_resp2_canonical,
    build_item_reconciliation,
    build_responsibility_reconciliation,
    build_vendor_weekly_trend,
    backfill_resp1_desc,
    backfill_resp1_desc_cross_dataset,
)
from parsers.commitment_xlsx_parser import parse_commitment_workbook
from parsers.expenditure_pdf_parser import parse_expenditure_pdf

RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
# The raw exports are gitignored (real government financial data, not
# meant for version control), so CI checks out a repo without them. This
# end-to-end test is skipped there rather than failing on missing fixtures;
# the synthetic-data tests above it don't need real files and still run.
_raw_files_present = os.path.isdir(RAW_DIR) and any(
    fn.lower().endswith(('.xlsx', '.pdf')) for fn in os.listdir(RAW_DIR)
)


def _commit_row(date, resp1, resp2, item_group, item, vendor, balance):
    return {
        'report_date': date, 'resp1_desc': resp1, 'resp2_desc': resp2,
        'item_group_desc': item_group, 'item_desc': item, 'vendor': vendor,
        'commitments_balance': balance,
    }


def _exp_row(date, resp1, resp2, item_group, item, commitments, expenses=0, budget=0, available=0):
    return {
        'report_date': date, 'resp1_desc': resp1, 'resp2_desc': resp2,
        'item_group_desc': item_group, 'item_desc': item, 'commitments': commitments,
        'expenses': expenses, 'budget': budget, 'available_budget': available,
    }


class TestResolveResp2Canonical(unittest.TestCase):
    def test_exact_match(self):
        commit = [_commit_row('2026-06-22', 'R1', 'FINANCIAL ACCOUNTING', 'GS', 'X', 'V', 1)]
        exp = [_exp_row('2026-06-22', 'R1', 'FINANCIAL ACCOUNTING', 'GS', 'X', 1)]
        mapping = resolve_resp2_canonical(commit, exp)
        self.assertEqual(mapping[('2026-06-22', 'FINANCIAL ACCOUNTING')], 'FINANCIAL ACCOUNTING')

    def test_ledger_truncated_shorter_than_expenditure(self):
        commit = [_commit_row('2026-07-06', 'R1', 'MEDIA RELA, CONTENT PROD & MANA', 'GS', 'X', 'V', 1)]
        exp = [_exp_row('2026-07-06', 'R1', 'MEDIA RELA, CONTENT PROD & MANAG', 'GS', 'X', 1)]
        mapping = resolve_resp2_canonical(commit, exp)
        self.assertEqual(
            mapping[('2026-07-06', 'MEDIA RELA, CONTENT PROD & MANA')],
            'MEDIA RELA, CONTENT PROD & MANAG',
        )

    def test_expenditure_truncated_shorter_than_ledger(self):
        # The reverse direction: expenditure's column is the narrower one.
        commit = [_commit_row('2026-07-06', 'R1', 'GOV, STATE CAP&INST DEV SUP (DDG)', 'GS', 'X', 'V', 1)]
        exp = [_exp_row('2026-07-06', 'R1', 'GOV, STATE CAP&INST DEV SUP (DDG', 'GS', 'X', 1)]
        mapping = resolve_resp2_canonical(commit, exp)
        self.assertEqual(
            mapping[('2026-07-06', 'GOV, STATE CAP&INST DEV SUP (DDG)')],
            'GOV, STATE CAP&INST DEV SUP (DDG',
        )

    def test_no_match_falls_back_to_original(self):
        commit = [_commit_row('2026-06-22', 'R1', 'UNRELATED UNIT', 'GS', 'X', 'V', 1)]
        exp = [_exp_row('2026-06-22', 'R1', 'SOMETHING ELSE ENTIRELY', 'GS', 'X', 1)]
        mapping = resolve_resp2_canonical(commit, exp)
        self.assertEqual(mapping[('2026-06-22', 'UNRELATED UNIT')], 'UNRELATED UNIT')


class TestBuildItemReconciliation(unittest.TestCase):
    def test_exact_match_zero_variance(self):
        commit = [_commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 'V', 100.0)]
        exp = [_exp_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 100.0)]
        resp2_map = resolve_resp2_canonical(commit, exp)
        [row] = build_item_reconciliation(commit, exp, resp2_map)
        self.assertEqual(row['note'], '')
        self.assertEqual(row['variance'], 0.0)

    def test_multiple_vendors_sum_before_reconciling(self):
        commit = [
            _commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 'VENDOR X', 60.0),
            _commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 'VENDOR Y', 40.0),
        ]
        exp = [_exp_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 100.0)]
        resp2_map = resolve_resp2_canonical(commit, exp)
        [row] = build_item_reconciliation(commit, exp, resp2_map)
        self.assertEqual(row['commitment_ledger_total'], 100.0)
        self.assertEqual(row['variance'], 0.0)

    def test_no_matching_expenditure_item_is_flagged(self):
        commit = [_commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'SOMETHING UNMATCHED', 'V', 50.0)]
        exp = [_exp_row('2026-06-22', 'R1', 'RESP2', 'GS', 'COMPLETELY DIFFERENT', 0.0)]
        resp2_map = resolve_resp2_canonical(commit, exp)
        [row] = build_item_reconciliation(commit, exp, resp2_map)
        self.assertEqual(row['note'], 'NO_EXPENDITURE_MATCH')
        self.assertIsNone(row['expenditure_reported_commitments'])

    def test_expenditure_only_nonzero_commitment_is_flagged(self):
        commit = []
        exp = [_exp_row('2026-06-22', 'R1', 'RESP2', 'GS', 'STANDING CHARGE', 250.0)]
        resp2_map = resolve_resp2_canonical(commit, exp)
        [row] = build_item_reconciliation(commit, exp, resp2_map)
        self.assertEqual(row['note'], 'NO_LEDGER_DETAIL')
        self.assertEqual(row['commitment_ledger_total'], 0.0)
        self.assertEqual(row['variance'], -250.0)

    def test_expenditure_only_zero_commitment_is_not_flagged(self):
        # Most items have zero commitments (e.g. salary lines); these
        # shouldn't clutter the reconciliation with a row per item.
        commit = []
        exp = [_exp_row('2026-06-22', 'R1', 'RESP2', 'GS', 'SALARY LINE', 0.0)]
        resp2_map = resolve_resp2_canonical(commit, exp)
        self.assertEqual(build_item_reconciliation(commit, exp, resp2_map), [])

    def test_item_description_truncation_resolved_via_normalized_prefix(self):
        commit = [_commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'AUDIT FEES:EXT PREVIOUS YEAR', 'V', 100.0)]
        exp = [_exp_row('2026-06-22', 'R1', 'RESP2', 'GS', 'AUDIT FEES:EXT PREVIOUS YEA R', 100.0)]
        resp2_map = resolve_resp2_canonical(commit, exp)
        [row] = build_item_reconciliation(commit, exp, resp2_map)
        self.assertEqual(row['note'], '')
        self.assertEqual(row['variance'], 0.0)


class TestBuildVendorWeeklyTrend(unittest.TestCase):
    def test_change_from_prior_week_is_none_for_first_observation(self):
        commit = [_commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 'VENDOR X', 100.0)]
        [row] = build_vendor_weekly_trend(commit)
        self.assertIsNone(row['change_from_prior_week'])

    def test_change_computed_across_consecutive_weeks(self):
        commit = [
            _commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', 'VENDOR X', 100.0),
            _commit_row('2026-06-29', 'R1', 'RESP2', 'GS', 'ITEM A', 'VENDOR X', 150.0),
        ]
        rows = build_vendor_weekly_trend(commit)
        self.assertEqual(rows[0]['change_from_prior_week'], None)
        self.assertEqual(rows[1]['change_from_prior_week'], 50.0)

    def test_rows_without_a_vendor_are_excluded(self):
        commit = [_commit_row('2026-06-22', 'R1', 'RESP2', 'GS', 'ITEM A', '', 100.0)]
        self.assertEqual(build_vendor_weekly_trend(commit), [])


class TestBackfillResp1Desc(unittest.TestCase):
    def test_fills_blank_from_same_dataset(self):
        rows = [
            _commit_row('2026-06-01', 'DEPT A', 'UNIT 1', 'GS', 'ITEM A', 'V', 10.0),
            _commit_row('2026-06-01', '', 'UNIT 1', 'GS', 'ITEM B', 'V', 20.0),
        ]
        rows, filled, ambiguous = backfill_resp1_desc(rows)
        self.assertEqual(filled, 1)
        self.assertEqual(ambiguous, set())
        self.assertEqual(rows[1]['resp1_desc'], 'DEPT A')

    def test_leaves_genuinely_ambiguous_resp2_blank(self):
        rows = [
            _commit_row('2026-06-01', 'DEPT A', 'SHARED UNIT', 'GS', 'ITEM A', 'V', 10.0),
            _commit_row('2026-06-22', 'DEPT B', 'SHARED UNIT', 'GS', 'ITEM A', 'V', 10.0),
            _commit_row('2026-06-29', '', 'SHARED UNIT', 'GS', 'ITEM A', 'V', 10.0),
        ]
        rows, filled, ambiguous = backfill_resp1_desc(rows)
        self.assertEqual(filled, 0)
        self.assertEqual(ambiguous, {'SHARED UNIT'})
        self.assertEqual(rows[2]['resp1_desc'], '')

    def test_cross_dataset_backfill_uses_other_dataset_for_same_week(self):
        commit = [_commit_row('2026-06-01', '', 'UNIT 1', 'GS', 'ITEM A', 'V', 10.0)]
        expenditure = [_exp_row('2026-06-01', 'DEPT A', 'UNIT 1', 'GS', 'ITEM A', 0.0)]
        commit, filled = backfill_resp1_desc_cross_dataset(commit, expenditure)
        self.assertEqual(filled, 1)
        self.assertEqual(commit[0]['resp1_desc'], 'DEPT A')

    def test_cross_dataset_backfill_tolerates_truncation_mismatch(self):
        commit = [_commit_row('2026-07-06', '', 'GOV, STATE CAP&INST DEV SUP (DDG', 'GS', 'ITEM A', 'V', 10.0)]
        expenditure = [_exp_row('2026-07-06', 'GOV, STATE CAPACITY & INSTIT DEV', 'GOV, STATE CAP&INST DEV SUP (DDG)', 'GS', 'ITEM A', 0.0)]
        commit, filled = backfill_resp1_desc_cross_dataset(commit, expenditure)
        self.assertEqual(filled, 1)
        self.assertEqual(commit[0]['resp1_desc'], 'GOV, STATE CAPACITY & INSTIT DEV')


@unittest.skipUnless(_raw_files_present, "raw data files not present (gitignored; expected in CI)")
class TestFullPipelineReconciliation(unittest.TestCase):
    """End-to-end pin across all 5 real weeks: parses every raw file
    directly (independent of whatever's in data/processed/), reconciles,
    and asserts the known-good result. If this count changes, either a
    parser regressed or a new cross-report quirk needs handling."""

    @classmethod
    def setUpClass(cls):
        xlsx_paths = sorted(glob.glob(os.path.join(RAW_DIR, '*.xlsx')))
        pdf_paths = sorted(glob.glob(os.path.join(RAW_DIR, '*.pdf')))
        cls.commitment_rows = []
        for path in xlsx_paths:
            rows, warnings = parse_commitment_workbook(path)
            assert warnings == [], f"{path} has parser warnings: {warnings}"
            cls.commitment_rows.extend(rows)
        cls.expenditure_rows = []
        for path in pdf_paths:
            rows, warnings = parse_expenditure_pdf(path)
            assert warnings == [], f"{path} has parser warnings: {warnings}"
            cls.expenditure_rows.extend(rows)

    def test_only_one_known_gap_remains(self):
        resp2_map = resolve_resp2_canonical(self.commitment_rows, self.expenditure_rows)
        item_recon = build_item_reconciliation(self.commitment_rows, self.expenditure_rows, resp2_map)
        flagged = [r for r in item_recon if (r['variance'] not in (None, 0.0)) or r['note']]

        self.assertEqual(len(flagged), 1, f"expected exactly 1 flagged row, got: {flagged}")
        gap = flagged[0]
        self.assertEqual(gap['report_date'], '2026-07-06')
        self.assertEqual(gap['resp2_desc'], 'INTERGRATED YOUTH DEVELO - SUPPP')
        self.assertEqual(gap['item_desc'], 'CATERING:DEPARTMENTL ACTIVITIES')
        self.assertEqual(gap['note'], 'NO_LEDGER_DETAIL')
        self.assertEqual(gap['variance'], -58410.0)

    def test_responsibility_level_variance_matches_the_same_single_gap(self):
        resp2_map = resolve_resp2_canonical(self.commitment_rows, self.expenditure_rows)
        resp_recon = build_responsibility_reconciliation(self.commitment_rows, self.expenditure_rows, resp2_map)
        flagged = [r for r in resp_recon if r['variance'] != 0.0]
        self.assertEqual(len(flagged), 1, f"expected exactly 1 flagged resp-unit row, got: {flagged}")
        self.assertEqual(flagged[0]['variance'], -58410.0)

    def test_backfill_resolves_every_blank_resp1_desc_in_the_real_data(self):
        # The entire 2026-06-01 expenditure PDF has corrupted/missing R-003
        # header text (a font-encoding issue specific to that export), so
        # every one of its 936 rows starts with a blank resp1_desc; a
        # handful of commitment rows are blank for unrelated reasons. Both
        # backfill passes together must resolve all of it, using the other
        # weeks'/dataset's resp2 -> resp1 mapping rather than leaving gaps
        # in department-level rollups.
        commitment_rows = [dict(r) for r in self.commitment_rows]
        expenditure_rows = [dict(r) for r in self.expenditure_rows]
        pre_blank_commit = sum(1 for r in commitment_rows if not r['resp1_desc'])
        pre_blank_exp = sum(1 for r in expenditure_rows if not r['resp1_desc'])
        self.assertGreater(pre_blank_exp, 900, "expected the known 2026-06-01 corruption to still be present")

        commitment_rows, _, _ = backfill_resp1_desc(commitment_rows)
        expenditure_rows, _, _ = backfill_resp1_desc(expenditure_rows)
        commitment_rows, _ = backfill_resp1_desc_cross_dataset(commitment_rows, expenditure_rows)
        expenditure_rows, _ = backfill_resp1_desc_cross_dataset(expenditure_rows, commitment_rows)

        self.assertEqual(sum(1 for r in commitment_rows if not r['resp1_desc']), 0)
        self.assertEqual(sum(1 for r in expenditure_rows if not r['resp1_desc']), 0)


if __name__ == '__main__':
    unittest.main()
