import os
import sys

SCRIPTS_DIR = os.path.dirname(__file__)
sys.path.insert(0, SCRIPTS_DIR)

import build_dataset
import reconcile
import build_dashboard
import weekly_delta
import procurement_flags_report

# The one gap known to genuinely exist across all weeks parsed so far (see
# tests/test_reconciliation.py's TestFullPipelineReconciliation, which pins
# the same fact). Reconciliation flagging anything beyond this baseline
# means a newly-added file introduced a real discrepancy, not that the
# baseline itself needs updating -- investigate before assuming otherwise.
KNOWN_BASELINE_GAP = ('2026-07-06', 'INTERGRATED YOUTH DEVELO - SUPPP', 'CATERING:DEPARTMENTL ACTIVITIES')


def print_header(label):
    print(f"\n{'=' * 80}\n{label}\n{'=' * 80}")


def main():
    print_header("STEP 1/5: Building combined datasets")
    dataset_summary = build_dataset.main()

    print_header("STEP 2/5: Reconciling commitments vs expenditure")
    reconcile_summary = reconcile.main()

    print_header("STEP 3/5: Checking procurement threshold proximity")
    procurement_summary = procurement_flags_report.main()

    print_header("STEP 4/5: Building dashboard")
    build_dashboard.main()

    print_header("STEP 5/5: Computing week-over-week delta")
    delta_summary = weekly_delta.main()

    print_header("INGESTION SUMMARY")
    attention_needed = False

    total_warnings = dataset_summary['commitment_warnings'] + dataset_summary['expenditure_warnings']
    if total_warnings:
        attention_needed = True
        print(f"! {total_warnings} parser warning(s) -- a new file may have an unhandled quirk. See STEP 1 output above.")
    else:
        print(f"OK: all {dataset_summary['num_files']} source files parsed with 0 warnings.")

    still_blank = dataset_summary['still_blank_resp1_commitment'] + dataset_summary['still_blank_resp1_expenditure']
    if still_blank:
        attention_needed = True
        print(f"! {still_blank} row(s) still have no resp1_desc after both backfill passes "
              f"-- a new department-name variant may need the backfill logic extended.")

    flagged = reconcile_summary['item_recon_flagged']
    new_gaps = [r for r in flagged if (r['report_date'], r['resp2_desc'], r['item_desc']) != KNOWN_BASELINE_GAP]
    if new_gaps:
        attention_needed = True
        print(f"! {len(new_gaps)} NEW reconciliation gap(s) beyond the known baseline:")
        for r in new_gaps:
            print(f"    {r['report_date']} {r['resp2_desc']} / {r['item_desc']} variance={r['variance']} {r['note']}")
    elif len(flagged) == 1:
        print("OK: reconciliation shows only the known baseline gap (Integrated Youth Development catering, 2026-07-06).")
    else:
        attention_needed = True
        print("! Reconciliation shows 0 gaps -- the known baseline gap appears to have resolved. "
              "If a new file explains this, update tests/test_reconciliation.py's pinned expectation.")

    if procurement_summary['flagged']:
        attention_needed = True
        print(f"\n! {len(procurement_summary['flagged'])} procurement threshold-proximity flag(s) "
              f"(combined same-vendor/item/week orders crossing R1,000,000 with no single order doing so) "
              f"-- see data/processed/procurement_flags.csv. Not evidence of wrongdoing on its own; "
              f"warrants a supply-chain-management look.")
    else:
        print(f"\nOK: no procurement threshold-proximity flags "
              f"({len(procurement_summary['groups'])} multi-order groups checked against R1,000,000).")

    if delta_summary['has_delta']:
        v, d, r = delta_summary['vendor_deltas'], delta_summary['dept_deltas'], delta_summary['reconciliation_deltas']
        print(f"\nWeek-over-week ({delta_summary['prev_date']} -> {delta_summary['latest_date']}):")
        print(f"  {len(v['newly_stale'])} newly stale vendor(s), {len(v['paid_off'])} paid off, {len(v['new_large'])} new")
        print(f"  {len(d['threshold_crossings'])} budget threshold crossing(s)")
        if r['newly_flagged']:
            attention_needed = True
            print(f"  ! {len(r['newly_flagged'])} newly-flagged reconciliation gap(s) in the latest week specifically")

    print()
    if attention_needed:
        print("Something above needs a look before trusting this data -- see the step output for detail.")
    else:
        print("Nothing unexpected. If any new source files were added, remember to add their filename/date/row-count "
              "to the cases lists in tests/test_commitment_xlsx_parser.py and tests/test_expenditure_pdf_parser.py, "
              "then run the test suite before committing.")


if __name__ == '__main__':
    main()
