# ExpenditureIntel

Parses weekly BAS mainframe financial exports for the Office of the Premier
into structured data, reconciles the two report types against each other,
and publishes a dashboard of vendor exposure and budget burn-down.

**Live dashboard:** https://xabisohila.github.io/ExpenditureIntel/

## What this is

Each week the department produces two reports from the same underlying
mainframe system:

- **Commitment report** (`.xlsx`, e.g. `COM22.06.26.xlsx`) — a vendor/order
  ledger: every outstanding GRV (goods received voucher), grouped by
  programme → responsibility unit → economic item → order → vendor.
- **Expenditure control report** (`.pdf`, e.g. `EXP22.06.26.pdf`) — the same
  hierarchy rolled up to item level, showing expenses, commitments, budget,
  and available budget per item.

Both are hierarchical mainframe dumps, not flat tables — commitment/total
lines interleave with detail lines, hierarchy codes get compressed or
dropped in some weeks, and dash-fill padding occasionally bleeds into
numbers. `src/parsers/` are state machines that recover normalized rows
from this, validating themselves as they go by re-deriving each report's
own printed subtotals and comparing.

`src/reconciliation.py` then cross-checks the vendor ledger's totals
against the expenditure report's per-item commitments figure — two
independently-generated reports that should agree, item by item, vendor
balances summed up to whatever the control report claims is outstanding.
As of the current 7-week dataset, 801 of 802 item/week comparisons match
exactly; the one gap is a specific, verified missing GRV, not a parser
bug (see `tests/test_reconciliation.py`'s `TestFullPipelineReconciliation`
for the pinned detail).

## Quick start

```
pip install -r requirements.txt
python -m unittest discover -s tests
```

The raw `.xlsx`/`.pdf` files are **not in git** (`.gitignore` excludes
`data/raw/*` — real government financial data, and large binary files
don't belong in version control). Without them, the test suite still
runs: the tests that need real files skip themselves and report why
(`raw data files not present (gitignored; expected in CI)`), while every
unit test against synthetic data still runs. This is what CI does on
every push.

To actually run the pipeline you need the raw files locally in
`data/raw/`.

## Pipeline

```
data/raw/*.xlsx, *.pdf
        │
        ▼
scripts/build_dataset.py      parse everything, backfill missing department
        │                     labels, write data/processed/{commitments,expenditure}.csv
        ▼
scripts/reconcile.py          cross-check the two reports, write
        │                     reconciliation_*.csv and vendor_weekly_trend.csv
        ▼
scripts/build_dashboard.py    render data/processed/dashboard.html
        │
        ▼
scripts/weekly_delta.py       print what changed since the previous snapshot
```

Run them in that order, or run `scripts/ingest_week.py` to chain all
four and get a one-paragraph summary of what needs attention (parser
warnings, unresolved department-label blanks, any reconciliation gap
beyond the one known baseline).

### Adding a new week's files

```
python scripts/onboard_and_publish.py --source "C:\path\to\new\files"
```

Finds `.xlsx`/`.pdf` files in `--source` not already in `data/raw/`
(defaults to `~/Downloads/files`), copies each in, parses it standalone
and reports warnings, and — only if everything parsed cleanly — auto-adds
the parser's own reported (filename, date, row count) to both
integration test files' pinned expectations, runs the full pipeline
above, publishes the dashboard to `docs/`, and runs the test suite.

If a file produces a warning or an ambiguous date, the script stops
there and leaves the file for manual inspection rather than pushing
forward with test pins or a dashboard build that might be wrong.

Committing and pushing the new raw files, the test-pin edits, and the
dashboard publish commit stays a manual step — deliberately, so there's
always a review point before anything lands permanently.

### Publishing the dashboard

`scripts/publish_dashboard.py` copies `data/processed/dashboard.html` to
`docs/index.html` and commits if it changed. GitHub Pages serves that
folder directly (Settings → Pages → Deploy from branch → `master` →
`/docs`, a one-time repo setting). This is a manual step run locally,
not something CI does — CI has no access to the raw source data, so it
can't regenerate the dashboard itself.

## Project structure

```
src/parsers/        commitment_xlsx_parser.py, expenditure_pdf_parser.py,
                     common.py — pure parsing, no I/O beyond reading a
                     single file, self-validating against printed subtotals
src/reconciliation.py   cross-report matching + department-label backfill
src/delta.py            week-over-week diffing (streaks, threshold crossings)
scripts/                one script per pipeline stage, thin CLI wrappers
                         around src/ — each also usable standalone
tests/                   78 tests: unit tests against synthetic data (always
                         run) + integration tests pinning known-good output
                         against every real file (skip without data/raw/) +
                         dashboard tests that run the generated <script>
                         under Node (skip without node on PATH)
data/raw/                gitignored — the weekly source files
data/processed/           gitignored — everything the pipeline produces
docs/                    published dashboard (served by GitHub Pages)
```

## Known data quirks

Handled in the parsers, documented in code comments at the point they're
handled rather than here (so the explanation stays next to the regex/logic
it justifies):

- Hierarchy codes are sometimes compressed (`R3` instead of `R 003`) or
  entirely missing for a whole file (one PDF's embedded font drops the
  department header line for every row) — `src/reconciliation.py`'s
  `backfill_resp1_desc*` functions recover the label from the other
  dataset/week rather than leaving it blank.
- Negative amounts appear with either a leading or trailing minus sign
  depending on the week — `src/parsers/common.py`'s `clean_amount`.
- TOTAL lines' dash-fill padding sometimes bleeds a stray `-` into the
  middle of the adjacent number — same function.
- The same item/department name gets truncated to different column widths
  by the two report types, in either direction — `src/reconciliation.py`'s
  `_norm` + bidirectional prefix matching.

## Dashboard

Filterable by responsibility unit and snapshot week; every section
recomputes client-side rather than only ever showing the latest week.
Includes a "Recent changes" panel (newly stale vendors, budget threshold
crossings, reconciliation gaps appearing/resolving) comparing whichever
two consecutive weeks the week filter selects — the same computation as
`weekly_delta.py`, ported to JS so it's visible on the published page
without anyone running a script.

The full parsed datasets (`commitments.csv`, `expenditure.csv` — every
vendor/order and every budget line, across all weeks, not just what's
currently filtered on screen) are downloadable directly from the page,
served as static files from `docs/data/`.
