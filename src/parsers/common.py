import re

DATE_RE = re.compile(r'DATE:\s*(\d{2})/(\d{2})/(\d{4})')


def parse_report_date_from_text(text: str):
    """Extract the report's 'as at' date from header text, as ISO YYYY-MM-DD.

    Filenames encode the date inconsistently across weekly exports
    (COM22.06.26.xlsx vs 'COMMITMENT REPORT 01.06.2026.xlsx' vs
    COMM13.07.26.xlsx), so the date is read from the report's own printed
    'DATE: dd/mm/yyyy' header instead of trusting the filename.
    """
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = m.groups()
    return f'{y}-{mo}-{d}'


def extract_xlsx_report_date(wb):
    ws = wb[wb.sheetnames[0]]
    for r in range(1, 6):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and 'DATE:' in v.upper():
                date = parse_report_date_from_text(v)
                if date:
                    return date
    return None


def extract_pdf_report_date(pdf):
    text = pdf.pages[0].extract_text() or ''
    return parse_report_date_from_text(text)


# The mainframe dump right-pads descriptions with dashes up to a fixed column
# width before the first amount. When a description is long, that dash-fill
# shrinks to nothing and glues directly onto the number with no separating
# space; in the PDF export the same fill occasionally has a stray '-'
# spliced into the middle of the digits themselves. Both cases are handled
# by treating any run of [0-9,.\-] as "amount-ish" and stripping noise dashes.
DASH_RUN_RE = re.compile(r'[\d,.\-]+$')


def clean_amount(raw) -> float:
    """Parse a mainframe amount field, tolerating dash-fill corruption."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s in ('', '-'):
        return 0.0
    # COBOL-style reports sometimes render the sign as a trailing '-'
    # ("4,040.00-") instead of a leading one; support both, but only when
    # there's a single dash (multiple dashes indicate fill-corruption noise,
    # not a sign, handled below).
    single_dash = s.count('-') == 1
    negative = single_dash and (
        (s[0] == '-' and len(s) > 1 and s[1].isdigit())
        or (s[-1] == '-' and len(s) > 1 and s[-2].isdigit())
    )
    digits = re.sub(r'[^\d.,]', '', s).replace(',', '')
    if digits in ('', '.'):
        return 0.0
    value = float(digits)
    return -value if negative else value


def split_trailing_amounts(text: str, n: int):
    """Split `text` into (description, [n raw amount strings]).

    Assumes the last n fields are whitespace-delimited amounts, except the
    first of the n may be glued to the tail of the description (see
    DASH_RUN_RE above). Returns None if `text` doesn't contain n amount
    fields at all (i.e. it's a pure hierarchy-header line with no values).
    """
    text = text.strip()
    if not text:
        return None
    parts = text.rsplit(None, n - 1)
    if len(parts) < n:
        return None
    head, tail = parts[0], parts[1:]
    # Guard against descriptions that merely end in a digit/comma/period (e.g.
    # "ECONO, TRADE AND ADVISORY") being mistaken for amount fields: a real
    # amount token has no letters mixed in.
    if not all(re.search(r'\d', t) and not re.search(r'[A-Za-z]', t) for t in tail):
        return None
    m = DASH_RUN_RE.search(head)
    if not m or not re.search(r'\d', m.group(0)):
        return None
    first = m.group(0)
    description = head[: m.start()].strip()
    return description, [first] + tail
