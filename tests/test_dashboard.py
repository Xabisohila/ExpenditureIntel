import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from build_dashboard import (
    build_vendor_records,
    build_dept_series,
    build_reconciliation_data,
    build_procurement_data,
    build_dashboard_data,
    render_html,
    TEMPLATE_PATH,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
NODE_AVAILABLE = shutil.which('node') is not None

DATES = ['2026-01-01', '2026-01-08', '2026-01-15']


def _commit_row(vendor, resp1, date, balance, order_no='OR-1', resp2='R2', item='ITEM'):
    return {'vendor': vendor, 'resp1_desc': resp1, 'resp2_desc': resp2, 'item_desc': item,
            'report_date': date, 'commitments_balance': balance, 'order_no': order_no}


def _exp_row(resp1, date, expenses, commitments, budget, available):
    return {'resp1_desc': resp1, 'report_date': date, 'expenses': expenses, 'commitments': commitments,
            'budget': budget, 'available_budget': available}


def _recon_row(date, resp1, resp2, item, ledger_total, reported, variance, note):
    return {'report_date': date, 'resp1_desc': resp1, 'resp2_desc': resp2, 'item_desc': item,
            'commitment_ledger_total': ledger_total, 'expenditure_reported_commitments': reported,
            'variance': variance, 'note': note}


# A small synthetic dataset covering every branch the delta panel and
# filters need to exercise: a vendor that goes flat/stale, one paid off,
# one that appears new and large, a vendor split across two departments
# (to test cross-department aggregation), a department that crosses two
# budget thresholds in one step, and a reconciliation gap that appears
# partway through the series (to test "newly flagged").
COMMITMENT_ROWS = [
    _commit_row('VENDOR X', 'DEPT A', '2026-01-01', 100),
    _commit_row('VENDOR X', 'DEPT A', '2026-01-08', 100),
    _commit_row('VENDOR X', 'DEPT A', '2026-01-15', 100),
    _commit_row('VENDOR Y', 'DEPT A', '2026-01-01', 500),
    _commit_row('VENDOR Z', 'DEPT B', '2026-01-15', 20000),
    _commit_row('VENDOR X', 'DEPT B', '2026-01-01', 50),
    _commit_row('VENDOR X', 'DEPT B', '2026-01-08', 50),
    _commit_row('VENDOR X', 'DEPT B', '2026-01-15', 50),
    # VENDOR BIG: a single order at d0, then a second distinct order joins
    # at d1 -- combined total crosses R1,000,000 while neither order does
    # on its own, so this is a procurement-flag candidate at both d1 and
    # d2. Balance is deliberately unchanged between d1 and d2 (streak of
    # only 2) so it does not also trip the unrelated "newly stale" delta,
    # and DEPT C has no expenditure rows so it doesn't touch dept_list/
    # dept-bar assertions elsewhere in this file.
    _commit_row('VENDOR BIG', 'DEPT C', '2026-01-01', 400000, order_no='OR-BIG-1'),
    _commit_row('VENDOR BIG', 'DEPT C', '2026-01-08', 600000, order_no='OR-BIG-1'),
    _commit_row('VENDOR BIG', 'DEPT C', '2026-01-08', 500000, order_no='OR-BIG-2'),
    _commit_row('VENDOR BIG', 'DEPT C', '2026-01-15', 600000, order_no='OR-BIG-1'),
    _commit_row('VENDOR BIG', 'DEPT C', '2026-01-15', 500000, order_no='OR-BIG-2'),
]

EXPENDITURE_ROWS = [
    _exp_row('DEPT A', '2026-01-01', 40, 10, 100, 50),
    _exp_row('DEPT A', '2026-01-08', 45, 10, 100, 45),
    _exp_row('DEPT A', '2026-01-15', 80, 10, 100, 10),  # 50% -> 55% -> 90%: crosses 75 and 90
    _exp_row('DEPT B', '2026-01-01', 10, 5, 100, 85),
    _exp_row('DEPT B', '2026-01-08', 12, 5, 100, 83),
    _exp_row('DEPT B', '2026-01-15', 14, 5, 100, 81),
]

ITEM_RECON_ROWS = [
    _recon_row('2026-01-01', 'DEPT A', 'R2', 'ITEM1', 100.0, 100.0, 0.0, ''),
    _recon_row('2026-01-08', 'DEPT A', 'R2', 'ITEM1', 100.0, 100.0, 0.0, ''),
    _recon_row('2026-01-15', 'DEPT A', 'R2', 'ITEM1', 100.0, 100.0, 0.0, ''),
    _recon_row('2026-01-15', 'DEPT A', 'R2', 'ITEM2', 0.0, 500.0, -500.0, 'NO_LEDGER_DETAIL'),
]


class TestBuildVendorRecords(unittest.TestCase):
    def test_attributes_balance_to_the_specific_department(self):
        records = build_vendor_records(COMMITMENT_ROWS, DATES)
        by_key = {(r['vendor'], r['resp1']): r['series'] for r in records}
        self.assertEqual(by_key[('VENDOR X', 'DEPT A')], [100.0, 100.0, 100.0])
        self.assertEqual(by_key[('VENDOR X', 'DEPT B')], [50.0, 50.0, 50.0])
        self.assertEqual(by_key[('VENDOR Y', 'DEPT A')], [500.0, 0.0, 0.0])
        self.assertEqual(by_key[('VENDOR Z', 'DEPT B')], [0.0, 0.0, 20000.0])

    def test_all_zero_series_excluded(self):
        rows = [_commit_row('GHOST', 'DEPT A', '2026-01-01', 0)]
        self.assertEqual(build_vendor_records(rows, ['2026-01-01']), [])


class TestBuildDeptSeries(unittest.TestCase):
    def test_computes_pct_committed_per_week(self):
        series = build_dept_series(EXPENDITURE_ROWS, DATES)
        self.assertEqual([w['pct'] for w in series['DEPT A']], [50.0, 55.0, 90.0])
        self.assertEqual([w['pct'] for w in series['DEPT B']], [15.0, 17.0, 19.0])

    def test_missing_week_is_null_not_a_crash(self):
        rows = [_exp_row('DEPT A', '2026-01-01', 10, 0, 100, 90)]
        series = build_dept_series(rows, DATES)
        self.assertEqual(series['DEPT A'][0]['pct'], 10.0)
        self.assertIsNone(series['DEPT A'][1]['pct'])
        self.assertIsNone(series['DEPT A'][2]['pct'])


class TestBuildReconciliationData(unittest.TestCase):
    def test_counts_and_gaps(self):
        data = build_reconciliation_data(ITEM_RECON_ROWS)
        self.assertEqual(data['reconciliation_total'], 4)
        self.assertEqual(data['reconciliation_matched'], 3)
        self.assertEqual(len(data['reconciliation_gaps']), 1)
        self.assertEqual(data['reconciliation_gaps'][0]['item_desc'], 'ITEM2')


class TestBuildProcurementData(unittest.TestCase):
    def test_flags_the_synthetic_split_and_leaves_the_rest_unflagged(self):
        data = build_procurement_data(COMMITMENT_ROWS)
        groups = {(g['vendor'], g['report_date']): g for g in data['procurement_groups']}
        self.assertEqual(groups[('VENDOR BIG', '2026-01-08')]['total'], 1_100_000.0)
        self.assertTrue(groups[('VENDOR BIG', '2026-01-08')]['flagged'])
        self.assertTrue(groups[('VENDOR BIG', '2026-01-15')]['flagged'])
        # d0 has only one distinct order for VENDOR BIG, so it isn't a
        # multi-order group at all.
        self.assertNotIn(('VENDOR BIG', '2026-01-01'), groups)
        self.assertEqual(data['procurement_threshold'], 1_000_000.0)


class TestBuildDashboardData(unittest.TestCase):
    def test_produces_expected_shape(self):
        data = build_dashboard_data(COMMITMENT_ROWS, EXPENDITURE_ROWS, ITEM_RECON_ROWS)
        self.assertEqual(data['dates'], DATES)
        self.assertEqual(data['dept_list'], ['DEPT A', 'DEPT B'])
        self.assertEqual(len(data['vendor_records']), 5)

    def test_row_counts_for_the_download_links(self):
        data = build_dashboard_data(COMMITMENT_ROWS, EXPENDITURE_ROWS, ITEM_RECON_ROWS)
        self.assertEqual(data['commitments_row_count'], len(COMMITMENT_ROWS))
        self.assertEqual(data['expenditure_row_count'], len(EXPENDITURE_ROWS))


class TestRenderHtml(unittest.TestCase):
    def test_download_links_point_at_the_published_csv_paths(self):
        data = build_dashboard_data(COMMITMENT_ROWS, EXPENDITURE_ROWS, ITEM_RECON_ROWS)
        html = render_html(data)
        self.assertIn('id="download-commitments" href="data/commitments.csv" download', html)
        self.assertIn('id="download-expenditure" href="data/expenditure.csv" download', html)

    def test_produces_a_balanced_standalone_document(self):
        data = build_dashboard_data(COMMITMENT_ROWS, EXPENDITURE_ROWS, ITEM_RECON_ROWS)
        html = render_html(data)
        self.assertTrue(html.strip().startswith('<!DOCTYPE html>'))
        for tag in ('html', 'head', 'body', 'script'):
            self.assertEqual(html.count(f'<{tag}') if tag == 'html' else html.count(f'<{tag}>'),
                              html.count(f'</{tag}>'),
                              f"unbalanced <{tag}> tags")
        self.assertNotIn('__DATA_JSON__', html)


@unittest.skipUnless(NODE_AVAILABLE, "node not found on PATH")
class TestDashboardScriptInBrowser(unittest.TestCase):
    """Runs the actual generated <script> content under Node with a DOM
    stub capable of real event dispatch, so filter interactions get
    exercised the same way a browser would -- not just a Python-side
    assertion that the numbers going in are correct. This is exactly the
    manual verification process that caught a real bug (broken apostrophe
    escaping that silently killed the entire page) turned into a real,
    always-run test instead of something that only happens if a human
    remembers to check by hand."""

    @classmethod
    def setUpClass(cls):
        data = build_dashboard_data(COMMITMENT_ROWS, EXPENDITURE_ROWS, ITEM_RECON_ROWS)
        html = render_html(data, template_path=TEMPLATE_PATH)

        m = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
        assert m, "no <script> block found in rendered HTML"

        cls.tmpdir = tempfile.mkdtemp(prefix='expintel_dashboard_test_')
        cls.script_path = os.path.join(cls.tmpdir, 'dashboard_script.js')
        with open(cls.script_path, 'w', encoding='utf-8') as f:
            f.write(m.group(1))

        # subprocess's text mode decodes with the system locale by default
        # (cp1252 on Windows, not UTF-8), which would corrupt the non-ASCII
        # characters (arrows, the ≥ sign) this page uses -- force UTF-8
        # explicitly rather than relying on the platform default.
        node_check = subprocess.run(['node', '--check', cls.script_path], capture_output=True, text=True, encoding='utf-8')
        assert node_check.returncode == 0, f"node --check failed:\n{node_check.stderr}"

        stub_path = os.path.join(FIXTURES_DIR, 'dashboard_dom_stub.js')
        result = subprocess.run(['node', stub_path, cls.script_path], capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, f"DOM stub simulation failed:\n{result.stdout}\n{result.stderr}"
        cls.result = json.loads(result.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_initial_render_compares_the_two_latest_weeks(self):
        self.assertEqual(self.result['initial']['deltaSub'], 'Comparing 2026-01-08 → 2026-01-15.')
        self.assertFalse(self.result['initial']['deltaIsEmptyState'])

    def test_initial_render_finds_the_expected_changes(self):
        headings = self.result['initial']['deltaGroupHeadings']
        # 1 newly-appeared reconciliation gap, 1 department crossing two
        # thresholds at once (counted as one crossing), vendor X going flat
        # for the 3rd consecutive week, vendor Z appearing new and large.
        self.assertIn('Reconciliation changes 1', headings)
        self.assertIn('Budget threshold crossings 1', headings)
        self.assertIn('Newly stale vendors 1', headings)
        self.assertIn('New vendors (≥R10k) 1', headings)
        self.assertIn('Biggest balance movers 0', headings)
        self.assertIn('Paid off 0', headings)

    def test_narrative_composes_a_sentence_per_signal(self):
        initial = self.result['initial']
        self.assertFalse(initial['narrativeIsEmptyState'])
        self.assertEqual(initial['narrativeHeader'], 'Comparing 2026-01-08 → 2026-01-15.')
        self.assertEqual(initial['narrativeLead'], '6 issues need attention this week.')
        self.assertEqual(initial['narrativeSentences'], [
            'DEPT A crossed 90% of budget committed (now 90%).',
            "DEPT B's budget-committed share moved up 2.0 points (17% → 19%).",
            '1 vendor had no balance movement for 3+ consecutive weeks: VENDOR X.',
            '1 procurement threshold-proximity flag this week: VENDOR BIG (R1.1M).',
            '1 new reconciliation gap appeared between the two reports.',
            '1 new vendor commitment appeared at R10k or more.',
        ])

    def test_narrative_has_no_prior_week_message_at_the_earliest_snapshot(self):
        earliest = self.result['earliestWeek']
        self.assertTrue(earliest['narrativeIsEmptyState'])
        self.assertIsNone(earliest['narrativeHeader'])

    def test_narrative_narrows_and_drops_the_out_of_scope_procurement_flag(self):
        # DEPT A has no procurement flags of its own (VENDOR BIG is DEPT C),
        # so that sentence should disappear entirely rather than showing a
        # zero-count line.
        deptFiltered = self.result['deptFiltered']
        self.assertEqual(deptFiltered['narrativeHeader'], 'Comparing 2026-01-08 → 2026-01-15 for DEPT A.')
        self.assertEqual(deptFiltered['narrativeLead'], '3 issues need attention this week.')
        self.assertEqual(deptFiltered['narrativeSentences'], [
            'DEPT A crossed 90% of budget committed (now 90%).',
            '1 vendor had no balance movement for 3+ consecutive weeks: VENDOR X.',
            '1 new reconciliation gap appeared between the two reports.',
        ])

    def test_download_counts_reflect_the_actual_row_counts(self):
        self.assertEqual(self.result['commitmentsCount'], f'({len(COMMITMENT_ROWS)} rows)')
        self.assertEqual(self.result['expenditureCount'], f'({len(EXPENDITURE_ROWS)} rows)')
        self.assertIn('parsed dataset', self.result['downloadSub'].lower())

    def test_filtered_csv_reflects_the_unfiltered_latest_scope(self):
        # ALL departments, latest week: every vendor with a positive
        # balance that week, summed across departments, sorted highest
        # first -- not the chart's top-10-excluding-SITA view.
        self.assertEqual(self.result['initial']['filteredCount'], '(3 vendors in current scope)')
        expected = (
            'vendor,outstanding_balance,department_filter,week\r\n'
            'VENDOR BIG,1100000.00,ALL,2026-01-15\r\n'
            'VENDOR Z,20000.00,ALL,2026-01-15\r\n'
            'VENDOR X,150.00,ALL,2026-01-15'
        )
        self.assertEqual(self.result['initialFilteredCsv'], expected)

    def test_filtered_csv_narrows_with_department_filter(self):
        self.assertEqual(self.result['deptFiltered']['filteredCount'], '(1 vendor in current scope)')
        expected = (
            'vendor,outstanding_balance,department_filter,week\r\n'
            'VENDOR X,100.00,DEPT A,2026-01-15'
        )
        self.assertEqual(self.result['deptFilteredCsv'], expected)

    def test_earliest_week_has_no_prior_snapshot(self):
        earliest = self.result['earliestWeek']
        self.assertTrue(earliest['deltaIsEmptyState'])
        self.assertIn('No prior snapshot', earliest['deltaSub'])

    def test_department_filter_narrows_vendor_views(self):
        # DEPT A alone: only vendor X has a nonzero balance in the latest
        # week (vendor Y went to 0 after week 1), so exactly one bar/row.
        self.assertEqual(self.result['firstDept'], 'DEPT A')
        self.assertEqual(self.result['deptFiltered']['vendorBarCount'], 1)
        self.assertEqual(self.result['deptFiltered']['staleRowCount'], 1)
        # Department bars always show every department for comparison,
        # regardless of the filter.
        self.assertEqual(self.result['deptFiltered']['deptBarCount'], 2)

    def test_reset_returns_to_the_unfiltered_latest_view(self):
        self.assertEqual(self.result['afterReset']['deltaSub'], self.result['initial']['deltaSub'])
        self.assertEqual(self.result['afterReset']['vendorBarCount'], self.result['initial']['vendorBarCount'])

    def test_tiles_and_dept_bars_always_render(self):
        for snap_name in ('initial', 'deptFiltered', 'afterReset'):
            with self.subTest(snapshot=snap_name):
                self.assertEqual(self.result[snap_name]['tileCount'], 4)
                self.assertEqual(self.result[snap_name]['deptBarCount'], 2)

    def test_procurement_section_lists_the_flagged_synthetic_split(self):
        # VENDOR BIG's group is flagged in both d1 and d2, and the section
        # is not week-filtered (a rare pattern needs to stay visible even
        # when the user is looking at an earlier snapshot), so both rows
        # show regardless of which week is selected.
        self.assertEqual(self.result['initial']['procurementRowCount'], 2)
        self.assertIn('2 cross', self.result['initial']['procurementSub'])

    def test_procurement_section_narrows_with_department_filter(self):
        # DEPT A has no multi-order groups at all -- just the one
        # "no matches" placeholder row, same pattern as the stale table.
        self.assertEqual(self.result['deptFiltered']['procurementRowCount'], 1)
        self.assertIn('0 same-vendor/item group(s) in DEPT A', self.result['deptFiltered']['procurementSub'])


if __name__ == '__main__':
    unittest.main()
