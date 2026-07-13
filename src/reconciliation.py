from collections import defaultdict


def backfill_resp1_desc(rows):
    """Fill in blank resp1_desc using the resp2_desc -> resp1_desc mapping
    learned from every other row in the same dataset that has one.

    resp2 (the responsibility sub-unit) belongs to exactly one resp1 (the
    branch/chief directorate) as a structural fact of the org hierarchy --
    confirmed unique with zero conflicts across every week in both the
    commitment and expenditure datasets. This is a safe fill rather than a
    guess: it covers cases where a source file has corrupted or missing
    R-003 header text (e.g. the entire 2026-06-01 expenditure PDF, whose
    embedded font encoding drops that line for every department) but the
    row's other fields, including resp2_desc, are otherwise correct.

    Mutates and returns `rows`. If a resp2_desc maps to more than one
    resp1_desc elsewhere in the dataset, it's genuinely ambiguous and is
    left blank rather than guessed. Returns (rows, filled_count, ambiguous_resp2s).
    """
    resp2_to_resp1 = defaultdict(set)
    for r in rows:
        if r['resp1_desc']:
            resp2_to_resp1[r['resp2_desc']].add(r['resp1_desc'])

    ambiguous = {r2 for r2, resp1s in resp2_to_resp1.items() if len(resp1s) > 1}
    filled = 0
    for r in rows:
        if not r['resp1_desc'] and r['resp2_desc'] not in ambiguous:
            resp1s = resp2_to_resp1.get(r['resp2_desc'])
            if resp1s:
                r['resp1_desc'] = next(iter(resp1s))
                filled += 1
    return rows, filled, ambiguous


def backfill_resp1_desc_cross_dataset(rows, other_rows):
    """Second-pass backfill for rows whose resp2_desc spelling is a
    truncation variant unique to one file, so it never appears elsewhere in
    the same dataset with a resp1_desc attached (backfill_resp1_desc alone
    can't help). Falls back to the other dataset's resp2 -> resp1 mapping
    for the same week, using the same normalized bidirectional prefix match
    as resolve_resp2_canonical.

    Mutates and returns (rows, filled_count).
    """
    other_map = defaultdict(dict)  # report_date -> {resp2_desc: resp1_desc}
    for r in other_rows:
        if r['resp1_desc']:
            other_map[r['report_date']][r['resp2_desc']] = r['resp1_desc']

    filled = 0
    for r in rows:
        if r['resp1_desc']:
            continue
        candidates = other_map.get(r['report_date'], {})
        if r['resp2_desc'] in candidates:
            r['resp1_desc'] = candidates[r['resp2_desc']]
            filled += 1
            continue
        norm_resp2 = _norm(r['resp2_desc'])
        matches = [resp1 for resp2, resp1 in candidates.items()
                   if _norm(resp2).startswith(norm_resp2) or norm_resp2.startswith(_norm(resp2))]
        if len(set(matches)) == 1:
            r['resp1_desc'] = matches[0]
            filled += 1
    return rows, filled


def _norm(text):
    # The mainframe splits long descriptions across fixed-width columns at a
    # character position, not a word boundary, so the truncation point
    # occasionally lands exactly on a space and swallows it (e.g.
    # 'MEMB&SUBSC' + 'F' for the real text 'MEMB&SUBSC FEES'). Comparing with
    # spaces stripped makes prefix matching tolerant of that either way.
    return text.replace(' ', '')


