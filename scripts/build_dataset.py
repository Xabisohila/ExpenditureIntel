import csv
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from parsers.commitment_xlsx_parser import parse_commitment_workbook
from parsers.expenditure_pdf_parser import parse_expenditure_pdf
from reconciliation import backfill_resp1_desc, backfill_resp1_desc_cross_dataset

RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')


def write_csv(rows, path):
    if not rows:
        print(f"  (no rows to write for {path})")
        return
    fieldnames = list(rows[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows)} rows -> {path}")


def main():
    xlsx_paths = sorted(glob.glob(os.path.join(RAW_DIR, '*.xlsx')))
    pdf_paths = sorted(glob.glob(os.path.join(RAW_DIR, '*.pdf')))

    print(f"Found {len(xlsx_paths)} commitment workbooks, {len(pdf_paths)} expenditure PDFs\n")

    all_commitment_rows = []
    total_commitment_warnings = 0
    print("Commitment workbooks:")
    for path in xlsx_paths:
        rows, warnings = parse_commitment_workbook(path)
        dates = {r['report_date'] for r in rows}
        print(f"  {os.path.basename(path):45s} date={sorted(dates)} rows={len(rows):4d} warnings={len(warnings)}")
        for w in warnings:
            print(f"      WARNING: {w}")
        total_commitment_warnings += len(warnings)
        all_commitment_rows.extend(rows)

    all_expenditure_rows = []
    total_expenditure_warnings = 0
    print("\nExpenditure PDFs:")
    for path in pdf_paths:
        rows, warnings = parse_expenditure_pdf(path)
        dates = {r['report_date'] for r in rows}
        print(f"  {os.path.basename(path):45s} date={sorted(dates)} rows={len(rows):4d} warnings={len(warnings)}")
        for w in warnings:
            print(f"      WARNING: {w}")
        total_expenditure_warnings += len(warnings)
        all_expenditure_rows.extend(rows)

    all_commitment_rows.sort(key=lambda r: (r['report_date'] or '', r['sheet']))
    all_expenditure_rows.sort(key=lambda r: (r['report_date'] or '',))

    print(f"\nTotal: {len(all_commitment_rows)} commitment rows ({total_commitment_warnings} warnings), "
          f"{len(all_expenditure_rows)} expenditure rows ({total_expenditure_warnings} warnings)")

    all_commitment_rows, filled, ambiguous = backfill_resp1_desc(all_commitment_rows)
    print(f"\nBackfilled resp1_desc for {filled} commitment rows"
          + (f" ({len(ambiguous)} resp2 values left ambiguous: {sorted(ambiguous)})" if ambiguous else ""))
    all_expenditure_rows, filled, ambiguous = backfill_resp1_desc(all_expenditure_rows)
    print(f"Backfilled resp1_desc for {filled} expenditure rows"
          + (f" ({len(ambiguous)} resp2 values left ambiguous: {sorted(ambiguous)})" if ambiguous else ""))

    # Mop up stragglers whose resp2 spelling is a truncation variant unique
    # to one file (so the same-dataset backfill above had no source row to
    # copy from) by cross-referencing the other dataset for the same week.
    all_commitment_rows, cross_filled_c = backfill_resp1_desc_cross_dataset(all_commitment_rows, all_expenditure_rows)
    all_expenditure_rows, cross_filled_e = backfill_resp1_desc_cross_dataset(all_expenditure_rows, all_commitment_rows)
    print(f"Cross-dataset backfill: {cross_filled_c} more commitment rows, {cross_filled_e} more expenditure rows")

    still_blank_c = sum(1 for r in all_commitment_rows if not r['resp1_desc'])
    still_blank_e = sum(1 for r in all_expenditure_rows if not r['resp1_desc'])
    if still_blank_c or still_blank_e:
        print(f"  still blank: {still_blank_c} commitment rows, {still_blank_e} expenditure rows")

    write_csv(all_commitment_rows, os.path.join(OUT_DIR, 'commitments.csv'))
    write_csv(all_expenditure_rows, os.path.join(OUT_DIR, 'expenditure.csv'))


if __name__ == '__main__':
    main()
