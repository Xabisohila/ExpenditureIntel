import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from delta import (
    latest_two_dates,
    vendor_balance_by_week,
    vendor_deltas,
    dept_pct_by_week,
    dept_deltas,
    reconciliation_deltas,
)

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def fmt_r(n):
    return f"R{n:,.2f}"


def main():
    vendor_trend_rows = read_csv(os.path.join(PROCESSED_DIR, 'vendor_weekly_trend.csv'))
    expenditure_rows = read_csv(os.path.join(PROCESSED_DIR, 'expenditure.csv'))
    item_recon_rows = read_csv(os.path.join(PROCESSED_DIR, 'reconciliation_item_level.csv'))

    dates = [r['report_date'] for r in vendor_trend_rows]
    prev_date, latest_date = latest_two_dates(dates)
    if prev_date is None:
        print("Only one week of data on hand -- nothing to diff against yet.")
        return

    print(f"Week-over-week delta: {prev_date} -> {latest_date}\n")

    vendor_by_week = vendor_balance_by_week(vendor_trend_rows)
    v = vendor_deltas(vendor_by_week, sorted(set(dates)), prev_date, latest_date)

    print(f"NEWLY STALE ({len(v['newly_stale'])}) -- balance just crossed 3+ weeks unchanged:")
    for x in v['newly_stale']:
        print(f"  {x['vendor']:35s} {fmt_r(x['balance']):>16s}  ({x['weeks_unchanged']} weeks unchanged)")
    if not v['newly_stale']:
        print("  (none)")

    print(f"\nPAID OFF ({len(v['paid_off'])}) -- balance dropped to zero this week:")
    for x in v['paid_off'][:10]:
        print(f"  {x['vendor']:35s} was {fmt_r(x['prior_balance']):>16s}")
    if not v['paid_off']:
        print("  (none)")

    print(f"\nNEW VENDORS ({len(v['new_large'])}) -- first appearance, balance >= R10,000:")
    for x in v['new_large'][:10]:
        print(f"  {x['vendor']:35s} {fmt_r(x['balance']):>16s}")
    if not v['new_large']:
        print("  (none)")

    print(f"\nBIGGEST MOVERS ({len(v['big_movers'])} vendors changed balance):")
    for x in v['big_movers'][:10]:
        sign = '+' if x['change'] > 0 else ''
        print(f"  {x['vendor']:35s} {fmt_r(x['prior_balance']):>16s} -> {fmt_r(x['latest_balance']):>16s}  ({sign}{fmt_r(x['change'])})")

    pct_by_week = dept_pct_by_week(expenditure_rows)
    d = dept_deltas(pct_by_week, prev_date, latest_date)

    print(f"\nBUDGET THRESHOLD CROSSINGS ({len(d['threshold_crossings'])}):")
    for x in d['threshold_crossings']:
        print(f"  {x['dept']:35s} {x['prev_pct']}% -> {x['latest_pct']}%  (crossed {', '.join(str(t)+'%' for t in x['crossed'])})")
    if not d['threshold_crossings']:
        print("  (none)")

    print(f"\nBIGGEST BUDGET MOVERS ({len(d['big_movers'])} depts moved >= 2 pts):")
    for x in d['big_movers'][:10]:
        sign = '+' if x['jump'] > 0 else ''
        print(f"  {x['dept']:35s} {x['prev_pct']}% -> {x['latest_pct']}%  ({sign}{x['jump']} pts)")

    r = reconciliation_deltas(item_recon_rows, prev_date, latest_date)
    print(f"\nRECONCILIATION -- newly flagged ({len(r['newly_flagged'])}), resolved ({len(r['resolved'])}):")
    for x in r['newly_flagged']:
        print(f"  NEW GAP: {x['resp2_desc']:35s} {x['item_desc']:30s} {x['note']} variance={x['variance']}")
    for x in r['resolved']:
        print(f"  RESOLVED: {x['resp2_desc']:35s} {x['item_desc']:30s}")
    if not r['newly_flagged'] and not r['resolved']:
        print("  (no change -- reconciliation status stable)")


if __name__ == '__main__':
    main()
