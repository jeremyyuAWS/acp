"""Recorded scan activity. Unknown metadata is never backfilled with invented history."""
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException

SUCCESS = {'done', 'completed'}
UNSUCCESSFUL = {'failed', 'error', 'cancelled', 'interrupted', 'superseded'}


def timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def interval(period, start, end, timezone_name, now):
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, 'Unknown reporting timezone')
    if period == 'custom':
        lower, upper = timestamp(start), timestamp(end)
        if lower is None or upper is None or lower >= upper:
            raise HTTPException(422, 'Custom dates require start before exclusive end')
    elif period == 'today':
        lower = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        upper = now
    elif period == 'all':
        lower, upper = None, now
    else:
        lower, upper = now - timedelta(days=int(period[:-1])), now
    return lower, upper, zone


def within(value, lower, upper):
    value = timestamp(value)
    return value is not None and (lower is None or value >= lower) and value < upper


def filtered(rows, source=None, owner=None, status=None, search=None):
    return [r for r in rows if (not source or (r.get('source') or 'unknown') == source)
            and (not owner or (r.get('owner_email') or 'unknown') == owner)
            and (not status or (status == '__successful__' and r.get('status') in SUCCESS)
                 or (status == '__unsuccessful__' and r.get('status') in UNSUCCESSFUL)
                 or (r.get('status') or 'unknown') == status)
            and (not search or search.lower() in ' '.join(str(r.get(k) or '') for k in ('id', 'source', 'owner_email', 'status')).lower())]


