import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from reconciliation import (
    resolve_resp2_canonical,
    build_item_reconciliation,
    build_responsibility_reconciliation,
    build_vendor_weekly_trend,
)

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
    expenditure_rows = read_csv(os.path.join(PROCESSED_DIR, 'expenditure.csv'))
    resp2_map = resolve_resp2_canonical(commitment_rows, expenditure_rows)
    remapped = sum(1 for k, v in resp2_map.items() if k[1] != v)
    print(f"Resolved {len(resp2_map)} resp2 names across both reports ({remapped} needed prefix-matching)\n")

    print("Building item-level reconciliation...")
    item_recon = build_item_reconciliation(commitment_rows, expenditure_rows, resp2_map)
    mismatches = [r for r in item_recon if r['variance'] not in (None, 0.0) or r['note']]
    print(f"  {len(item_recon)} item/week rows, {len(mismatches)} with a variance or unmatched note")
    write_csv(item_recon, os.path.join(PROCESSED_DIR, 'reconciliation_item_level.csv'),
              fieldnames=['report_date', 'resp1_desc', 'resp2_desc', 'item_group_desc', 'item_desc',
                          'commitment_ledger_total', 'expenditure_reported_commitments', 'variance', 'note'])

    print("\nBuilding responsibility-unit-level reconciliation...")
    resp_recon = build_responsibility_reconciliation(commitment_rows, expenditure_rows, resp2_map)
    resp_mismatches = [r for r in resp_recon if r['variance'] != 0.0]
    print(f"  {len(resp_recon)} resp-unit/week rows, {len(resp_mismatches)} with a nonzero variance")
    write_csv(resp_recon, os.path.join(PROCESSED_DIR, 'reconciliation_responsibility_level.csv'),
              fieldnames=['report_date', 'resp1_desc', 'resp2_desc', 'commitment_ledger_total',
                          'expenditure_reported_commitments', 'variance', 'expenses', 'budget', 'available_budget'])

    print("\nBuilding vendor weekly trend...")
    vendor_trend = build_vendor_weekly_trend(commitment_rows)
    write_csv(vendor_trend, os.path.join(PROCESSED_DIR, 'vendor_weekly_trend.csv'),
              fieldnames=['vendor', 'resp2_desc', 'item_desc', 'report_date',
                          'commitments_balance', 'change_from_prior_week'])

    print("\nRemaining flagged rows (nonzero variance or unmatched):")
    flagged = [r for r in item_recon if (r['variance'] not in (None, 0.0)) or r['note']]
    for r in sorted(flagged, key=lambda r: abs(r['variance'] or 0), reverse=True)[:15]:
        print(f"  {r['report_date']} {r['resp2_desc']:35s} {r['item_desc']:35s} "
              f"ledger={r['commitment_ledger_total']:>14,.2f} reported={r['expenditure_reported_commitments']!s:>14} "
              f"variance={r['variance']!s:>14} {r['note']}")
    if not flagged:
        print("  (none)")

    return {
        'item_recon_total': len(item_recon),
        'item_recon_flagged': flagged,
        'resp_recon_flagged_count': len(resp_mismatches),
    }


if __name__ == '__main__':
    main()
