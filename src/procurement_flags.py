from collections import defaultdict

# Eastern Cape Provincial Treasury Circular No. 03 of 2021/22 (disseminating
# National Treasury PFMA SCM Instruction No. 02 of 2021/22, effective
# 1 July 2021, applicable to all provincial departments): procurement above
# R1,000,000 (inclusive of taxes) requires open competitive bidding;
# R2,000-R1,000,000 requires written price quotations from at least 3
# suppliers. Paragraph 4.1: "Procurement of goods and services may not be
# deliberately split into parts or items of a lesser transaction value in
# order to circumvent the prescribed procurement process... said parts or
# items must as far as possible be treated as a single transaction."
COMPETITIVE_BID_THRESHOLD = 1_000_000.0


def group_multi_order_purchases(commitment_rows):
    """Group commitment rows by (vendor, resp2_desc, item_desc, report_date)
    -- orders to the same vendor, for the same item, outstanding in the same
    weekly snapshot, which is the closest this ledger can get to "orders
    that look like they were procured around the same time for the same
    need." Returns only groups with 2 or more distinct order numbers; a
    single order is never a splitting concern.

    This is a grouping heuristic, not a determination of fact: multiple
    orders in the same group can be entirely legitimate (staggered
    delivery against one contract, genuinely separate needs that happen to
    land in the same week). The point is to surface the pattern for a
    human reviewer, not to assert wrongdoing.
    """
    groups = defaultdict(list)
    for r in commitment_rows:
        if not r['vendor'] or not r['order_no']:
            continue
        key = (r['vendor'], r['resp1_desc'], r['resp2_desc'], r['item_desc'], r['report_date'])
        groups[key].append(r)

    results = []
    for (vendor, resp1, resp2, item, date), rows in groups.items():
        order_nos = sorted(set(r['order_no'] for r in rows))
        if len(order_nos) < 2:
            continue
        amounts = [float(r['commitments_balance']) for r in rows]
        results.append({
            'vendor': vendor,
            'resp1_desc': resp1,
            'resp2_desc': resp2,
            'item_desc': item,
            'report_date': date,
            'order_count': len(order_nos),
            'order_nos': order_nos,
            'amounts': [round(a, 2) for a in amounts],
            'total': round(sum(amounts), 2),
            'max_single_order': round(max(amounts), 2),
        })
    results.sort(key=lambda g: -g['total'])
    return results


def flag_threshold_proximity(groups, threshold=COMPETITIVE_BID_THRESHOLD):
    """Of the multi-order groups, the ones where the combined total crosses
    `threshold` while no single order in the group does on its own -- the
    specific pattern Circular 03/2021-22 paragraph 4.1 prohibits. A group
    where some order already independently exceeds the threshold (e.g. a
    large existing contract being drawn down across several GRVs) is not
    flagged: that value was already presumably subject to the correct
    process on its own, so the combination isn't evidence of evasion.
    """
    return [g for g in groups if g['total'] >= threshold and g['max_single_order'] < threshold]
