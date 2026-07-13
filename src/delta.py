from collections import defaultdict

BUDGET_THRESHOLDS = (50, 75, 90, 100)
NEW_VENDOR_MIN_BALANCE = 10000.0
DEPT_MIN_PCT_JUMP = 2.0
STALE_STREAK_THRESHOLD = 3


def latest_two_dates(dates):
    """Return (previous, latest) from a sorted set of report dates, or
    (None, None) if there's only one week of data (nothing to diff yet)."""
    dates = sorted(set(dates))
    if len(dates) < 2:
        return None, None
    return dates[-2], dates[-1]


def vendor_balance_by_week(vendor_trend_rows):
    """Aggregate commitments_balance to (vendor, date), summing across
    whatever resp2/item combinations that vendor appears under."""
    by_vendor = defaultdict(lambda: defaultdict(float))
    for r in vendor_trend_rows:
        by_vendor[r['vendor']][r['report_date']] += float(r['commitments_balance'])
    return by_vendor


def vendor_deltas(vendor_by_week, dates, prev_date, latest_date):
    """Compare vendor balances between the two most recent snapshots.

    Returns a dict with:
    - newly_stale: vendors whose unchanged-balance streak first reached
      STALE_STREAK_THRESHOLD at latest_date (i.e. this week, not before)
    - paid_off: vendors with a balance at prev_date that dropped to zero
    - new_large: vendors with no balance at prev_date that now have one
      above NEW_VENDOR_MIN_BALANCE
    - big_movers: vendors present at both dates whose balance changed,
      sorted by absolute rand change descending
    """
    streaks = compute_streaks(vendor_by_week, dates)

    newly_stale, paid_off, new_large, big_movers = [], [], [], []
    for vendor, by_date in vendor_by_week.items():
        prev_val = by_date.get(prev_date, 0.0)
        latest_val = by_date.get(latest_date, 0.0)

        if prev_val == 0.0 and latest_val >= NEW_VENDOR_MIN_BALANCE:
            new_large.append({'vendor': vendor, 'balance': round(latest_val, 2)})
        elif prev_val > 0 and latest_val == 0.0:
            paid_off.append({'vendor': vendor, 'prior_balance': round(prev_val, 2)})
        elif prev_val > 0 and latest_val > 0:
            change = latest_val - prev_val
            if abs(change) > 0.01:
                big_movers.append({
                    'vendor': vendor, 'prior_balance': round(prev_val, 2),
                    'latest_balance': round(latest_val, 2), 'change': round(change, 2),
                })
            else:
                streak_latest = streaks[vendor].get(latest_date, 0)
                streak_prev = streaks[vendor].get(prev_date, 0)
                if streak_latest >= STALE_STREAK_THRESHOLD and streak_prev < STALE_STREAK_THRESHOLD:
                    newly_stale.append({
                        'vendor': vendor, 'balance': round(latest_val, 2),
                        'weeks_unchanged': streak_latest,
                    })

    new_large.sort(key=lambda x: -x['balance'])
    paid_off.sort(key=lambda x: -x['prior_balance'])
    big_movers.sort(key=lambda x: -abs(x['change']))
    newly_stale.sort(key=lambda x: -x['balance'])
    return {'newly_stale': newly_stale, 'paid_off': paid_off, 'new_large': new_large, 'big_movers': big_movers}


def compute_streaks(vendor_by_week, dates):
    """For each vendor, the length of the run of consecutive dates (up to
    and including each date) with an identical nonzero balance. Resets to 0
    on a zero balance and to 1 on any change, so a streak only grows when
    the balance has genuinely sat untouched."""
    streaks = {}
    for vendor, by_date in vendor_by_week.items():
        vendor_streaks = {}
        prev_val = None
        streak = 0
        for d in dates:
            val = by_date.get(d, 0.0)
            if val == 0.0:
                streak = 0
                prev_val = None
            elif prev_val is not None and val == prev_val:
                streak += 1
            else:
                streak = 1
                prev_val = val
            vendor_streaks[d] = streak
        streaks[vendor] = vendor_streaks
    return streaks


def dept_pct_by_week(expenditure_rows):
    """Aggregate (expenses + commitments) / budget * 100 to (resp1, date)."""
    agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
    for r in expenditure_rows:
        resp1 = r['resp1_desc']
        if not resp1:
            continue
        d = agg[resp1][r['report_date']]
        d[0] += float(r['expenses'])
        d[1] += float(r['commitments'])
        d[2] += float(r['budget'])

    pct_by_week = defaultdict(dict)
    for resp1, byweek in agg.items():
        for date, (exp, com, bud) in byweek.items():
            pct_by_week[resp1][date] = round((exp + com) / bud * 100, 1) if bud else None
    return pct_by_week


def dept_deltas(pct_by_week, prev_date, latest_date):
    """Compare each department's % of budget committed between the two most
    recent snapshots.

    Returns a dict with:
    - threshold_crossings: departments whose pct crossed one of
      BUDGET_THRESHOLDS between prev_date and latest_date
    - big_movers: departments with a percentage-point jump of at least
      DEPT_MIN_PCT_JUMP, sorted by jump size descending
    """
    crossings, movers = [], []
    for dept, by_date in pct_by_week.items():
        prev_pct = by_date.get(prev_date)
        latest_pct = by_date.get(latest_date)
        if prev_pct is None or latest_pct is None:
            continue
        jump = latest_pct - prev_pct
        crossed = [t for t in BUDGET_THRESHOLDS if prev_pct < t <= latest_pct]
        if crossed:
            crossings.append({'dept': dept, 'prev_pct': prev_pct, 'latest_pct': latest_pct, 'crossed': crossed})
        if abs(jump) >= DEPT_MIN_PCT_JUMP:
            movers.append({'dept': dept, 'prev_pct': prev_pct, 'latest_pct': latest_pct, 'jump': round(jump, 1)})

    crossings.sort(key=lambda x: -max(x['crossed']))
    movers.sort(key=lambda x: -abs(x['jump']))
    return {'threshold_crossings': crossings, 'big_movers': movers}


def reconciliation_deltas(item_recon_rows, prev_date, latest_date):
    """Compare flagged (nonzero-variance or unmatched) reconciliation rows
    between the two most recent snapshots.

    Returns a dict with:
    - newly_flagged: flagged at latest_date but not at prev_date
    - resolved: flagged at prev_date but not at latest_date
    """
    def is_flagged(r):
        variance = r['variance']
        return bool(r['note']) or (variance not in (None, '', 0.0) and abs(float(variance)) > 0.01)

    def key(r):
        return (r['resp2_desc'], r['item_desc'])

    prev_flagged = {key(r): r for r in item_recon_rows if r['report_date'] == prev_date and is_flagged(r)}
    latest_flagged = {key(r): r for r in item_recon_rows if r['report_date'] == latest_date and is_flagged(r)}

    newly_flagged = [latest_flagged[k] for k in latest_flagged if k not in prev_flagged]
    resolved = [prev_flagged[k] for k in prev_flagged if k not in latest_flagged]
    return {'newly_flagged': newly_flagged, 'resolved': resolved}
