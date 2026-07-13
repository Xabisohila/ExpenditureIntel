import argparse
import ast
import os
import re
import shutil
import sys
import unittest

SCRIPTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.join(SCRIPTS_DIR, '..')
RAW_DIR = os.path.join(PROJECT_ROOT, 'data', 'raw')
TESTS_DIR = os.path.join(PROJECT_ROOT, 'tests')

sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import ingest_week
import publish_dashboard
from parsers.commitment_xlsx_parser import parse_commitment_workbook
from parsers.expenditure_pdf_parser import parse_expenditure_pdf

DEFAULT_SOURCE = os.path.join(os.path.expanduser('~'), 'Downloads', 'files')


def print_header(label):
    print(f"\n{'=' * 80}\n{label}\n{'=' * 80}")


def discover_new_files(source_dir):
    """Files in source_dir with a recognized extension whose name isn't
    already present in data/raw (by filename -- the same de-dup check a
    person would do by eye). Returns (new_xlsx, new_pdf) path lists."""
    if not os.path.isdir(source_dir):
        return [], []
    existing = set(os.listdir(RAW_DIR))
    new_xlsx, new_pdf = [], []
    for name in sorted(os.listdir(source_dir)):
        if name in existing:
            continue
        lower = name.lower()
        if lower.endswith('.xlsx'):
            new_xlsx.append(os.path.join(source_dir, name))
        elif lower.endswith('.pdf'):
            new_pdf.append(os.path.join(source_dir, name))
    return new_xlsx, new_pdf


def smoke_test_and_copy(paths, parse_fn):
    """Copy each file into data/raw, parse it standalone, and report. Returns
    a list of (filename, report_date, row_count, warnings) -- copies happen
    regardless of warnings (so the file is available for inspection), but
    the caller decides whether to proceed based on the warnings returned."""
    results = []
    for path in paths:
        name = os.path.basename(path)
        dest = os.path.join(RAW_DIR, name)
        shutil.copyfile(path, dest)
        rows, warnings = parse_fn(dest)
        dates = {r['report_date'] for r in rows}
        date = sorted(dates)[0] if len(dates) == 1 else None
        print(f"  {name:45s} date={sorted(dates)} rows={len(rows):4d} warnings={len(warnings)}")
        for w in warnings:
            print(f"      WARNING: {w}")
        if len(dates) != 1:
            print(f"      NOTE: expected exactly one report_date, found {sorted(dates)} -- needs manual review")
        results.append((name, date, len(rows), warnings))
    return results


def update_test_cases(test_file_path, new_cases):
    """Insert new_cases (filename, date, row_count) into that file's `cases`
    list, sorted by date, skipping any filename already present. Returns the
    list of filenames actually added."""
    with open(test_file_path, encoding='utf-8') as f:
        content = f.read()

    m = re.search(r'(    cases = \[\n)(.*?)(    \]\n)', content, re.DOTALL)
    if not m:
        raise ValueError(f"Could not find a `cases = [...]` list in {test_file_path}")

    existing = ast.literal_eval('[' + m.group(2).strip().rstrip(',') + ']')
    existing_names = {c[0] for c in existing}

    added = []
    for case in new_cases:
        if case[0] in existing_names:
            continue
        existing.append(case)
        existing_names.add(case[0])
        added.append(case[0])

    if not added:
        return added

    existing.sort(key=lambda c: c[1])
    new_body = ''.join(f"        {tuple(c)!r},\n" for c in existing)
    new_content = content[:m.start()] + m.group(1) + new_body + m.group(3) + content[m.end():]
    with open(test_file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return added


def main():
    parser = argparse.ArgumentParser(description="Discover, ingest, and publish new weekly report files.")
    parser.add_argument('--source', default=DEFAULT_SOURCE,
                         help=f"Directory to look for new files in (default: {DEFAULT_SOURCE})")
    args = parser.parse_args()

    print_header(f"Looking for new files in {args.source}")
    new_xlsx, new_pdf = discover_new_files(args.source)
    if not new_xlsx and not new_pdf:
        print("No new .xlsx/.pdf files found (or source directory doesn't exist). Nothing to do.")
        return
    print(f"Found {len(new_xlsx)} new commitment workbook(s), {len(new_pdf)} new expenditure PDF(s)")

    print_header("Smoke-testing new commitment workbooks")
    xlsx_results = smoke_test_and_copy(new_xlsx, parse_commitment_workbook)

    print_header("Smoke-testing new expenditure PDFs")
    pdf_results = smoke_test_and_copy(new_pdf, parse_expenditure_pdf)

    any_warnings = any(w for _, _, _, w in xlsx_results + pdf_results)
    any_bad_dates = any(d is None for _, d, _, _ in xlsx_results + pdf_results)
    if any_warnings or any_bad_dates:
        print_header("STOPPING HERE")
        print("At least one new file produced parser warnings or an ambiguous report date.")
        print("The file(s) have been copied into data/raw/ for inspection, but test pins were NOT")
        print("updated and the full pipeline was NOT run -- investigate the parser output above first.")
        return

    print_header("Updating test pins")
    xlsx_test_file = os.path.join(TESTS_DIR, 'test_commitment_xlsx_parser.py')
    pdf_test_file = os.path.join(TESTS_DIR, 'test_expenditure_pdf_parser.py')
    added_xlsx = update_test_cases(xlsx_test_file, [(n, d, c) for n, d, c, _ in xlsx_results])
    added_pdf = update_test_cases(pdf_test_file, [(n, d, c) for n, d, c, _ in pdf_results])
    print(f"  {xlsx_test_file}: added {added_xlsx or '(nothing new)'}")
    print(f"  {pdf_test_file}: added {added_pdf or '(nothing new)'}")

    print_header("Running full pipeline (ingest_week)")
    ingest_week.main()

    print_header("Publishing dashboard")
    publish_dashboard.main()

    print_header("Running full test suite")
    suite = unittest.defaultTestLoader.discover(TESTS_DIR)
    # TextTestRunner defaults to stderr; pin it to stdout so this step's
    # output stays in the same stream as everything else instead of
    # interleaving unpredictably when both are redirected together.
    result = unittest.TextTestRunner(verbosity=1, stream=sys.stdout).run(suite)

    print_header("DONE -- what's left for you")
    print(f"New files copied into data/raw/: {[os.path.basename(p) for p in new_xlsx + new_pdf]}")
    print(f"Test suite: {'PASSED' if result.wasSuccessful() else 'FAILED -- investigate before committing'}")
    print("Still needed: review the new raw files and test-pin edits with `git status`/`git diff`,")
    print("commit them, and push (the dashboard publish commit was already made locally by this run).")


if __name__ == '__main__':
    main()
