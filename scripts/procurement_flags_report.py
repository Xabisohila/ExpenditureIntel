import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from procurement_flags import group_multi_order_purchases, flag_threshold_proximity, COMPETITIVE_BID_THRESHOLD

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_csv(rows, path, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows)} rows -> {path}")


def main():
    commitment_rows = read_csv(os.path.join(PROCESSED_DIR, 'commitments.csv'))

    groups = group_multi_order_purchases(commitment_rows)
    flagged = flag_threshold_proximity(groups, threshold=COMPETITIVE_BID_THRESHOLD)
    flagged_keys = {(g['vendor'], g['resp2_desc'], g['item_desc'], g['report_date']) for g in flagged}

    print(f"Threshold: R{COMPETITIVE_BID_THRESHOLD:,.0f} (Eastern Cape Provincial Treasury Circular 03/2021-22)")
    print(f"{len(groups)} same-vendor/item/week groups with 2+ distinct orders")
    print(f"{len(flagged)} flagged: combined total crosses the threshold while no single order does\n")

    for g in flagged:
        print(f"  ! {g['vendor']:25s} {g['resp2_desc']:30s} {g['item_desc']:30s} {g['report_date']}  "
              f"{g['order_count']} orders totaling R{g['total']:,.2f}")

    csv_rows = []
    for g in groups:
        key = (g['vendor'], g['resp2_desc'], g['item_desc'], g['report_date'])
        csv_rows.append({
            'vendor': g['vendor'],
            'resp1_desc': g['resp1_desc'],
            'resp2_desc': g['resp2_desc'],
            'item_desc': g['item_desc'],
            'report_date': g['report_date'],
            'order_count': g['order_count'],
            'order_nos': ';'.join(g['order_nos']),
            'total': g['total'],
            'max_single_order': g['max_single_order'],
            'flagged': key in flagged_keys,
        })
    write_csv(csv_rows, os.path.join(PROCESSED_DIR, 'procurement_flags.csv'),
              fieldnames=['vendor', 'resp1_desc', 'resp2_desc', 'item_desc', 'report_date',
                          'order_count', 'order_nos', 'total', 'max_single_order', 'flagged'])

    return {'groups': groups, 'flagged': flagged}


if __name__ == '__main__':
    main()
