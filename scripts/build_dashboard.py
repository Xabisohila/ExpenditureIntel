import csv
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from procurement_flags import group_multi_order_purchases, flag_threshold_proximity, COMPETITIVE_BID_THRESHOLD

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'dashboard_template.html')
OUTPUT_PATH = os.path.join(PROCESSED_DIR, 'dashboard.html')

# Named directly in the template's prose (SITA callout) rather than driven
# purely by rank, so a re-run with new data still reads correctly only if
# this stays the largest vendor.
SITA_VENDOR = 'STATE INFORMATION TEC'


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def build_vendor_records(commitment_rows, dates):
    """Per (vendor, resp1_desc) pair, the full weekly balance series -- the
    portion of that vendor's balance specifically attributable to that
    department, not the vendor's cross-department total. This lets the
    dashboard filter vendor exposure down to a single department without
    losing the ability to also show the all-departments view (sum across
    every resp1 a vendor appears under)."""
    agg = defaultdict(lambda: defaultdict(float))
    for r in commitment_rows:
        vendor = r['vendor']
        if not vendor:
            continue
        key = (vendor, r['resp1_desc'] or '(unknown)')
        agg[key][r['report_date']] += float(r['commitments_balance'])

    records = []
    for (vendor, resp1), by_date in agg.items():
        series = [round(by_date.get(d, 0.0), 2) for d in dates]
        if any(v != 0 for v in series):
            records.append({'vendor': vendor, 'resp1': resp1, 'series': series})
    return records


def build_dept_series(expenditure_rows, dates):
    """Per department, the full weekly [expenses, commitments, budget,
    available_budget, pct] series -- every week, every department, so the
    dashboard can filter/highlight any one of them at any past snapshot
    instead of only ever showing the latest week's ranking."""
    agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))
    for r in expenditure_rows:
        resp1 = r['resp1_desc']
        if not resp1:
            continue
        d = agg[resp1][r['report_date']]
        d[0] += float(r['expenses'])
        d[1] += float(r['commitments'])
        d[2] += float(r['budget'])
        d[3] += float(r['available_budget'])

    dept_series = {}
    for resp1, byweek in agg.items():
        series = []
        for d in dates:
            if d in byweek:
                exp, com, bud, avail = byweek[d]
                pct = round((exp + com) / bud * 100, 1) if bud else None
                series.append({'expenses': round(exp, 2), 'commitments': round(com, 2),
                                'budget': round(bud, 2), 'available': round(avail, 2), 'pct': pct})
            else:
                series.append({'expenses': None, 'commitments': None, 'budget': None, 'available': None, 'pct': None})
        dept_series[resp1] = series
    return dept_series


def build_reconciliation_data(item_recon_rows):
    def is_flagged(r):
        variance = r['variance']
        return bool(r['note']) or (variance not in (None, '') and abs(float(variance)) > 0.01)

    flagged = [r for r in item_recon_rows if is_flagged(r)]
    gaps = [{
        'report_date': r['report_date'],
        'resp2_desc': r['resp2_desc'],
        'item_desc': r['item_desc'],
        'note': r['note'],
        'variance': float(r['variance']) if r['variance'] not in (None, '') else None,
    } for r in flagged]

    return {
        'reconciliation_total': len(item_recon_rows),
        'reconciliation_matched': len(item_recon_rows) - len(flagged),
        'reconciliation_gaps': gaps,
    }


def build_procurement_data(commitment_rows):
    groups = group_multi_order_purchases(commitment_rows)
    flagged = flag_threshold_proximity(groups, threshold=COMPETITIVE_BID_THRESHOLD)
    flagged_keys = {(g['vendor'], g['resp2_desc'], g['item_desc'], g['report_date']) for g in flagged}
    for g in groups:
        g['flagged'] = (g['vendor'], g['resp2_desc'], g['item_desc'], g['report_date']) in flagged_keys
    return {
        'procurement_threshold': COMPETITIVE_BID_THRESHOLD,
        'procurement_groups': groups,
    }


def build_dashboard_data(commitment_rows, expenditure_rows, item_recon_rows):
    """Pure: rows in, the dashboard's DATA dict out. No file I/O, so this is
    directly testable against small synthetic row lists rather than only
    ever against the real (gitignored) dataset."""
    dates = sorted(set(r['report_date'] for r in commitment_rows) | set(r['report_date'] for r in expenditure_rows))

    vendor_records = build_vendor_records(commitment_rows, dates)
    dept_series = build_dept_series(expenditure_rows, dates)
    dept_list = sorted(dept_series.keys())

    data = {
        'dates': dates,
        'sita_vendor': SITA_VENDOR,
        'dept_list': dept_list,
        'dept_series': dept_series,
        'vendor_records': vendor_records,
        'commitments_row_count': len(commitment_rows),
        'expenditure_row_count': len(expenditure_rows),
    }
    data.update(build_reconciliation_data(item_recon_rows))
    data.update(build_procurement_data(commitment_rows))
    return data


def render_html(data, template_path=TEMPLATE_PATH):
    """Pure: DATA dict + template path in, the final HTML string out."""
    json_str = json.dumps(data)
    assert '</script' not in json_str.lower(), "vendor/department names collided with a script-closing tag"

    with open(template_path, encoding='utf-8') as f:
        template = f.read()
    # A replacement *function* (not a string) is required here: re.sub
    # treats backslashes in a string replacement specially (\1, \g<name>,
    # etc.), and JSON-escaped content can easily contain sequences that
    # collide with that. A lambda inserts the return value verbatim.
    html, n = re.subn(r'const DATA = __DATA_JSON__;', lambda m: 'const DATA = ' + json_str + ';', template, count=1)
    assert n == 1, "template's __DATA_JSON__ placeholder not found"
    return html


def main():
    commitment_rows = read_csv(os.path.join(PROCESSED_DIR, 'commitments.csv'))
    expenditure_rows = read_csv(os.path.join(PROCESSED_DIR, 'expenditure.csv'))
    item_recon_rows = read_csv(os.path.join(PROCESSED_DIR, 'reconciliation_item_level.csv'))

    data = build_dashboard_data(commitment_rows, expenditure_rows, item_recon_rows)
    html = render_html(data)

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"wrote {OUTPUT_PATH}")
    print(f"  {len(data['dept_list'])} responsibility units, {len(data['vendor_records'])} vendor/department records "
          f"across {len(data['dates'])} weeks")

    return data


if __name__ == '__main__':
    main()