def resolve_resp2_canonical(commitment_rows, expenditure_rows):
    """Map each commitment-side resp2_desc to its expenditure-side spelling
    for the same week.

    resp2_desc (the responsibility sub-unit name) is truncated to a
    different column width in each report, so the same unit can read
    differently on each side for a given week (e.g. ledger: 'MEDIA RELA,
    CONTENT PROD & MANA' vs expenditure: 'MEDIA RELA, CONTENT PROD &
    MANAG') -- this bites hardest on the vendor-rollup-only weeks whose
    6-column layout truncates more aggressively. Matched the same way as
    item descriptions: exact text first, then a normalized prefix match
    within the same report_date.
    """
    exp_resp2_by_date = defaultdict(set)
    for r in expenditure_rows:
        exp_resp2_by_date[r['report_date']].add(r['resp2_desc'])

    commit_resp2_by_date = defaultdict(set)
    for r in commitment_rows:
        commit_resp2_by_date[r['report_date']].add(r['resp2_desc'])

    mapping = {}
    for date, commit_resp2s in commit_resp2_by_date.items():
        exp_resp2s = exp_resp2_by_date.get(date, set())
        for resp2 in commit_resp2s:
            if resp2 in exp_resp2s:
                mapping[(date, resp2)] = resp2
                continue
            # Truncation isn't consistently one-directional: usually the
            # ledger's column is narrower, but occasionally the
            # expenditure report's is, so check both.
            norm_resp2 = _norm(resp2)
            candidates = [e for e in exp_resp2s
                          if _norm(e).startswith(norm_resp2) or norm_resp2.startswith(_norm(e))]
            mapping[(date, resp2)] = candidates[0] if len(candidates) == 1 else resp2
    return mapping


def build_item_reconciliation(commitment_rows, expenditure_rows, resp2_map):
    """Reconcile the vendor/order-level commitment ledger against the
    per-item 'commitments' figure the expenditure control report shows for
    the same responsibility unit.

    Two cross-report quirks are handled here rather than by exact-key
    matching:
    - The two reports truncate item descriptions to different column widths
      (e.g. ledger: 'CATERING:DEPARTMENTL ACTIVIT' vs expenditure:
      'CATERING:DEPARTMENTL ACTIVITIES'), so items are matched by exact text
      first, falling back to a prefix match within the same (resp2,
      item_group) bucket when either side's truncated text is a prefix of
      the other.
    - resp1_desc is dropped from the join key: one source PDF (the oldest,
      differently-generated export) has corrupted/missing R-003 header text
      for several departments, leaving resp1_desc blank there even though
      the underlying figures are intact. resp2_desc alone is confirmed
      unique per resp1 in both datasets for every week, so it's a safe join
      key; resp1_desc is carried through only as a display field.
    """
    exp_index = defaultdict(dict)
    resp1_by_resp2 = {}
    for r in expenditure_rows:
        key = (r['report_date'], r['resp2_desc'], r['item_group_desc'])
        exp_index[key][r['item_desc']] = float(r['commitments'])
        if r['resp1_desc']:
            resp1_by_resp2.setdefault((r['report_date'], r['resp2_desc']), r['resp1_desc'])

    ledger_totals = defaultdict(float)
    for r in commitment_rows:
        resp2 = resp2_map.get((r['report_date'], r['resp2_desc']), r['resp2_desc'])
        key = (r['report_date'], resp2, r['item_group_desc'], r['item_desc'])
        ledger_totals[key] += float(r['commitments_balance'])
        resp1_by_resp2.setdefault((r['report_date'], resp2), r['resp1_desc'])

    results = []
    matched_exp_keys = set()

    for (date, resp2, item_group, item_desc), total in ledger_totals.items():
        bucket = exp_index.get((date, resp2, item_group), {})
        canonical, reported, note = item_desc, None, ''
        if item_desc in bucket:
            reported = bucket[item_desc]
        else:
            norm_item = _norm(item_desc)
            candidates = [k for k in bucket
                          if _norm(k).startswith(norm_item) or norm_item.startswith(_norm(k))]
            if len(candidates) == 1:
                canonical = candidates[0]
                reported = bucket[canonical]
            elif len(candidates) > 1:
                note = 'AMBIGUOUS_PREFIX_MATCH'
            else:
                note = 'NO_EXPENDITURE_MATCH'
        matched_exp_keys.add((date, resp2, item_group, canonical))
        results.append({
            'report_date': date,
            'resp1_desc': resp1_by_resp2.get((date, resp2), ''),
            'resp2_desc': resp2,
            'item_group_desc': item_group,
            'item_desc': canonical,
            'commitment_ledger_total': round(total, 2),
            'expenditure_reported_commitments': None if reported is None else round(reported, 2),
            'variance': None if reported is None else round(total - reported, 2) or 0.0,
            'note': note,
        })

    # Items where the expenditure report shows outstanding commitments but
    # the ledger has no matching vendor/order detail at all.
    for (date, resp2, item_group), bucket in exp_index.items():
        for item_desc, commitments_value in bucket.items():
            if commitments_value == 0:
                continue
            key = (date, resp2, item_group, item_desc)
            if key in matched_exp_keys:
                continue
            results.append({
                'report_date': date,
                'resp1_desc': resp1_by_resp2.get((date, resp2), ''),
                'resp2_desc': resp2,
                'item_group_desc': item_group,
                'item_desc': item_desc,
                'commitment_ledger_total': 0.0,
                'expenditure_reported_commitments': round(commitments_value, 2),
                'variance': round(-commitments_value, 2),
                'note': 'NO_LEDGER_DETAIL',
            })

    results.sort(key=lambda r: (r['report_date'], r['resp1_desc'], r['resp2_desc'], r['item_desc']))
    return results


