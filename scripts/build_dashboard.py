import csv
import json
import os
import re
from collections import defaultdict

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'dashboard_template.html')
OUTPUT_PATH = os.path.join(PROCESSED_DIR, 'dashboard.html')

# Vendors/departments named directly in the template's prose (SITA callout,
# footer, trend chart) rather than driven purely by rank, so a re-run with
# new data still reads correctly only if these stay the largest.
SITA_VENDOR = 'STATE INFORMATION TEC'
TOP_DEPT_NAMES = ['INTERGRATED YOUTH DEVELOPMENT', 'PROVINCIAL ICT', 'FINANCIAL MANAGEMENT']


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def build_vendor_data(vendor_trend_rows, dates, latest):
    vendor_by_week = defaultdict(lambda: defaultdict(float))
    for r in vendor_trend_rows:
        vendor_by_week[r['vendor']][r['report_date']] += float(r['commitments_balance'])

    vendor_latest = sorted(
        ((v, wk.get(latest, 0.0)) for v, wk in vendor_by_week.items() if wk.get(latest, 0.0) > 0),
        key=lambda x: -x[1],
    )
    total_outstanding = sum(b for _, b in vendor_latest)
    sita_balance = vendor_by_week[SITA_VENDOR][latest]

    top_excl_sita = [(v, b) for v, b in vendor_latest if v != SITA_VENDOR][:10]
    top_vendors_excl_sita = [
        {'vendor': v, 'balance': round(b, 2), 'series': [round(vendor_by_week[v].get(d, 0.0), 2) for d in dates]}
        for v, b in top_excl_sita
    ]

    flat_vendors = []
    for v, wk in vendor_by_week.items():
        present = [d for d in dates if d in wk and wk[d] != 0]
        if len(present) >= 3:
            vals = [wk[d] for d in present]
            if len(set(round(x, 2) for x in vals)) == 1:
                flat_vendors.append({'vendor': v, 'balance': round(vals[0], 2), 'weeks_flat': len(present)})
    flat_vendors.sort(key=lambda x: -x['balance'])

    return {
        'total_outstanding': round(total_outstanding, 2),
        'sita_balance': round(sita_balance, 2),
        'sita_pct_of_total': round(sita_balance / total_outstanding * 100, 1) if total_outstanding else 0.0,
        'num_vendors_outstanding': len(vendor_latest),
        'num_flat_vendors': len(flat_vendors),
        'top_vendors_excl_sita': top_vendors_excl_sita,
        'flat_vendors': flat_vendors,
    }


def build_budget_data(expenditure_rows, dates, latest):
    agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))  # resp1 -> date -> [expenses, commitments, budget, available]
    for r in expenditure_rows:
        resp1 = r['resp1_desc']
        if not resp1:
            continue
        d = agg[resp1][r['report_date']]
        d[0] += float(r['expenses'])
        d[1] += float(r['commitments'])
        d[2] += float(r['budget'])
        d[3] += float(r['available_budget'])

    ranked = []
    for resp1, byweek in agg.items():
        if latest not in byweek:
            continue
        exp, com, bud, avail = byweek[latest]
        if bud <= 0:
            continue
        ranked.append({
            'dept': resp1, 'pct': round((exp + com) / bud * 100, 1),
            'budget': round(bud, 2), 'available': round(avail, 2),
            'expenses': round(exp, 2), 'commitments': round(com, 2),
        })
    ranked.sort(key=lambda x: -x['pct'])

    top_dept_series = {}
    for name in TOP_DEPT_NAMES:
        series = []
        for dt in dates:
            if dt in agg[name]:
                exp, com, bud, avail = agg[name][dt]
                series.append(round((exp + com) / bud * 100, 1) if bud else None)
            else:
                series.append(None)
        top_dept_series[name] = series

    return {
        'num_depts_over_50pct': sum(1 for r in ranked if r['pct'] >= 50),
        'num_depts_total': len(ranked),
        'dept_ranking': ranked,
        'top_dept_series': top_dept_series,
        'top_dept_names': TOP_DEPT_NAMES,
    }


def main():
    vendor_trend_rows = read_csv(os.path.join(PROCESSED_DIR, 'vendor_weekly_trend.csv'))
    expenditure_rows = read_csv(os.path.join(PROCESSED_DIR, 'expenditure.csv'))

    dates = sorted(set(r['report_date'] for r in vendor_trend_rows))
    latest = dates[-1]

    data = {'dates': dates}
    data.update(build_vendor_data(vendor_trend_rows, dates, latest))
    data.update(build_budget_data(expenditure_rows, dates, latest))

    json_str = json.dumps(data)
    assert '</script' not in json_str.lower(), "vendor/department names collided with a script-closing tag"

    with open(TEMPLATE_PATH, encoding='utf-8') as f:
        template = f.read()
    # A replacement *function* (not a string) is required here: re.sub
    # treats backslashes in a string replacement specially (\1, \g<name>,
    # etc.), and JSON-escaped content can easily contain sequences that
    # collide with that. A lambda inserts the return value verbatim.
    html, n = re.subn(r'const DATA = __DATA_JSON__;', lambda m: 'const DATA = ' + json_str + ';', template, count=1)
    assert n == 1, "template's __DATA_JSON__ placeholder not found"

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"wrote {OUTPUT_PATH}")
    print(f"  {data['num_vendors_outstanding']} vendors with outstanding balances, {data['num_flat_vendors']} stale")
    print(f"  {data['num_depts_total']} responsibility units, {data['num_depts_over_50pct']} over 50% of budget committed")


if __name__ == '__main__':
    main()
