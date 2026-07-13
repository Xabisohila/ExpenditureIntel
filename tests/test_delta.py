import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from delta import (
    latest_two_dates,
    vendor_balance_by_week,
    compute_streaks,
    vendor_deltas,
    dept_pct_by_week,
    dept_deltas,
    reconciliation_deltas,
)


def _vendor_row(vendor, date, balance, resp2='RESP2', item='ITEM'):
    return {'vendor': vendor, 'report_date': date, 'commitments_balance': balance, 'resp2_desc': resp2, 'item_desc': item}


def _exp_row(resp1, date, expenses, commitments, budget):
    return {'resp1_desc': resp1, 'report_date': date, 'expenses': expenses, 'commitments': commitments, 'budget': budget}


def _recon_row(date, resp2, item, variance, note=''):
    return {'report_date': date, 'resp2_desc': resp2, 'item_desc': item, 'variance': variance, 'note': note}


class TestLatestTwoDates(unittest.TestCase):
    def test_fewer_than_two_dates_returns_none(self):
        self.assertEqual(latest_two_dates(['2026-06-22']), (None, None))
        self.assertEqual(latest_two_dates([]), (None, None))

    def test_returns_last_two_in_order(self):
        dates = ['2026-06-22', '2026-06-01', '2026-06-29']
        self.assertEqual(latest_two_dates(dates), ('2026-06-22', '2026-06-29'))

    def test_deduplicates(self):
        dates = ['2026-06-22', '2026-06-22', '2026-06-29', '2026-06-29']
        self.assertEqual(latest_two_dates(dates), ('2026-06-22', '2026-06-29'))


class TestVendorBalanceByWeek(unittest.TestCase):
    def test_sums_across_resp2_and_item(self):
        rows = [
            _vendor_row('V', '2026-06-22', 60.0, resp2='A', item='X'),
            _vendor_row('V', '2026-06-22', 40.0, resp2='B', item='Y'),
        ]
        result = vendor_balance_by_week(rows)
        self.assertEqual(result['V']['2026-06-22'], 100.0)


class TestComputeStreaks(unittest.TestCase):
    def test_streak_grows_on_repeat_resets_on_change_or_zero(self):
        dates = ['d1', 'd2', 'd3', 'd4', 'd5']
        by_week = {'V': {'d1': 100.0, 'd2': 100.0, 'd3': 100.0, 'd4': 0.0, 'd5': 50.0}}
        streaks = compute_streaks(by_week, dates)
        self.assertEqual(streaks['V'], {'d1': 1, 'd2': 2, 'd3': 3, 'd4': 0, 'd5': 1})

    def test_streak_resets_on_any_change(self):
        dates = ['d1', 'd2', 'd3']
        by_week = {'V': {'d1': 100.0, 'd2': 150.0, 'd3': 150.0}}
        streaks = compute_streaks(by_week, dates)
        self.assertEqual(streaks['V'], {'d1': 1, 'd2': 1, 'd3': 2})


class TestVendorDeltas(unittest.TestCase):
    def test_newly_stale_only_fires_the_week_the_streak_crosses_threshold(self):
        dates = ['d1', 'd2', 'd3']
        by_week = {'V': {'d1': 100.0, 'd2': 100.0, 'd3': 100.0}}
        # d1->d2: streak goes 1->2, not yet stale. d2->d3: streak goes 2->3, newly stale.
        result_early = vendor_deltas(by_week, dates, 'd1', 'd2')
        self.assertEqual(result_early['newly_stale'], [])
        result_late = vendor_deltas(by_week, dates, 'd2', 'd3')
        self.assertEqual(len(result_late['newly_stale']), 1)
        self.assertEqual(result_late['newly_stale'][0]['vendor'], 'V')
        self.assertEqual(result_late['newly_stale'][0]['weeks_unchanged'], 3)

    def test_paid_off_detected(self):
        dates = ['d1', 'd2']
        by_week = {'V': {'d1': 500.0, 'd2': 0.0}}
        result = vendor_deltas(by_week, dates, 'd1', 'd2')
        self.assertEqual(result['paid_off'], [{'vendor': 'V', 'prior_balance': 500.0}])

    def test_new_large_only_above_threshold(self):
        dates = ['d1', 'd2']
        by_week = {
            'BIG': {'d1': 0.0, 'd2': 50000.0},
            'SMALL': {'d1': 0.0, 'd2': 500.0},
        }
        result = vendor_deltas(by_week, dates, 'd1', 'd2')
        vendors_flagged = {x['vendor'] for x in result['new_large']}
        self.assertEqual(vendors_flagged, {'BIG'})

    def test_big_mover_reports_signed_change(self):
        dates = ['d1', 'd2']
        by_week = {'V': {'d1': 1000.0, 'd2': 700.0}}
        result = vendor_deltas(by_week, dates, 'd1', 'd2')
        [mover] = result['big_movers']
        self.assertEqual(mover['change'], -300.0)

    def test_unchanged_below_stale_threshold_is_not_flagged_anywhere(self):
        dates = ['d1', 'd2']
        by_week = {'V': {'d1': 100.0, 'd2': 100.0}}
        result = vendor_deltas(by_week, dates, 'd1', 'd2')
        self.assertEqual(result['newly_stale'], [])
        self.assertEqual(result['big_movers'], [])
        self.assertEqual(result['paid_off'], [])
        self.assertEqual(result['new_large'], [])


