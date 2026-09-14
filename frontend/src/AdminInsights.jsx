import { useEffect, useState, useRef } from 'react'
import { getAdminAnalytics, getAdminAnalyticsScan, downloadAdminAnalyticsExport, downloadAdminAnalyticsMethodology, getScanInventory } from './api.js'
import './operations-typography.css'
import './scan-analytics.css'
import BalancedSummary, { ScanActivityCalendar } from './BalancedSummary.jsx'
import { loadDiscoveryInventory } from './discoveryInventory.js'

const PERIODS = [['today', 'Today'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['90d', 'Last 90 days'], ['all', 'All time'], ['custom', 'Custom dates']]
const SOURCES = { drive: 'Google Drive', sharepoint: 'SharePoint', local: 'Local', unknown: 'Unknown' }
const number = (v, places = 0) => v == null ? '—' : typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: places }) : String(v)
const statusName = s => ({ __successful__: 'All successful outcomes', __unsuccessful__: 'All unsuccessful outcomes', done: 'Successful', failed: 'Failed', cancelled: 'Cancelled', interrupted: 'Interrupted', superseded: 'Superseded', running: 'Running' }[s] || s || 'Unknown')
const date = s => s ? String(s).replace('T', ' ').replace(/\.\d+Z$/, ' UTC') : 'Not recorded'
const entries = object => Object.entries(object || {})

// Deliberately retained and unmounted: review overlaps assessment populations, so the former
// sequential lifecycle visual is retired. Keep its implementation for a reversible redesign.
function RetainedLifecycleFunnel({ data }) {
  const totalDocs = data?.docs ?? 0
  if (!totalDocs) return null
  const stages = [
    ['Scanned', totalDocs], ['Assessed', totalDocs - (data.error_docs ?? 0)],
    ['Certifiable', data.certifiable ?? 0],
    ...((data.review_pending ?? 0) > 0 ? [['In review', data.review_pending]] : []),
  ]
  return <section className="panel"><h2>Estate lifecycle</h2><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>{stages.map(([label, count]) => <div key={label} style={{ flex: 1 }}><div className="ops-kpi__meta">{label}</div><div className="ops-kpi__value ops-kpi__value--compact">{number(count)}</div><div style={{ height: 6, background: 'var(--line)', borderRadius: 3 }}><div style={{ height: '100%', width: `${Math.max(count / totalDocs * 100, 0)}%`, background: 'var(--ink)', borderRadius: 3 }} /></div></div>)}</div></section>
}

