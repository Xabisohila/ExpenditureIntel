import os
import re
import pdfplumber

from .common import clean_amount, split_trailing_amounts, extract_pdf_report_date

# Digit count is 1-3: the R-level code is sometimes printed compressed with
# no space and no zero-padding ("R3PREMIER SUPPORT STAFF" instead of
# "R 003 PREMIER SUPPORT STAFF"); comparing the parsed int below still works
# regardless of padding.
LEVEL_RE = re.compile(r'^(TOTAL\s+)?([FORI])\s*(\d{1,3})(.*)$')

SKIP_RES = [
    re.compile(r'^BAS DATE:'),
    re.compile(r'EC: OFFICE OF THE PREMIER'),
    re.compile(r'^RP\d+BS'),
    re.compile(r'^FOR FINANCIAL YEAR'),
    re.compile(r'^REPORT INTRODUCTORY PAGE'),
    re.compile(r'^TYPE\b'),
    re.compile(r'^LEVEL\s+DESCRIPTION'),
    re.compile(r'^[\-\s]+$'),
    re.compile(r'^\*{2,}\s*END OF REPORT'),
]

N_AMOUNTS = 4  # expenses, commitments, budget, available budget


def _is_junk(line):
    return not line.strip() or any(p.search(line) for p in SKIP_RES)


def parse_expenditure_pdf(path):
    rows_out = []
    warnings = []
    ctx = {'fund': None, 'o1': None, 'o2': None, 'r1': None, 'r2': None, 'item_group': None}

    # Running subtotals mirror the report's own nested TOTAL lines.
    item_group_sum = [0.0, 0.0, 0.0, 0.0]
    r2_sum = [0.0, 0.0, 0.0, 0.0]
    r1_sum = [0.0, 0.0, 0.0, 0.0]
    o2_sum = [0.0, 0.0, 0.0, 0.0]
    o1_sum = [0.0, 0.0, 0.0, 0.0]

    def add_to_running(amounts):
        for acc in (item_group_sum, r2_sum, r1_sum, o2_sum, o1_sum):
            for i in range(4):
                acc[i] += amounts[i]

    def make_row(item_code, item_desc, amounts):
        return {
            'source_file': os.path.basename(path),
            'report_date': report_date,
            'fund_code': ctx['fund'][0] if ctx['fund'] else None,
            'fund_desc': ctx['fund'][1] if ctx['fund'] else None,
            'prog1_code': ctx['o1'][0] if ctx['o1'] else None,
            'prog1_desc': ctx['o1'][1] if ctx['o1'] else None,
            'prog2_code': ctx['o2'][0] if ctx['o2'] else None,
            'prog2_desc': ctx['o2'][1] if ctx['o2'] else None,
            'resp1_code': ctx['r1'][0] if ctx['r1'] else None,
            'resp1_desc': ctx['r1'][1] if ctx['r1'] else None,
            'resp2_code': ctx['r2'][0] if ctx['r2'] else None,
            'resp2_desc': ctx['r2'][1] if ctx['r2'] else None,
            'item_group_code': ctx['item_group'][0] if ctx['item_group'] else None,
            'item_group_desc': ctx['item_group'][1] if ctx['item_group'] else None,
            'item_code': item_code,
            'item_desc': item_desc,
            'expenses': amounts[0],
            'commitments': amounts[1],
            'budget': amounts[2],
            'available_budget': amounts[3],
        }

    with pdfplumber.open(path) as pdf:
        report_date = extract_pdf_report_date(pdf)
        for page in pdf.pages:
            text = page.extract_text() or ''
            for raw_line in text.split('\n'):
                line = raw_line.strip()
                if _is_junk(line):
                    continue

                m = LEVEL_RE.match(line)
                if not m:
                    continue  # not a hierarchy/amount line (shouldn't occur in this report)

                is_total = bool(m.group(1))
                letter, num, rest = m.group(2), int(m.group(3)), m.group(4)
                split = split_trailing_amounts(rest, N_AMOUNTS)

                if is_total:
                    if split is None:
                        continue
                    description, raw_amounts = split
                    reported = tuple(clean_amount(a) for a in raw_amounts)
                    if letter == 'I' and num == 3:
                        actual, label = tuple(item_group_sum), f"I003 {ctx['item_group'][1] if ctx['item_group'] else '?'}"
                    elif letter == 'R' and num == 4:
                        actual, label = tuple(r2_sum), f"R004 {ctx['r2'][1] if ctx['r2'] else '?'}"
                    elif letter == 'R' and num == 3:
                        actual, label = tuple(r1_sum), f"R003 {ctx['r1'][1] if ctx['r1'] else '?'}"
                    elif letter == 'O' and num == 7:
                        actual, label = tuple(o2_sum), f"O007 {ctx['o2'][1] if ctx['o2'] else '?'}"
                    elif letter == 'O' and num == 6:
                        actual, label = tuple(o1_sum), f"O006 {ctx['o1'][1] if ctx['o1'] else '?'}"
                    else:
                        actual, label = None, None
                    if actual is not None and any(abs(a - b) > 0.01 for a, b in zip(actual, reported)):
                        warnings.append(f"TOTAL mismatch for {label}: computed={actual} reported={reported}")
                    continue

                if split is None:
                    # Pure hierarchy header line: push onto the stack per its fixed code.
                    description = rest.strip()
                    if letter == 'F':
                        ctx.update(fund=(f'F{num:03d}', description), o1=None, o2=None, r1=None, r2=None, item_group=None)
                    elif letter == 'O' and num == 6:
                        ctx.update(o1=(f'O{num:03d}', description), o2=None, r1=None, r2=None, item_group=None)
                        o1_sum[:] = [0.0, 0.0, 0.0, 0.0]
                    elif letter == 'O' and num == 7:
                        ctx.update(o2=(f'O{num:03d}', description), r1=None, r2=None, item_group=None)
                        o2_sum[:] = [0.0, 0.0, 0.0, 0.0]
                    elif letter == 'R' and num == 3:
                        ctx.update(r1=(f'R{num:03d}', description), r2=None, item_group=None)
                        r1_sum[:] = [0.0, 0.0, 0.0, 0.0]
                    elif letter == 'R' and num == 4:
                        ctx.update(r2=(f'R{num:03d}', description), item_group=None)
                        r2_sum[:] = [0.0, 0.0, 0.0, 0.0]
                    elif letter == 'I' and num == 3:
                        ctx.update(item_group=(f'I{num:03d}', description))
                        item_group_sum[:] = [0.0, 0.0, 0.0, 0.0]
                    # else: unexpected header-only line for a leaf code; skip.
                else:
                    # Leaf item line: description + its own 4 amounts.
                    description, raw_amounts = split
                    amounts = [clean_amount(a) for a in raw_amounts]
                    rows_out.append(make_row(f'I{num:03d}', description, amounts))
                    add_to_running(amounts)

    return rows_out, warnings