def build_responsibility_reconciliation(commitment_rows, expenditure_rows, resp2_map):
    """Roll the same reconciliation up to (report_date, resp2), adding
    expenditure context (expenses/budget/available budget) for that unit.

    Keyed on resp2 alone rather than (resp1, resp2) for the same reason as
    build_item_reconciliation: resp1_desc is blank for several departments
    in one source PDF due to corrupted header text there.
    """
    ledger = defaultdict(float)
    resp1_by_resp2 = {}
    for r in commitment_rows:
        resp2 = resp2_map.get((r['report_date'], r['resp2_desc']), r['resp2_desc'])
        key = (r['report_date'], resp2)
        ledger[key] += float(r['commitments_balance'])
        resp1_by_resp2.setdefault(key, r['resp1_desc'])

    reported = defaultdict(float)
    context = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in expenditure_rows:
        key = (r['report_date'], r['resp2_desc'])
        reported[key] += float(r['commitments'])
        context[key][0] += float(r['expenses'])
        context[key][1] += float(r['budget'])
        context[key][2] += float(r['available_budget'])
        if r['resp1_desc']:
            resp1_by_resp2.setdefault(key, r['resp1_desc'])

    results = []
    for key in sorted(set(ledger) | set(reported)):
        date, resp2 = key
        l_total = ledger.get(key, 0.0)
        r_total = reported.get(key, 0.0)
        expenses, budget, available = context.get(key, [0.0, 0.0, 0.0])
        results.append({
            'report_date': date,
            'resp1_desc': resp1_by_resp2.get(key, ''),
            'resp2_desc': resp2,
            'commitment_ledger_total': round(l_total, 2),
            'expenditure_reported_commitments': round(r_total, 2),
            'variance': round(l_total - r_total, 2) or 0.0,
            'expenses': round(expenses, 2),
            'budget': round(budget, 2),
            'available_budget': round(available, 2),
        })
    return results


def build_vendor_weekly_trend(commitment_rows):
    """Per vendor/item, the commitments_balance across weeks plus the
    change from the prior week (aging/pay-down trend)."""
    agg = defaultdict(float)
    for r in commitment_rows:
        if not r['vendor']:
            continue
        key = (r['vendor'], r['resp2_desc'], r['item_desc'], r['report_date'])
        agg[key] += float(r['commitments_balance'])

    series = defaultdict(dict)
    for (vendor, resp2, item, date), val in agg.items():
        series[(vendor, resp2, item)][date] = val

    results = []
    for (vendor, resp2, item), by_date in series.items():
        prev = None
        for date in sorted(by_date):
            val = by_date[date]
            results.append({
                'vendor': vendor,
                'resp2_desc': resp2,
                'item_desc': item,
                'report_date': date,
                'commitments_balance': round(val, 2),
                'change_from_prior_week': None if prev is None else round(val - prev, 2),
            })
            prev = val

    results.sort(key=lambda r: (r['vendor'], r['resp2_desc'], r['item_desc'], r['report_date']))
    return results