def valid_count(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def valid_score(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def summaries(rows):
    return {'attempts': len(rows), 'successful_runs': sum(r.get('status') in SUCCESS for r in rows),
            'unsuccessful_runs': sum(r.get('status') in UNSUCCESSFUL for r in rows)}


def build(rows, *, period='30d', source=None, owner=None, status=None, search=None,
          start=None, end=None, timezone_name='UTC', page=1, page_size=20, now=None):
    rows = [dict(row) for row in rows]
    for row in rows:
        for key in ('files', 'certifiable', 'uncertain', 'error'):
            if not valid_count(row.get(key)):
                row[key] = None
        if not valid_score(row.get('avg_score')):
            row['avg_score'] = None
    now = now or datetime.now(timezone.utc)
    lower, upper, zone = interval(period, start, end, timezone_name, now)
    population = filtered(rows, source, owner, status, search)
    attempts = [r for r in population if within(r.get('started_at'), lower, upper)
                or (period == 'all' and timestamp(r.get('started_at')) is None)]
    attempts.sort(key=lambda r: (timestamp(r.get('started_at')) or datetime.min.replace(tzinfo=timezone.utc), str(r.get('id'))), reverse=True)
    by_status, users, days = {}, {}, {}
    for row in attempts:
        state, actor = row.get('status') or 'unknown', row.get('owner_email') or 'unknown'
        by_status[state] = by_status.get(state, 0) + 1
        user = users.setdefault(actor, {'owner_email': actor, 'attempts': 0, 'successful_runs': 0, 'unsuccessful_runs': 0, 'last_activity': None})
        user['attempts'] += 1
        user['successful_runs'] += state in SUCCESS
        user['unsuccessful_runs'] += state in UNSUCCESSFUL
        if user['last_activity'] is None:
            user['last_activity'] = row.get('started_at')
        if timestamp(row.get('started_at')) is None:
            continue
        day = timestamp(row['started_at']).astimezone(zone).date().isoformat()
        bucket = days.setdefault(day, {'date': day, 'attempts': 0, 'statuses': {}})
        bucket['attempts'] += 1
        bucket['statuses'][state] = bucket['statuses'].get(state, 0) + 1
    results = [r for r in population if within(r.get('completed_at'), lower, upper) and r.get('status') in SUCCESS]
    valid = [r for r in results if valid_count(r.get('files')) and valid_count(r.get('certifiable')) and r['certifiable'] <= r['files']]
    docs, cert = sum(r['files'] for r in valid), sum(r['certifiable'] for r in valid)
    prior = None
    if lower is not None:
        prior_start = lower - (upper - lower)
        prior_rows = [r for r in population if within(r.get('started_at'), prior_start, lower)]
        prior_valid = [r for r in population if within(r.get('completed_at'), prior_start, lower) and r.get('status') in SUCCESS and valid_count(r.get('files')) and valid_count(r.get('certifiable')) and r['certifiable'] <= r['files']]
        prior_docs = sum(r['files'] for r in prior_valid)
        prior_rate = round(sum(r['certifiable'] for r in prior_valid) / prior_docs * 100, 1) if prior_docs else None
        rate = round(cert / docs * 100, 1) if docs else None
        prior = dict(summaries(prior_rows), start=prior_start.isoformat(), end=lower.isoformat(), certifiable_rate=prior_rate,
                     attempts_change=len(attempts)-len(prior_rows), rate_change_pp=round(rate-prior_rate, 1) if rate is not None and prior_rate is not None else None)
    known_dates = [timestamp(r.get(k)) for r in rows for k in ('started_at', 'completed_at')]
    latest = max((d for d in known_dates if d is not None), default=None)
    reporting = {'metric_version': 'scan-analytics-v1', 'generated_at': now.isoformat(), 'data_through': latest.isoformat() if latest else None,
                 'scope': 'Platform · all users', 'time_basis': 'Attempts: started_at; assessment compatibility metrics: completed_at',
                 'timezone': timezone_name, 'start': lower.isoformat() if lower else None, 'end': upper.isoformat(),
                 'filters': {'source': source, 'owner': owner, 'status': status, 'search': search},
                 'review_scope': 'Current platform-wide pending queue snapshot; date, user, source and status filters do not apply',
                 'limitations': ['Platform administrators can report across owner-email tenants; no organization boundary is recorded.',
                                'Document totals are scan observations, not deduplicated files. Certifiable rate uses recorded file counts and is not verified conformance.',
                                'Mean scan score equally weights recorded scan averages.',
                                'Department, source connection, exception reasons and historical stage/rubric changes are unavailable in this register.',
                                'All-time reporting covers retained records only; retention boundary is not recorded.'],
                 'undated_activity': sum(timestamp(r.get('started_at')) is None for r in attempts),
                 'missing_started_at': sum(timestamp(r.get('started_at')) is None for r in population),
                 'snapshot_note': 'Overview, CSV and methodology are generated independently; records may change between requests. Compare generated-at timestamps.',
                 'data_through_note': 'Latest recorded run start/end, not ingestion freshness',
                 'certifiable_denominator': 'Recorded file counts from successful completed runs; valid eligibility denominator is not separately recorded',
                 'partial_data': any(timestamp(r.get('started_at')) is None for r in population)}
    scores = [r['avg_score'] for r in results if valid_score(r.get('avg_score'))]
    result_summary = {'scans': len(results), 'docs': docs, 'certifiable': cert,
                      'certifiable_rate': round(cert / docs * 100, 1) if docs else None,
                      'error_docs': sum(r['error'] for r in results if valid_count(r.get('error'))),
                      'uncertain': sum(r['uncertain'] for r in results if valid_count(r.get('uncertain'))),
                      'missing_results': len(results)-len(valid),
                      'avg_score': round(sum(scores)/len(scores), 1) if scores else None}
    activity_sources, result_sources = {}, {}
    for row in attempts:
        source_key = row.get('source') or 'unknown'
        group = activity_sources.setdefault(source_key, {'attempts': 0, 'successful_runs': 0, 'unsuccessful_runs': 0})
        group['attempts'] += 1
        group['successful_runs'] += row.get('status') in SUCCESS
        group['unsuccessful_runs'] += row.get('status') in UNSUCCESSFUL
    for row in results:
        group = result_sources.setdefault(row.get('source') or 'unknown', {'scans': 0, 'docs': 0, 'certifiable': 0, 'missing_results': 0})
        group['scans'] += 1
        if not valid_count(row.get('files')) or not valid_count(row.get('certifiable')) or row['certifiable'] > row['files']:
            group['missing_results'] += 1
        else:
            group['docs'] += row['files']
            group['certifiable'] += row['certifiable']
    for group in result_sources.values():
        group['certifiable_rate'] = round(group['certifiable']/group['docs']*100, 1) if group['docs'] else None
    result_rows = sorted(results, key=lambda r: timestamp(r['completed_at']), reverse=True)
    result_series = [{k: r.get(k) for k in ('id', 'completed_at', 'files', 'certifiable', 'avg_score')}
                     for r in reversed(result_rows)]
    for row in result_series:
        row['certifiable_rate'] = round(row['certifiable']/row['files']*100, 1) if valid_count(row.get('files')) and row['files'] > 0 and valid_count(row.get('certifiable')) and row['certifiable'] <= row['files'] else None
        if not valid_score(row.get('avg_score')):
            row['avg_score'] = None
    return dict(summaries(attempts), successful_results=result_summary, result_trend=result_series,
                results_register={'rows': result_rows[(page-1)*page_size:page*page_size], 'total': len(result_rows),
                                  'page': page, 'page_size': page_size, 'pages': (len(result_rows)+page_size-1)//page_size, 'time_basis': 'completed_at'}, active_users=len([u for u in users if u != 'unknown']), by_status=by_status,
                by_user=list(users.values()), activity_by_source=activity_sources, results_by_source=result_sources, activity=[days[k] for k in sorted(days)], reporting=reporting,
                filter_options={'owners': sorted({r.get('owner_email') or 'unknown' for r in rows}),
                                'sources': sorted({r.get('source') or 'unknown' for r in rows}),
                                'statuses': ['__successful__', '__unsuccessful__'] + sorted({r.get('status') or 'unknown' for r in rows})},
                register={'rows': attempts[(page-1)*page_size:page*page_size], 'total': len(attempts), 'page': page,
                          'page_size': page_size, 'pages': (len(attempts)+page_size-1)//page_size}, comparison=prior)
