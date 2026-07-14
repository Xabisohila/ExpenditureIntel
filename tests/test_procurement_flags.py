import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from procurement_flags import group_multi_order_purchases, flag_threshold_proximity, COMPETITIVE_BID_THRESHOLD


def _row(vendor, order_no, resp1, resp2, item, date, balance):
    return {'vendor': vendor, 'order_no': order_no, 'resp1_desc': resp1, 'resp2_desc': resp2,
            'item_desc': item, 'report_date': date, 'commitments_balance': balance}


class TestGroupMultiOrderPurchases(unittest.TestCase):
    def test_single_order_group_excluded(self):
        rows = [_row('V', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 100)]
        self.assertEqual(group_multi_order_purchases(rows), [])

    def test_two_distinct_orders_grouped_and_summed(self):
        rows = [
            _row('V', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 100),
            _row('V', 'OR-2', 'R1', 'R2', 'ITEM', 'd1', 250),
        ]
        [group] = group_multi_order_purchases(rows)
        self.assertEqual(group['order_count'], 2)
        self.assertEqual(group['total'], 350.0)
        self.assertEqual(group['max_single_order'], 250.0)
        self.assertEqual(group['order_nos'], ['OR-1', 'OR-2'])

    def test_same_order_number_appearing_twice_is_not_two_orders(self):
        # A continuation line for the same order (same order_no, different
        # GL split) must not be counted as a second distinct order.
        rows = [
            _row('V', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 100),
            _row('V', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 50),
        ]
        self.assertEqual(group_multi_order_purchases(rows), [])

    def test_different_vendor_item_or_week_are_separate_groups(self):
        rows = [
            _row('V', 'OR-1', 'R1', 'R2', 'ITEM A', 'd1', 100),
            _row('V', 'OR-2', 'R1', 'R2', 'ITEM B', 'd1', 100),  # different item
        ]
        self.assertEqual(group_multi_order_purchases(rows), [])

    def test_blank_vendor_or_order_excluded(self):
        rows = [
            _row('', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 100),
            _row('V', '', 'R1', 'R2', 'ITEM', 'd1', 100),
        ]
        self.assertEqual(group_multi_order_purchases(rows), [])

    def test_results_sorted_by_total_descending(self):
        rows = [
            _row('SMALL', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 10),
            _row('SMALL', 'OR-2', 'R1', 'R2', 'ITEM', 'd1', 20),
            _row('BIG', 'OR-3', 'R1', 'R2', 'ITEM', 'd1', 1000),
            _row('BIG', 'OR-4', 'R1', 'R2', 'ITEM', 'd1', 2000),
        ]
        groups = group_multi_order_purchases(rows)
        self.assertEqual([g['vendor'] for g in groups], ['BIG', 'SMALL'])


class TestFlagThresholdProximity(unittest.TestCase):
    def test_flags_a_genuine_split_below_the_line(self):
        groups = group_multi_order_purchases([
            _row('V', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 600_000),
            _row('V', 'OR-2', 'R1', 'R2', 'ITEM', 'd1', 500_000),
        ])
        flagged = flag_threshold_proximity(groups, threshold=1_000_000)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]['total'], 1_100_000.0)

    def test_does_not_flag_when_one_order_already_exceeds_the_threshold(self):
        # The SITA case: a legitimate large existing contract drawn down
        # across several GRVs, where each individual order already
        # independently exceeds the threshold. Not evidence of splitting.
        groups = group_multi_order_purchases([
            _row('SITA', 'OR-1', 'R1', 'R2', 'DATA LINES', 'd1', 273_961_120.07),
            _row('SITA', 'OR-2', 'R1', 'R2', 'DATA LINES', 'd1', 64_612_051.64),
        ])
        flagged = flag_threshold_proximity(groups, threshold=1_000_000)
        self.assertEqual(flagged, [])

    def test_does_not_flag_when_total_stays_under_threshold(self):
        groups = group_multi_order_purchases([
            _row('V', 'OR-1', 'R1', 'R2', 'ITEM', 'd1', 100),
            _row('V', 'OR-2', 'R1', 'R2', 'ITEM', 'd1', 200),
        ])
        self.assertEqual(flag_threshold_proximity(groups, threshold=1_000_000), [])

    def test_default_threshold_matches_the_treasury_circular(self):
        self.assertEqual(COMPETITIVE_BID_THRESHOLD, 1_000_000.0)


if __name__ == '__main__':
    unittest.main()
