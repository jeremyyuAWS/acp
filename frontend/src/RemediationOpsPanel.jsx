import { useEffect, useRef, useState } from 'react'
import LiveCounter from './LiveCounter.jsx'
import { counterRows, secondaryRows, freshness, headline, partitionSums } from './remediationSnapshot.js'
import { activityBuckets, attemptStage, milestoneCrossings, retrySeconds } from './remediationLivePanel.js'
import './remediation-ops-panel.css'
import './remediation-live-detail.css'

const PHASE_TEXT = { pending: 'Pending', active: 'In progress', completed: 'Completed', completed_with_exceptions: 'Completed with exceptions', failed: 'Failed', skipped: 'Skipped' }
const POSITIVE = new Set(['fixesApplied', 'fixesVerified', 'documentsVerified', 'delivered'])
function ago(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  return minutes < 60 ? `${minutes}m ${Math.round(seconds % 60)}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function FreshnessBadge({ state, updateMode }) {
  const polling = updateMode === 'polling' && state.level === 'reconnecting'
  const label = polling ? 'Updating by polling' : state.label
  return <span className={`remops-fresh remops-fresh-${polling ? 'polling' : state.level}`} role="status" title={state.detail}>
    <span aria-hidden="true">{state.level === 'stalled' ? '■' : polling ? '↻' : state.level === 'live' ? '●' : '◐'}</span>
    {label}{state.ageS !== null && state.level !== 'live' ? ` · last update ${state.ageS}s ago` : ''}
  </span>
}

function Progress({ snapshot, suspect }) {
  const rows = counterRows(snapshot)
  if (!rows) return null
  const total = snapshot.total_documents
  const completed = rows.find((r) => r.key === 'completed')?.value
  const known = typeof total === 'number' && total > 0 && rows.every((r) => typeof r.value === 'number')
  return <section className="remops-progress" aria-labelledby="remops-progress-title">
    <div className="remops-progress-head"><strong id="remops-progress-title">{completed == null || total == null ? 'Document progress unavailable' : `${completed.toLocaleString()} of ${total.toLocaleString()} documents complete`}</strong><span className="muted">{snapshot.estimate?.available ? `Estimated ${snapshot.estimate.label || 'range available'}` : 'Estimating after the first results'}</span></div>
    {known && <div className="remops-segments" aria-label={`${total} documents: ${rows.map((r) => `${r.value} ${r.label.toLowerCase()}`).join(', ')}`}>{rows.filter((r) => r.value > 0).map((row) => <span key={row.key} tabIndex="0" role="img" aria-label={`${row.label}: ${row.value}`} className={`remops-segment remops-segment-${row.key}`} style={{ width: `${row.value / total * 100}%` }} data-detail={`${row.label}: ${row.value.toLocaleString()}`} />)}</div>}
    <dl className={`remops-counts${suspect ? ' remops-suspect' : ''}`}>{rows.map((row) => <div key={row.key} title={row.definition}><dt>{row.label}</dt><dd data-testid={`rem-count-${row.key}`}>{row.value == null ? '—' : row.key === 'completed' ? <LiveCounter value={row.value} /> : row.value.toLocaleString()}</dd></div>)}</dl>
    {partitionSums(snapshot) === false && <p className="remops-error">These counters do not add up to the documents in scope. ACP is reconciling them.</p>}
  </section>
}

function Pipeline({ phases = [], attempts = [], moving = false }) {
  if (!phases.length) return null
  return <section className={`remops-pipeline${moving ? ' remops-pipeline-moving' : ''}`}><h3>Active document pipeline</h3><ol aria-label="Remediation phases">{phases.map((phase, index) => { const documents = attempts.filter((attempt) => attemptStage(attempt.phase) === phase.key).slice(0, 2); return <li key={phase.key} className={`remops-phase remops-phase-${phase.status}`}><span className="remops-phase-mark" aria-hidden="true">{phase.status === 'active' ? '●' : phase.status === 'failed' ? '×' : phase.status.startsWith('completed') ? '✓' : '○'}</span><span className="remops-phase-name">{phase.label}</span><span className="remops-phase-state">{PHASE_TEXT[phase.status] || phase.status}{phase.detail ? ` · ${phase.detail}` : ''}</span>{documents.length > 0 && <span className="remops-phase-docs">{documents.map((document) => <span key={`${document.file}-${phase.key}`} title={document.file}>{document.file}</span>)}</span>}{index < phases.length - 1 && <span className="remops-flow" aria-hidden="true">···►</span>}</li> })}</ol></section>
}

function Workstream({ attempts = [], generatedAt }) {
  if (!attempts.length) return null
  const now = generatedAt ? Date.parse(generatedAt) : null
  const shown = attempts.slice(0, 3)
  return <section className="remops-work"><h3>In flight now <span>· {attempts.length} document{attempts.length === 1 ? '' : 's'}</span></h3><ul>{shown.map((a) => { const signal = now && a.progress_at ? (now - Date.parse(a.progress_at)) / 1000 : null; const trail = Array.isArray(a.trail) ? a.trail : []; return <li key={`${a.file}-${a.started_at || ''}`}><div className="remops-doc-head"><strong><span aria-hidden="true">●</span> <span className="fname">{a.file}</span></strong><span>{ago(a.elapsed_s) ? `in flight ${ago(a.elapsed_s)}` : ''}</span></div><div className="remops-trail"><span className="remops-done">✓ Opened</span>{trail.map((step, index) => <span className="remops-trail-step" key={`${step.label || step}-${index}`}><span aria-hidden="true">→</span><span className="remops-done">✓ {step.label || step}</span></span>)}<span aria-hidden="true">→</span><span className="remops-active">● {a.phase || 'Processing'}</span>{a.attempt > 1 && <span>attempt {a.attempt}</span>}{ago(signal) && <span>last signal {ago(signal)} ago</span>}</div></li> })}</ul>{attempts.length > 3 && <p className="muted">and {attempts.length - 3} more document{attempts.length - 3 === 1 ? '' : 's'} in flight</p>}</section>
}

function RetryNotice({ retryAt, now }) {
  const seconds = retrySeconds(retryAt, now)
  if (seconds === null) return null
  return <div className="remops-retry" role="status"><span aria-hidden="true">↻</span> Temporary issue · {seconds > 0 ? `retry in ${seconds}s` : 'retry due now'}</div>
}

function Milestones({ notices, onDismiss }) {
  return notices.length ? <aside className="remops-milestones" aria-label="Completion milestones">{notices.map((notice) => <div key={notice.key}><span><span aria-hidden="true">✓</span> {notice.text}</span><button type="button" aria-label={`Dismiss ${notice.text}`} onClick={() => onDismiss(notice.key)}>×</button></div>)}</aside> : null
}

function ActivityPulse({ events, generatedAt }) {
  const buckets = activityBuckets(events, generatedAt)
  const max = Math.max(0, ...buckets)
  if (!max) return null
  return <div className="remops-pulse-strip" aria-label={`Last 60 seconds: ${buckets.reduce((sum, value) => sum + value, 0)} recorded events`}><span>Last 60 seconds</span><span className="remops-pulse-bars" aria-hidden="true">{buckets.map((value, index) => <i key={index} style={{ height: `${Math.max(2, value / max * 12)}px` }} />)}</span></div>
}

function Throughput({ snapshot, frozen = false }) {
  const latest = snapshot.throughput || {}
  const latestRef = useRef(latest)
  latestRef.current = latest
  const [data, setData] = useState(latest)
  useEffect(() => setData(latestRef.current), [snapshot.run_id])
  useEffect(() => {
    if (frozen) return undefined
    const timer = setInterval(() => setData(latestRef.current), 12_000)
    return () => clearInterval(timer)
  }, [frozen])
  const bars = Array.isArray(data.buckets) ? data.buckets.slice(-10) : []
  const max = Math.max(1, ...bars.map((v) => Number(v) || 0))
  return <section className="remops-throughput"><h3>Throughput <span>· last 5 minutes</span></h3>{typeof data.documents_per_minute === 'number' ? <>{bars.length > 0 && <div className="remops-bars" aria-label={`${data.documents_per_minute} documents per minute`}>{bars.map((v, i) => <span key={i} style={{ height: `${Math.max(8, Number(v) / max * 100)}%` }} />)}</div>}<p><strong>{data.documents_per_minute.toLocaleString()} documents/min</strong>{data.change_percent != null && data.sample_documents >= 5 && <span className="remops-rate"> {data.change_percent >= 0 ? '↑' : '↓'} {Math.abs(data.change_percent)}% over previous 5 minutes</span>}</p></> : <p className="muted">Server-observed throughput will appear after the first comparable documents finish.</p>}</section>
}

function Secondary({ snapshot }) {
  const rows = secondaryRows(snapshot)
  return rows.length ? <dl className="remops-secondary">{rows.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{POSITIVE.has(row.key) ? <LiveCounter value={row.value} /> : row.value.toLocaleString()}</dd></div>)}</dl> : null
}

function Activity({ events = [] }) {
  return <section className="remops-activity"><h3>Live activity</h3>{events.length ? <ol aria-label="Recent remediation activity">{events.slice(0, 10).map((event) => <li key={event.key}><time dateTime={event.occurredAt || undefined}>{event.occurredAt ? new Date(event.occurredAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'Now'}</time><span aria-hidden="true">{event.tone === 'error' ? '×' : event.tone === 'attention' ? '!' : event.tone === 'success' ? '✓' : '·'}</span><span>{event.line}</span></li>)}</ol> : <p className="muted">New durable remediation events will appear here.</p>}</section>
}

function Exceptions({ snapshot }) {
  const groups = [['Manual decisions', snapshot.review?.items], ['Verification failures', snapshot.fixes?.verification_failures], ['Delivery failures', snapshot.delivery?.failures], ['Failed documents', snapshot.documents?.failed]].filter(([, value]) => typeof value === 'number' && value > 0)
  return groups.length ? <section className="remops-exceptions"><h3>Needs attention · {groups.reduce((sum, [, value]) => sum + value, 0)}</h3><ul>{groups.map(([label, value]) => <li key={label}><strong>{value}</strong> {label}</li>)}</ul></section> : null
}

export default function RemediationOpsPanel({ snapshot = null, connected = false, receivedAt = null, events = [], updateMode = 'idle', onViewMonitor = null }) {
  const [paused, setPaused] = useState(false)
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden)
  const [clock, setClock] = useState(() => Date.now())
  const [milestones, setMilestones] = useState([])
  const previousSnapshot = useRef(null)
  useEffect(() => { if (typeof document === 'undefined') return undefined; const change = () => setHidden(document.hidden); document.addEventListener('visibilitychange', change); return () => document.removeEventListener('visibilitychange', change) }, [])
  useEffect(() => { if (paused || hidden || !snapshot?.retry_at) return undefined; const timer = setInterval(() => setClock(Date.now()), 1_000); return () => clearInterval(timer) }, [paused, hidden, snapshot?.retry_at])
  useEffect(() => { const previous = previousSnapshot.current; previousSnapshot.current = snapshot; const crossed = milestoneCrossings(previous, snapshot); if (crossed.length) setMilestones((current) => [...current, ...crossed.filter((next) => !current.some((item) => item.key === next.key))]) }, [snapshot])
  if (!snapshot || snapshot.state === 'draft') return null
  const fresh = freshness({ snapshot, connected, receivedAt })
  const line = headline(snapshot)
  const suspect = snapshot.integrity?.ok === false
  return <section className={`panel remops${paused || hidden ? ' remops-motion-paused' : ''}`} aria-label="Remediation run status">
    <header className="remops-header"><div><span className="remops-eyebrow">Remediation {snapshot.terminal ? 'complete' : 'in progress'}</span><h2>{line}</h2>{snapshot.source?.breadcrumb && <p>{snapshot.source.breadcrumb}</p>}<p className="muted">{snapshot.source?.locked_at ? `Snapshot locked ${new Date(snapshot.source.locked_at).toLocaleString()} · ` : ''}{snapshot.run_id}</p></div><div className="remops-actions"><FreshnessBadge state={fresh} updateMode={updateMode} /><button type="button" className="ghost" aria-pressed={paused} onClick={() => setPaused((value) => !value)}>{paused ? 'Resume visual updates' : 'Pause visual updates'}</button>{onViewMonitor && <button type="button" className="linklike" onClick={onViewMonitor}>View in Monitor →</button>}</div></header>
    {suspect && <div className="remops-integrity" role="status"><b>Status temporarily inconsistent.</b> ACP cannot currently reconcile {(snapshot.integrity.affected || []).join(', ') || 'one or more values'}. The values below are the last ACP confirmed.</div>}
    <ActivityPulse events={events} generatedAt={snapshot.generated_at} />
    <Milestones notices={milestones} onDismiss={(key) => setMilestones((current) => current.filter((notice) => notice.key !== key))} />
    <RetryNotice retryAt={snapshot.retry_at} now={clock} />
    <Progress snapshot={snapshot} suspect={suspect} /><Pipeline phases={snapshot.phases} attempts={snapshot.active_attempts || []} moving={connected && snapshot.state !== 'stalled' && (snapshot.active_attempts || []).length > 0} />
    <div className="remops-two"><Workstream attempts={snapshot.active_attempts || []} generatedAt={snapshot.generated_at} /><Throughput snapshot={snapshot} frozen={paused || hidden} /></div>
    <Secondary snapshot={snapshot} /><div className="remops-bottom"><Activity events={events} /><Exceptions snapshot={snapshot} /></div>
    <p aria-live="polite" className="sr-only" data-testid="rem-ops-announce">{line}</p>
  </section>
}