class TestDeptPctByWeek(unittest.TestCase):
    def test_computes_percent_committed(self):
        rows = [_exp_row('DEPT', '2026-06-22', 30.0, 20.0, 100.0)]
        result = dept_pct_by_week(rows)
        self.assertEqual(result['DEPT']['2026-06-22'], 50.0)

    def test_zero_budget_is_none_not_a_crash(self):
        rows = [_exp_row('DEPT', '2026-06-22', 30.0, 20.0, 0.0)]
        result = dept_pct_by_week(rows)
        self.assertIsNone(result['DEPT']['2026-06-22'])

    def test_blank_resp1_excluded(self):
        rows = [_exp_row('', '2026-06-22', 30.0, 20.0, 100.0)]
        result = dept_pct_by_week(rows)
        self.assertEqual(result, {})


class TestDeptDeltas(unittest.TestCase):
    def test_threshold_crossing_detected_at_boundary(self):
        pct_by_week = {'DEPT': {'d1': 49.0, 'd2': 50.0}}
        result = dept_deltas(pct_by_week, 'd1', 'd2')
        self.assertEqual(len(result['threshold_crossings']), 1)
        self.assertEqual(result['threshold_crossings'][0]['crossed'], [50])

    def test_no_crossing_when_already_above(self):
        pct_by_week = {'DEPT': {'d1': 60.0, 'd2': 61.0}}
        result = dept_deltas(pct_by_week, 'd1', 'd2')
        self.assertEqual(result['threshold_crossings'], [])

    def test_multiple_thresholds_crossed_at_once(self):
        pct_by_week = {'DEPT': {'d1': 40.0, 'd2': 80.0}}
        result = dept_deltas(pct_by_week, 'd1', 'd2')
        self.assertEqual(result['threshold_crossings'][0]['crossed'], [50, 75])

    def test_big_mover_requires_minimum_jump(self):
        pct_by_week = {
            'BIG': {'d1': 40.0, 'd2': 43.0},
            'SMALL': {'d1': 40.0, 'd2': 41.0},
        }
        result = dept_deltas(pct_by_week, 'd1', 'd2')
        movers = {x['dept'] for x in result['big_movers']}
        self.assertEqual(movers, {'BIG'})


class TestReconciliationDeltas(unittest.TestCase):
    def test_newly_flagged_detected(self):
        rows = [
            _recon_row('d1', 'R2', 'ITEM', 0.0, ''),
            _recon_row('d2', 'R2', 'ITEM', -100.0, 'NO_LEDGER_DETAIL'),
        ]
        result = reconciliation_deltas(rows, 'd1', 'd2')
        self.assertEqual(len(result['newly_flagged']), 1)
        self.assertEqual(result['newly_flagged'][0]['note'], 'NO_LEDGER_DETAIL')
        self.assertEqual(result['resolved'], [])

    def test_resolved_detected(self):
        rows = [
            _recon_row('d1', 'R2', 'ITEM', -100.0, 'NO_LEDGER_DETAIL'),
            _recon_row('d2', 'R2', 'ITEM', 0.0, ''),
        ]
        result = reconciliation_deltas(rows, 'd1', 'd2')
        self.assertEqual(result['newly_flagged'], [])
        self.assertEqual(len(result['resolved']), 1)

    def test_stable_flag_is_neither_new_nor_resolved(self):
        rows = [
            _recon_row('d1', 'R2', 'ITEM', -100.0, 'NO_LEDGER_DETAIL'),
            _recon_row('d2', 'R2', 'ITEM', -100.0, 'NO_LEDGER_DETAIL'),
        ]
        result = reconciliation_deltas(rows, 'd1', 'd2')
        self.assertEqual(result['newly_flagged'], [])
        self.assertEqual(result['resolved'], [])


if __name__ == '__main__':
    unittest.main()