function ChartTable({ caption, headings, children }) {
  return <details className="sa-data"><summary>View data table: {caption}</summary><div className="sa-scroll"><table><caption>{caption}</caption><thead><tr>{headings.map(h => <th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div></details>
}
function Panel({ title, subtitle, children, wide = false }) {
  return <section className={`panel sa-panel ${wide ? 'sa-wide' : ''}`}><h2>{title}</h2><p className="sa-muted">{subtitle}</p>{children}</section>
}
function RankChart({ rows, onSelect, label = 'Scan attempts' }) {
  const max = Math.max(1, ...rows.map(r => r.count || 0))
  return rows.length ? <div className="sa-ranks" aria-label={`${label} by category`}>{rows.map(r => <button key={r.key} className="sa-rank" onClick={() => onSelect(r.key)} aria-label={`${r.label}: ${number(r.count)} ${label.toLowerCase()}. Show matching scans`}><span>{r.label}</span><span className="sa-track" aria-hidden="true"><span style={{ width: `${(r.count || 0) / max * 100}%` }} /></span><strong>{number(r.count)}</strong></button>)}</div> : <p className="sa-empty">No matching records.</p>
}
function RateChart({ points, onSelect }) {
  const validTimes = points.map(p => Date.parse(p.at)).filter(Number.isFinite)
  const first = Math.min(...validTimes), last = Math.max(...validTimes)
  let open = false
  const path = points.map(p => {
    const time = Date.parse(p.at)
    if (p.certifiable_pct == null || !Number.isFinite(time)) { open = false; return '' }
    const x = 48 + (last > first ? (time - first) / (last - first) : .5) * 490
    const y = 160 - p.certifiable_pct * 1.3
    const d = `${open ? 'L' : 'M'}${x},${y}`; open = true; return d
  }).join(' ')
  return <><svg viewBox="0 0 580 195" role="img" aria-label="Certifiable rate by actual assessment completion time, fixed 0 to 100 percent scale. Missing rates are gaps.">
    {[0, 50, 100].map(v => <g key={v}><line x1="48" x2="538" y1={160 - v * 1.3} y2={160 - v * 1.3} stroke="var(--line)" /><text x="4" y={165 - v * 1.3}>{v}%</text></g>)}
    <path d={path} fill="none" stroke="#6e62a4" strokeWidth="3" />
    {points.map((p, i) => p.certifiable_pct != null && Number.isFinite(Date.parse(p.at)) ? <circle key={p.id || i} cx={48 + (last > first ? (Date.parse(p.at) - first) / (last - first) : .5) * 490} cy={160 - p.certifiable_pct * 1.3} r="4" fill="#6e62a4"><title>{p.at}: {number(p.certifiable_pct, 1)}%</title></circle> : null)}
    <text x="48" y="188">{points[0]?.at?.slice(0, 10) || 'No dated results'}</text><text x="538" y="188" textAnchor="end">{points.at(-1)?.at?.slice(0, 10)}</text>
  </svg><ChartTable caption="Assessment results over time" headings={['Completed at', 'Observations', 'Certifiable rate', 'Records']}>{points.map((p, i) => <tr key={p.id || i}><td>{date(p.at)}</td><td>{number(p.files ?? p.docs)}</td><td>{p.certifiable_pct == null ? 'Unavailable' : `${number(p.certifiable_pct, 1)}%`}</td><td>{p.id ? <button className="sa-link" onClick={() => onSelect(p.id)}>View scan {p.id}</button> : 'Run ID unavailable'}</td></tr>)}</ChartTable></>
}

export function AdminInsights({ me, run, files = [], cap, assessment, scanList = [], onPickScan }) {
  const [estateInventory, setEstateInventory] = useState(null)
  useEffect(() => {
    let live = true
    setEstateInventory(null)
    if (run?.id) loadDiscoveryInventory(run.id, getScanInventory).then(inventory => {
      if (live) setEstateInventory({ scanId: run.id, inventory })
    })
    return () => { live = false }
  }, [run?.id])
  const [filters, setFilters] = useState(() => {
    const q = new URLSearchParams(window.location.search)
    return { period: q.get('analytics_period') || '30d', source: q.get('analytics_source') || '', owner: q.get('analytics_owner') || '', status: q.get('analytics_status') || '', search: q.get('analytics_search') || '', start: q.get('analytics_start') || '', end: q.get('analytics_end') || '', timezone: 'UTC', page: 1, page_size: 20 }
  })
  const [dates, setDates] = useState({ start: filters.start.slice(0, 10), end: filters.end && Number.isFinite(Date.parse(filters.end)) ? new Date(Date.parse(filters.end) - 86400000).toISOString().slice(0,10) : '' })
  const [data, setData] = useState(null), [loading, setLoading] = useState(true), [error, setError] = useState(null)
  const [optionData, setOptionData] = useState({}), [registerBasis, setRegisterBasis] = useState('attempts')
  const [revision, setRevision] = useState(0), [detailId, setDetailId] = useState(null), [detail, setDetail] = useState(null), [detailEvidence, setDetailEvidence] = useState({}), [detailError, setDetailError] = useState(null)
  const [evidenceFilter, setEvidenceFilter] = useState(null)
  const [exporting, setExporting] = useState(false), [exportError, setExportError] = useState(null), [dateError, setDateError] = useState(null)
  const registerRef = useRef(null), pendingRegisterFocus = useRef(false)
  useEffect(() => {
    if (data && pendingRegisterFocus.current) {
      pendingRegisterFocus.current = false
      registerRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
      registerRef.current?.focus({ preventScroll: true })
    }
  }, [data])
  useEffect(() => {
    const controller = new AbortController()
    if (filters.period === 'custom' && (!filters.start || !filters.end)) { setLoading(false); return () => controller.abort() }
    setLoading(true); setError(null)
    getAdminAnalytics(filters.period, filters.source || null, { ...filters, signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) { setData(result); setOptionData(result.filter_options || {}); setLoading(false) } })
      .catch(e => { if (!controller.signal.aborted) { setError(e?.message || 'Analytics could not be loaded.'); setLoading(false) } })
    return () => controller.abort()
  }, [filters, revision])
  useEffect(() => {
    if (filters.start && filters.end && Number.isFinite(Date.parse(filters.end))) setDates({ start: filters.start.slice(0,10), end: new Date(Date.parse(filters.end) - 86400000).toISOString().slice(0,10) })
  }, [filters.start, filters.end])
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    for (const key of ['period', 'source', 'owner', 'status', 'search', 'start', 'end']) filters[key] ? q.set(`analytics_${key}`, filters[key]) : q.delete(`analytics_${key}`)
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${q.size ? `?${q}` : ''}${window.location.hash}`)
  }, [filters])
  useEffect(() => {
    if (!detailId) return
    const controller = new AbortController(); setDetail(null); setDetailError(null); setEvidenceFilter(null)
    getAdminAnalyticsScan(detailId, { signal: controller.signal }).then(d => { if (!controller.signal.aborted) { setDetail(d.scan); setDetailEvidence({ observations: d.observations || [], events: d.events || [], reporting: d.reporting || {} }) } }).catch(e => { if (!controller.signal.aborted) setDetailError(e.message) })
    return () => controller.abort()
  }, [detailId])
  const change = patch => { setData(null); setFilters(f => ({ ...f, ...patch, page: 1 })); setDetailId(null) }
  const select = (patch, basis = 'attempts') => { pendingRegisterFocus.current = true; setRegisterBasis(basis); change(patch) }
  const applyDates = e => {
    e.preventDefault()
    if (!dates.start || !dates.end || dates.end < dates.start) { setDateError('Choose an end date on or after the start date.'); return }
    const end = new Date(`${dates.end}T00:00:00Z`); end.setUTCDate(end.getUTCDate() + 1)
    setDateError(null); change({ period: 'custom', start: `${dates.start}T00:00:00Z`, end: end.toISOString() })
  }
  const doExport = async () => {
    setExporting(true); setExportError(null)
    try { await downloadAdminAnalyticsExport(filters.period, filters.source || null, { ...filters, basis: registerBasis }); await downloadAdminAnalyticsMethodology(filters.period, filters.source || null, { ...filters, basis: registerBasis }) }
    catch (e) { setExportError(e.message || 'Export failed.'); } finally { setExporting(false) }
  }
  const reporting = data?.reporting || {}, register = (registerBasis === 'results' ? data?.results_register : data?.register) || { rows: data?.recent_scans || [], total: data?.scans, page: 1, pages: 1 }
  const results = data?.successful_results || {}
  const options = optionData, users = data?.by_user || [], activity = data?.activity || [], points = data?.result_trend ? data.result_trend.map(p => ({ ...p, at: p.completed_at, certifiable_pct: p.certifiable_rate })) : data?.trend?.points || []
  const statuses = entries(data?.by_status), sources = entries(data?.results_by_source || data?.by_source)
  const comparison = data?.comparison
  const observationType = o => o.engine || o.format || o.extension || 'Unknown'
  const criterion = issue => typeof issue === 'string' ? 'Unclassified' : issue.wcag || issue.code || issue.criterion || issue.rule || 'Unclassified'
  const typeCounts = {}, criterionCounts = {}
  for (const observation of detailEvidence.observations || []) {
    const type = observationType(observation); typeCounts[type] = (typeCounts[type] || 0) + 1
    for (const issue of observation.issues || []) { const key = criterion(issue); criterionCounts[key] = (criterionCounts[key] || 0) + 1 }
  }
  const selectedObservations = (detailEvidence.observations || []).filter(o => !evidenceFilter || (evidenceFilter.type ? observationType(o) === evidenceFilter.type : (o.issues || []).some(issue => criterion(issue) === evidenceFilter.criterion)))
  return <div className="scan-analytics">
    <header className="sa-header"><div><h1>Scan Analytics</h1><p>Who scanned, what happened, and the records behind every number.</p></div><div className="sa-actions"><button className="chip" onClick={() => setRevision(r => r + 1)} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button><button className="chip" onClick={doExport} disabled={!data || loading || !!error || exporting}>{exporting ? 'Exporting…' : `Export all filtered ${registerBasis === 'results' ? 'results' : 'scans'} CSV`}</button></div></header>
    <section className="panel sa-context" aria-label="Reporting context"><strong>{reporting.scope || 'Platform administrator reporting · all recorded users'}</strong><div className="sa-context-grid"><span>Timezone: {reporting.timezone || 'UTC'}</span><span>Refreshed: {date(reporting.generated_at)}</span><span>Data through: {date(reporting.data_through)}</span><span>Interval: {reporting.start ? `${date(reporting.start)} to ${date(reporting.end)} (end exclusive)` : 'All retained history'}</span></div><p>Attempts use scan start time. Document results use recorded completion time. All users means platform-wide authorized administrator access; this is not an organization coverage report.</p></section>
    <section className="panel sa-filters" aria-label="Analytics filters">
      <label>Reporting period<select value={filters.period} onChange={e => { if (e.target.value === 'custom') change({ period: 'custom' }); else change({ period: e.target.value, start: '', end: '' }) }}>{PERIODS.map(([v,l]) => <option value={v} key={v}>{l}</option>)}</select></label>
      <label>User<select value={filters.owner} onChange={e => change({ owner: e.target.value })}><option value="">All users</option>{(options.owners || []).map(u => <option key={u} value={u}>{u || 'Unknown actor'}</option>)}</select></label>
      <label>Source<select value={filters.source} onChange={e => change({ source: e.target.value })}><option value="">All sources</option>{(options.sources || []).map(s => <option key={s} value={s}>{SOURCES[s] || s}</option>)}</select></label>
      <label>Status<select value={filters.status} onChange={e => change({ status: e.target.value })}><option value="">All statuses</option>{[...new Set([...(options.statuses || []), ...(filters.status ? [filters.status] : [])])].map(s => <option key={s} value={s}>{statusName(s)}</option>)}</select></label>
      <label className="sa-search">Search scans<input type="search" value={filters.search} placeholder="Run ID, user or source" onChange={e => change({ search: e.target.value })} /></label>
      <button className="sa-link" onClick={() => change({ period: '30d', owner: '', source: '', status: '', search: '', start: '', end: '' })}>Clear filters</button>
      {filters.period === 'custom' && <form className="sa-custom" onSubmit={applyDates}><label>Start date<input type="date" value={dates.start} onChange={e => setDates(d => ({ ...d, start: e.target.value }))} required /></label><label>End date<input type="date" value={dates.end} onChange={e => setDates(d => ({ ...d, end: e.target.value }))} required /></label><button className="chip" type="submit">Apply dates</button><span>Includes both dates, in UTC.</span></form>}
      {dateError && <p role="alert">{dateError}</p>}
    </section>
    <div aria-live="polite">{loading && <p className="sa-notice">{data ? 'Updating reporting. The previous snapshot remains visible until loading completes.' : 'Loading scan analytics…'}</p>}{error && <p role="alert" className="sa-notice sa-error">{error}{data && ' Showing a stale previous snapshot; it may not match the selected filters.'}</p>}{exportError && <p role="alert" className="sa-error">{exportError}</p>}</div>
    {data && <div aria-busy={loading} className={loading || error ? 'sa-retained' : ''}>
      {reporting.partial_data && <p className="sa-notice" role="status">{number(reporting.missing_started_at)} retained runs have no valid start timestamp. All-time reporting keeps them inspectable; dated activity excludes them.</p>}
      {results.missing_results > 0 && <p className="sa-notice" role="status">{number(results.missing_results)} successful completions have unavailable or inconsistent result counters and are excluded from observation and rate totals.</p>}
      {onPickScan && scanList.length > 0 && <label className="balanced-scan-choice">Estate chart scan
        <select value={run?.id || ''} onChange={event => onPickScan(event.target.value)}>
          {!run?.id && <option value="">Select a scan</option>}
          {scanList.map(scan => <option key={scan.id} value={scan.id}>{scan.id}{scan.completed_at ? ` · ${scan.completed_at}` : ''}</option>)}
        </select>
      </label>}
      <BalancedSummary run={run} files={files} cap={cap} assessment={assessment}
        inventory={estateInventory && estateInventory.scanId === run?.id ? estateInventory.inventory : null}
        calendar={<ScanActivityCalendar activity={activity} disabled={loading || !!error} stale={!!error}
          onDay={day => select({ period: 'custom', start: `${day.date}T00:00:00Z`, end: new Date(Date.parse(`${day.date}T00:00:00Z`) + 86400000).toISOString() })} />} />
      <details className="balanced-legacy"><summary>Additional scan reporting</summary>
      <div className="ops-kpi-grid ops-kpi-grid--analytics sa-kpis">{[
        ['Scan attempts', data.attempts ?? data.scans, 'Distinct started runs; all recorded statuses', {}],
        ['Successful runs', data.successful_runs, 'Recorded successful terminal outcome', { status: '__successful__' }],
        ['Unsuccessful runs', data.unsuccessful_runs, 'Failed, error, cancelled, interrupted or superseded attempts', { status: '__unsuccessful__' }],
        ['Active scanning users', data.active_users, 'Distinct initiating actors; unknown kept separate', {}],
        ['Assessment observations', results.docs, 'Successful completions; rescans count again', {}, 'results'],
        ['Certifiable rate', results.certifiable_rate == null ? '—' : `${number(results.certifiable_rate, 1)}%`, `${number(results.certifiable)} certifiable / ${number(results.docs)} recorded observations`, {}, 'results'],
      ].map(([label,value,sub,patch,basis]) => <button key={label} className="panel ops-kpi sa-kpi" onClick={() => select(patch,basis)} disabled={loading || !!error}><div className="ops-kpi__value">{number(value)}</div><div className="ops-kpi__label">{label}</div><div className="ops-kpi__meta">{sub}</div><span className="sa-kpi-link">Explore scans →</span></button>)}</div>
      {comparison && <section className="panel sa-comparison"><h2>Previous equal-length period</h2><p>{date(comparison.start)} to {date(comparison.end)} · identical filters</p><div><strong>{number(comparison.attempts)} attempts</strong><span>Attempt change: {comparison.attempts_change == null ? 'No comparable baseline' : `${comparison.attempts_change > 0 ? '+' : ''}${number(comparison.attempts_change)} runs`}</span><span>Certifiable rate: {comparison.certifiable_rate == null ? 'Unavailable' : `${number(comparison.certifiable_rate,1)}%`}</span><span>Rate change: {comparison.rate_change_pp == null ? 'Unavailable' : `${number(comparison.rate_change_pp,1)} percentage points`}</span></div><small>Different scan populations may explain the change; period comparison does not establish remediation impact.</small></section>}
      <div className="sa-chart-grid">
        <Panel title="Scan activity" subtitle="Attempts by UTC start date and recorded status. Running scans are current states, not terminal outcomes." wide>
          <div className="sa-activity" aria-label="Daily scan attempts">{activity.map(day => <div className="sa-day" key={day.date}><button className="sa-link" onClick={() => select({ period: 'custom', start: `${day.date}T00:00:00Z`, end: new Date(Date.parse(`${day.date}T00:00:00Z`) + 86400000).toISOString() })}>{day.date}</button><div className="sa-stack" style={{width: `${day.attempts / Math.max(1,...activity.map(d => d.attempts)) * 100}%`}}>{entries(day.statuses).map(([status,count]) => <button key={status} className={`sa-segment sa-status-${status}`} style={{ flexGrow: count }} title={`${statusName(status)}: ${count}`} aria-label={`${day.date}, ${statusName(status)}, ${count} attempts. Show scans`} onClick={() => select({ status, period: 'custom', start: `${day.date}T00:00:00Z`, end: new Date(Date.parse(`${day.date}T00:00:00Z`) + 86400000).toISOString() })}>{statusName(status)} {count}</button>)}</div><strong>{number(day.attempts)}</strong></div>)}</div>
          {!activity.length && <p className="sa-empty">No dated attempts in this interval.</p>}
          <ChartTable caption="Daily scan activity" headings={['UTC date', 'Status', 'Attempts', 'Records']}>{activity.flatMap(day => entries(day.statuses).map(([status,count]) => <tr key={`${day.date}-${status}`}><td>{day.date}</td><td>{statusName(status)}</td><td>{number(count)}</td><td><button className="sa-link" onClick={() => select({ status, period:'custom', start:`${day.date}T00:00:00Z`, end:new Date(Date.parse(`${day.date}T00:00:00Z`)+86400000).toISOString() })}>Show matching scans</button></td></tr>))}</ChartTable>
        </Panel>
        <Panel title="Assessment results over time" subtitle="Certifiable / recorded file observations per successful completion, on a fixed 0–100% scale. Missing results are unavailable, never zero."><RateChart points={points} onSelect={setDetailId} /></Panel>
        <Panel title="Recorded scan outcomes" subtitle="All attempt statuses participate in totals; unknown statuses remain visible."><RankChart rows={statuses.map(([key,count]) => ({key,label:statusName(key),count}))} onSelect={status => select({status})} /><ChartTable caption="Scan outcomes" headings={['Status','Attempts']}>{statuses.map(([s,c]) => <tr key={s}><td><button className="sa-link" onClick={() => select({status:s})}>{statusName(s)}</button></td><td>{number(c)}</td></tr>)}</ChartTable></Panel>
        <Panel title="Results by source" subtitle="Completion-time observations. Select a source to inspect its attempts and recorded results."><RankChart rows={sources.map(([key,r]) => ({key,label:SOURCES[key] || key,count:r.docs}))} label="Document observations" onSelect={source => select({source}, 'results')} /><ChartTable caption="Source results" headings={['Source','Observations','Certifiable','Rate']}>{sources.map(([s,r]) => <tr key={s}><td><button className="sa-link" onClick={() => select({source:s}, 'results')}>{SOURCES[s] || s}</button></td><td>{number(r.docs)}</td><td>{number(r.certifiable)}</td><td>{r.certifiable_rate == null ? 'Unavailable' : `${number(r.certifiable_rate,1)}%`}</td></tr>)}</ChartTable></Panel>
        <Panel title="Attempts by source" subtitle="Start-time activity across all statuses. Select a source to inspect contributing scan attempts."><RankChart rows={entries(data.activity_by_source).map(([key,r]) => ({key,label:SOURCES[key] || key,count:r.attempts}))} onSelect={source => select({source})} /><ChartTable caption="Source scan activity" headings={['Source','Attempts','Successful','Unsuccessful']}>{entries(data.activity_by_source).map(([source,r]) => <tr key={source}><td><button className="sa-link" onClick={() => select({source})}>{SOURCES[source] || source}</button></td><td>{number(r.attempts)}</td><td>{number(r.successful_runs)}</td><td>{number(r.unsuccessful_runs)}</td></tr>)}</ChartTable></Panel>
        <Panel title="User activity" subtitle="Initiators are not necessarily document owners or remediation assignees."><RankChart rows={users.map(u => ({key:u.owner_email || 'unknown',label:u.owner_email || 'Unknown actor',count:u.attempts}))} onSelect={owner => select({owner})} /><ChartTable caption="User activity" headings={['Initiating actor','Attempts','Successful','Unsuccessful','Last activity']}>{users.map(u => <tr key={u.owner_email || 'unknown'}><td><button className="sa-link" onClick={() => select({owner:u.owner_email || 'unknown'})}>{u.owner_email || 'Unknown actor'}</button></td><td>{number(u.attempts)}</td><td>{number(u.successful_runs)}</td><td>{number(u.unsuccessful_runs)}</td><td>{date(u.last_activity)}</td></tr>)}</ChartTable></Panel>
      </div>
      </details>
      <section className="panel sa-panel" ref={registerRef} tabIndex="-1"><h2>Scan register</h2><p className="sa-muted">Reporting snapshot generated {date(reporting.generated_at)}. Export uses a fresh server snapshot and records its own generation time.</p><div className="sa-actions"><button className="sa-link" onClick={() => { setRegisterBasis('attempts'); setFilters(f => ({...f,page:1})) }}>Attempt activity</button><button className="sa-link" onClick={() => { setRegisterBasis('results'); setFilters(f => ({...f,page:1})) }}>Assessment completions</button></div><p className="sa-muted">{number(register.total)} matching {registerBasis === 'results' ? 'successful completion results' : 'attempts'} · page {register.page || 1} of {register.pages || 1}. Select a run for recorded evidence.</p><div className="sa-scroll"><table><caption>{registerBasis === 'results' ? 'Successful assessment completions in the interval' : 'All filtered scan attempts'}</caption><thead><tr>{['Run ID','Initiating actor','Source','Started','Completed','Status','Observations','Certifiable','Mean scan score'].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{register.rows.map(s => <tr key={s.id}><td><button className="sa-link" onClick={() => setDetailId(s.id)}>{s.id}</button></td><td>{s.owner_email || 'Unknown actor'}</td><td>{SOURCES[s.source] || s.source || 'Unknown'}</td><td>{date(s.created_at || s.started_at)}</td><td>{date(s.completed_at)}</td><td><span className={`sa-status sa-status-${s.status}`}>{statusName(s.status)}</span></td><td>{number(s.files)}</td><td>{number(s.certifiable)}{s.status === 'done' && s.files > 0 && s.certifiable != null ? ` (${number(s.certifiable / s.files * 100, 1)}%)` : ''}</td><td>{number(s.avg_score,1)}</td></tr>)}</tbody></table></div>{!register.rows.length && <p className="sa-empty">No matching records for this time basis. Clear filters or choose a wider interval.</p>}<div className="sa-pagination"><button className="chip" disabled={loading || (register.page || 1) <= 1} onClick={() => setFilters(f => ({...f,page:f.page-1}))}>Previous page</button><span>Page {register.page || 1} of {register.pages || 1}</span><button className="chip" disabled={loading || (register.page || 1) >= (register.pages || 1)} onClick={() => setFilters(f => ({...f,page:f.page+1}))}>Next page</button></div></section>
      {detailId && <section className="panel sa-panel sa-detail" aria-label="Scan detail"><div className="sa-header"><h2>Scan detail · {detailId}</h2><button className="chip" onClick={() => setDetailId(null)}>Close detail</button></div>{detailError ? <p role="alert">{detailError}</p> : !detail ? <p role="status">Loading scan evidence…</p> : <><dl className="sa-detail-grid">{[['Initiating actor',detail.owner_email || 'Unknown actor'],['Source',SOURCES[detail.source] || detail.source || 'Unknown'],['Status',statusName(detail.status)],['Started',date(detail.created_at || detail.started_at)],['Completed',date(detail.completed_at)],['Document observations',number(detail.files)],['Certifiable',number(detail.certifiable)],['Mean scan score',number(detail.avg_score,1)]].map(([k,v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>{detail.error && <p className="sa-error">Recorded error: {typeof detail.error === 'string' ? detail.error : JSON.stringify(detail.error)}</p>}<p>Only recorded evidence is shown. Historical departments and rubric versions may be unavailable.</p>
        <h3>Recorded stage events</h3><p>{detailEvidence.reporting?.events_note}</p>{detailEvidence.events?.length ? <ol>{detailEvidence.events.map((event,i) => <li key={event.id || i}>{date(event.timestamp || event.created_at || event.at)} · {event.stage || event.event_type || event.type || 'Recorded event'} · {event.message || event.status || ''}</li>)}</ol> : <p>No stage history recorded for this run.</p>}
        <div className="sa-chart-grid"><Panel title="Recorded document types" subtitle="Counts within this scan's available document evidence."><RankChart label="Observations" rows={entries(typeCounts).map(([key,count]) => ({key,label:key,count}))} onSelect={type => setEvidenceFilter({type})} /><ChartTable caption="Scan document types" headings={['Recorded type','Observations']}>{entries(typeCounts).map(([type,count]) => <tr key={type}><td>{type}</td><td>{count}</td></tr>)}</ChartTable></Panel><Panel title="Recorded finding criteria" subtitle="Issue instances, not distinct open findings; unclassified issues stay visible."><RankChart label="Issue instances" rows={entries(criterionCounts).map(([key,count]) => ({key,label:key,count}))} onSelect={criterion => setEvidenceFilter({criterion})} /><ChartTable caption="Scan finding criteria" headings={['Recorded criterion','Issue instances']}>{entries(criterionCounts).map(([key,count]) => <tr key={key}><td>{key}</td><td>{count}</td></tr>)}</ChartTable></Panel></div>
        <h3>Document observations & findings</h3>{evidenceFilter && <p>Selected evidence: {evidenceFilter.type || evidenceFilter.criterion} · <button className="sa-link" onClick={() => setEvidenceFilter(null)}>Show all observations</button></p>}{selectedObservations.length ? <div className="sa-observations">{selectedObservations.map((observation,i) => <details key={observation.id || observation.name || i}><summary>{observation.name || observation.file || observation.filename || `Observation ${i+1}`} · {observation.engine || 'Unknown type'} · {observation.status || 'Outcome unavailable'} · score {number(observation.score,1)}</summary><p>Eligibility: {observation.certifiable == null ? 'Unavailable' : observation.certifiable ? 'Certifiable' : 'Not certifiable'}</p>{observation.issues?.length ? <ul>{observation.issues.map((issue,j) => <li key={j}>{typeof issue === 'string' ? issue : `${issue.wcag || issue.code || issue.rule || 'Finding'}: ${issue.message || issue.description || issue.name || JSON.stringify(issue)}`}</li>)}</ul> : <p>No finding list recorded; this alone does not establish conformance.</p>}</details>)}</div> : <p>No document evidence available for this run.</p>}</>}</section>}
      <section className="panel sa-panel sa-methodology"><h2>Definitions & data limitations</h2><p>Document observations count again on each scan. They are not unique files or estate coverage. Automated certifiability is eligibility, not verified WCAG conformance. Mean scan scores equally weight recorded scan averages.</p><p>{reporting.certifiable_denominator}</p><p>{reporting.data_through_note}</p><p>{reporting.snapshot_note}</p><p>Missing values appear as — or Unavailable. Failed or incomplete runs must not imply successful assessments with zero findings.</p>{reporting.review_scope && <p>Review queue: {reporting.review_scope}{data.review_pending != null && ` · ${number(data.review_pending)} pending now`}.</p>}{reporting.undated_activity > 0 && <p>{number(reporting.undated_activity)} undated attempts remain in all-time totals but cannot be placed on the activity chart.</p>}{(reporting.limitations || []).map((l,i) => <p key={i}>{typeof l === 'string' ? l : JSON.stringify(l)}</p>)}<p>Export downloads all filtered authorized rows and a companion methodology file. Department, finding age and verification charts require recorded historical evidence before they can be reported.</p></section>
    </div>}
  </div>
}
