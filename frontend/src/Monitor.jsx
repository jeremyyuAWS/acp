import { useEffect, useMemo, useRef, useState } from 'react'
import { monitoringState, sourceWatch, IDENTITY, SIM } from './sim.js'
import { getSchedule, putSchedule, listCampaigns, createCampaign, setCampaignStatus, getScanDiff, getSourceStatus, getAiProvidersHealth } from './api.js'
import { prefersReducedMotion } from './a11y.js'
import RegressionRadar from './RegressionRadar.jsx'
import ComplianceDigest from './ComplianceDigest.jsx'
import { Sparkline } from './ScoreRing.jsx'
import FailureLane from './FailureLane.jsx'
import QueuePanel from './QueuePanel.jsx'
import RevisionHistoryPanel from './RevisionHistoryPanel.jsx'
import ScanActivityPanel from './ScanActivityPanel.jsx'

// Step 10 · Monitor — the always-on surface. Shows every connected source being
// continuously watched for new files and changes, a live event stream (with demo
// controls to inject events), scheduled re-scans, drift detection, and the rules.
const KIND = {
  new: ['＋', '#185FA5', '#E7F0FB', 'new file'],
  changed: ['✎', 'var(--warn-fg)', 'var(--warn-bg)', 'changed'],
  scanned: ['◷', '#3C3489', '#EEEDFE', 'scanned'],
  regressed: ['▼', 'var(--info-fg)', 'var(--info-bg)', 'regression'],
  recertified: ['✓', 'var(--success-fg)', 'var(--success-bg)', 're-certified'],
  clean: ['✓', '#5F5E5A', '#EFEDEA', 'no change'],
}
const SRC_ICON = { sharepoint: '▤', gdrive: '▣', box: '◰', confluence: '❖', cms: '🌐', s3: '☁', onedrive: '☁' }
const hrs = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`

const DEC_ACT = { auto: 'auto-fix', assisted: 'review', review: 'review', archive: 'archive', keep: 'archive', manual: 'review' }
const DEC_WHAT = { auto: 'issues auto-remediated', assisted: 'AI fix queued for approval', review: 'flagged for manual review', archive: 'marked for archive — superseded', keep: 'kept as-is', manual: 'flagged for manual rebuild' }
const ACTOR = { 'auto-fix': 'mova engine', review: 'you', publish: 'mova engine', 're-scan': 'mova engine', archive: 'mova engine' }
const ACOLOR = { 'auto-fix': '#157A56', review: 'var(--warn-fg)', publish: '#185FA5', 're-scan': 'var(--success-fg)', archive: '#5F5E5A' }

function Toggle({ label, hint, on, set }) {
  return (
    <button className="togrow" role="switch" aria-checked={on} onClick={() => set(!on)}>
      <span className={on ? 'tsw on' : 'tsw'} aria-hidden="true"><i /></span>
      <span className="toglabel">{label}{hint && <span className="muted tog-hint">{hint}</span>}</span>
    </button>
  )
}

// Marks panels that show illustrative content (continuous-monitoring demo data) rather
// than live scan output — so a real user isn't misled. Renders nothing in SIM/demo mode.
const SampleTag = () => SIM ? null : (
  <span title="Illustrative — not from your live scans (continuous monitoring isn't wired yet)"
        style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.04em', color: '#7A6A3A',
                 background: '#F3ECD7', border: '1px solid #E3D3A8', borderRadius: 6,
                 padding: '1px 7px', marginLeft: 8, verticalAlign: 'middle' }}>SAMPLE</span>
)

// Published-doc watchdog: a regression on any document is worth knowing about, but a
// regression on one that's already PUBLISHED (live, certified) is a different order of
// urgency -- it means a document currently presented as compliant no longer is. Reuses
// the same scan-diff data RegressionRadar computes (ADR 0009), filtered to publishedFiles.
function PublishedWatchdog({ run, scanList, publishedFiles }) {
  const [diff, setDiff] = useState(null)
  const runId = run?.id
  useEffect(() => {
    if (!runId || !publishedFiles.length) { setDiff(null); return }
    let cancelled = false
    getScanDiff(runId).then((d) => { if (!cancelled) setDiff(d) }).catch(() => { if (!cancelled) setDiff(null) })
    return () => { cancelled = true }
  }, [runId, publishedFiles.length])

  if (!runId || !publishedFiles.length || scanList.length < 2 || !diff || diff.no_baseline) return null
  const published = new Set(publishedFiles)
  const atRisk = (diff.regressed || []).filter((r) => published.has(r.file))
  if (!atRisk.length) return null

  return (
    <div style={{ margin: '0 0 14px', padding: '12px 14px', borderRadius: 9,
                  background: '#FCEBEB', border: '1px solid #F3C9C9' }}>
      <b style={{ color: '#7A2020', fontSize: 13.5 }}>
        ⚠ {atRisk.length} published document{atRisk.length !== 1 ? 's' : ''} regressed since certification
      </b>
      <div className="muted" style={{ fontSize: 12, margin: '3px 0 8px' }}>
        These are live and presented as compliant, but the last scan found they no longer are.
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {atRisk.map((r) => (
          <div key={r.file} style={{ fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontWeight: 600 }}>{r.file}</span>
            <span className="muted">{r.prev} → {r.cur} ({r.delta})</span>
            {r.broke?.length ? <span className="muted">· broke {r.broke.map((b) => b.sc).join(', ')}</span> : null}
          </div>
        ))}
      </div>
    </div>
  )
}

// Derive program phase data from the live corpus + decisions
function useProgramBatches(files, decisions) {
  const total = files.length || 124
  const hasCrit = (f) => (f.issues || []).some((i) => i.severity === 'CRITICAL')
  const hasSer  = (f) => (f.issues || []).some((i) => i.severity === 'SERIOUS')
  const hasMod  = (f) => (f.issues || []).some((i) => i.severity === 'MODERATE')
  const isNA    = (f) => (f.score ?? 0) >= 90 && !(f.issues || []).some((i) => i.severity === 'CRITICAL' || i.severity === 'SERIOUS')
  const b1 = files.filter(hasCrit)
  const b2 = files.filter((f) => !hasCrit(f) && hasSer(f))
  const b3 = files.filter((f) => !hasCrit(f) && !hasSer(f) && hasMod(f))
  const na = files.filter(isNA)
  const decided = (batch) => batch.filter((f) => decisions[f.file]?.state === 'accepted' || decisions[f.file]?.state === 'override').length
  // SIM defaults when no real data
  const sim = !files.length
  return {
    total: sim ? total : files.length,
    deadline: '2026-06-28',
    batches: [
      { label: 'Batch 1 · CRITICAL auto-fix',    count: sim ? 47  : b1.length, done: sim ? 38 : decided(b1), color: '#7B1D1D', bg: '#FDECEA', note: 'auto-fix eligible · one click' },
      { label: 'Batch 2 · SERIOUS HITL review',  count: sim ? 189 : b2.length, done: sim ? 44 : decided(b2), color: 'var(--warn-fg)', bg: 'var(--warn-bg)', note: 'human approval needed' },
      { label: 'Batch 3 · MODERATE sweep',       count: sim ? 521 : b3.length, done: sim ? 0  : decided(b3), color: 'var(--info-fg)', bg: 'var(--info-bg)', note: 'auto-fix + spot-check' },
      { label: 'N/A · excluded from plan',       count: sim ? 490 : na.length, done: sim ? 490: na.length,  color: '#9a948f', textColor: 'var(--muted)', bg: '#EFEDEA', note: 'internal / compliant / junk' },
    ],
  }
}

export default function Monitor({ run, scanList = [], sources = [], files = [], ratified, decisions = {}, publishedFiles = [], aiEnabled = true, onAiToggle, busy = false, progress = null, scanPct = 0, readOnly = false, me, focusScanId = null, onClearFocus = null, trend = [], trendDates = [] }) {
  const m = monitoringState(files)
  // Real signed-in org for the evidence report — demo org only in SIM.
  const orgName = SIM ? IDENTITY.org : (me?.email?.split('@')[1]?.replace(/\.[^.]+$/, '') || me?.name || 'your organisation')
  const watch = sourceWatch(sources, files)
  const derivedProg = useProgramBatches(files, decisions)

  // ADR 0003 Phase 4: the program below was purely client-derived (recomputed from
  // files/decisions on every render, nothing survived a reload). If a real campaign
  // has been persisted for this scan, its batch counts win; the derived view is only
  // the illustrative fallback until one exists.
  const [campaign, setCampaign] = useState(null)
  const [campaignBusy, setCampaignBusy] = useState(false)
  useEffect(() => {
    if (!run?.id) { setCampaign(null); return }
    let live = true
    listCampaigns(run.id).then((cs) => { if (live) setCampaign(cs?.[0] || null) }).catch(() => {})
    return () => { live = false }
  }, [run?.id])

  // R5 — real source-staleness on the Monitor tab. The Release Center already consumes this
  // (Publish.jsx / getSourceStatus, #253); Continuous Monitoring showed only illustrative drift
  // until now. Best-effort and honest: a scan with nothing trackable returns zero, any error leaves
  // the panel empty rather than inventing changes, and it never marks a file "changed" it can't
  // verify. Gated to a real run — SIM/demo keeps its illustrative surfaces (SampleTag), never this.
  const [drift, setDrift] = useState({ loaded: false, stale: 0, untracked: 0, files: [] })
  useEffect(() => {
    if (SIM || !run?.id) { setDrift({ loaded: false, stale: 0, untracked: 0, files: [] }); return }
    let live = true
    getSourceStatus(run.id)
      .then((s) => {
        if (!live) return
        const files = (s?.files || []).filter((r) => r.state === 'stale')
        setDrift({ loaded: true, stale: s?.stale_count || 0, untracked: s?.untracked_count || 0, files })
      })
      .catch(() => { if (live) setDrift({ loaded: true, stale: 0, untracked: 0, files: [] }) })
    return () => { live = false }
  }, [run?.id])

  const [providerHealth, setProviderHealth] = useState(null)
  useEffect(() => {
    if (!me?.is_admin) return
    let live = true
    getAiProvidersHealth(24).then((d) => { if (live) setProviderHealth(d) }).catch(() => {})
    return () => { live = false }
  }, [me?.is_admin])

  const BUCKET_ORDER = ['critical', 'serious', 'moderate', 'na']
  const prog = useMemo(() => {
    if (!campaign?.batches?.length) return derivedProg
    const byBucket = Object.fromEntries(campaign.batches.map((b) => [b.bucket, b]))
    return { ...derivedProg, batches: derivedProg.batches.map((b, i) => {
      const real = byBucket[BUCKET_ORDER[i]]
      return real ? { ...b, count: real.count, done: real.done } : b
    }) }
  }, [derivedProg, campaign])
  const [campaignErr, setCampaignErr] = useState('')
  const persistProgram = async () => {
    if (!run?.id || campaignBusy || readOnly) return
    setCampaignBusy(true); setCampaignErr('')
    try {
      const c = await createCampaign(run.id, 'Remediation Program — 2026 ADA Title II Compliance', prog.deadline)
      setCampaign(c)
    } catch (e) {
      setCampaignErr(e.message || 'could not save the program — try again')
    } finally {
      setCampaignBusy(false)
    }
  }
  const toggleCampaignPause = async () => {
    if (!campaign || campaignBusy || readOnly) return
    setCampaignBusy(true); setCampaignErr('')
    try {
      const next = campaign.status === 'paused' ? 'active' : 'paused'
      const c = await setCampaignStatus(campaign.campaign_id, next)
      setCampaign(c)
    } catch (e) {
      setCampaignErr(e.message || 'could not update the program — try again')
    } finally {
      setCampaignBusy(false)
    }
  }

  // SLA enforcement — uses f.age (days since last edit) as elapsed time proxy.
  const daysInQueue = (f) => Math.floor((f.age || 30) * 0.4)
  const slaItems = files
    .filter((f) => f.ont?.sla && f.status !== 'certifiable' && f.status !== 'error')
    .map((f) => { const elapsed = daysInQueue(f); const remaining = f.ont.sla - elapsed; return { f, sla: f.ont.sla, remaining, status: remaining < 0 ? 'breached' : remaining <= Math.max(3, f.ont.sla * 0.25) ? 'at-risk' : 'on-track' } })
    .sort((a, b) => a.remaining - b.remaining)
  const slaBreached = slaItems.filter((s) => s.status === 'breached')
  const slaAtRisk = slaItems.filter((s) => s.status === 'at-risk')
  const slaOnTrack = slaItems.filter((s) => s.status === 'on-track')

  // Collapsible settings at top — remembered per session so it doesn't snap shut
  // on every tab switch once someone has opened it.
  const [controlsOpen, setControlsOpen] = useState(() => sessionStorage.getItem('acp-mon-controls') === '1')
  useEffect(() => { try { sessionStorage.setItem('acp-mon-controls', controlsOpen ? '1' : '0') } catch { /* ignore */ } }, [controlsOpen])
  const evidenceRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const [schedNext, setSchedNext] = useState(null)
  // The last sweep's outcome from /schedule ({ok, at, source, error, files, scan_id}), or null
  // before any has run. A FAILED sweep saves nothing and leaves the previous scan standing, so
  // without this the estate on screen silently ages while every date on the page still looks
  // current. Named for the outcome, not the time, because the time was never the missing part.
  const [lastSweep, setLastSweep] = useState(null)
  // When the last scan that DID save completed — what the page is actually showing while a
  // sweep is failing. `last_at` from /schedule.
  const [schedLastAt, setSchedLastAt] = useState(null)
  const exportEvidence = async () => {
    if (exporting) return
    setExporting(true)
    try {
      const { exportEvidenceReport } = await import('./pdfReport.js')
      await exportEvidenceReport({
        org: orgName,
        date: new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }),
        summary: `${prog.total.toLocaleString()} documents in the remediation plan across ${prog.batches.length} batches; ${prog.batches.reduce((a, b) => a + b.done, 0).toLocaleString()} of ${prog.batches.reduce((a, b) => a + b.count, 0).toLocaleString()} resolved. Evidence below is the live audit trail of decisions and re-validations recorded for this estate.`,
        metrics: [
          { label: 'Documents in scope', value: files.length.toLocaleString() },
          { label: 'In remediation plan', value: prog.total.toLocaleString() },
          { label: 'Resolved', value: prog.batches.reduce((a, b) => a + b.done, 0).toLocaleString(), color: 'var(--success-fg)' },
          { label: 'Sources', value: new Set(files.map((f) => f.sourceName).filter(Boolean)).size || 1 },
        ],
        events: realAuditSrc.map(([action, change, document]) => ({ action, actor: ACTOR[action] || 'mova engine', change, document })),
      })
    } catch (e) { console.error('evidence export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }
  const [triggers, setTriggers] = useState({ newFile: true, onEdit: true, autoRemediate: true, alertRegression: true })
  const [cad, setCad] = useState(() => Object.fromEntries(watch.map((w) => [w.id, w.cadence])))
  const [schedErr, setSchedErr] = useState('')
  const setAllCad = (v) => {
    // Optimistic UI with a real rollback: if the schedule write fails, revert the
    // chips to what the server still has instead of showing a cadence that isn't real.
    const prev = cad
    setCad(Object.fromEntries(watch.map((w) => [w.id, v])))
    setSchedErr('')
    if (!SIM) {
      const minMap = { live: 5, hourly: 60, daily: 1440, weekly: 10080 }
      putSchedule({ enabled: v !== 'off', interval_minutes: minMap[v] ?? 60 })
        .then((s) => setSchedNext(s.next_at))
        .catch((e) => { setCad(prev); setSchedErr(e.message || 'schedule not saved — try again') })
    }
  }

  // Build the live audit trail: published files first, then remediation decisions, padded with baseline.
  const realAuditSrc = useMemo(() => {
    const fromPub = publishedFiles.slice(-3).reverse().map((file) => ['publish', 'published · fixed copy stored · audit recorded', file])
    const decided = files.filter((f) => decisions[f.file])
    const fromDec = decided.slice(0, 4 - fromPub.length).map((f) => {
      const dec = decisions[f.file]
      const eff = dec.state === 'override' ? dec.action : dec.state === 'rejected' ? 'archive' : f.rec?.action || 'review'
      return [DEC_ACT[eff] || 'review', (DEC_WHAT[eff] || 'decision recorded') + ' · ' + f.file, f.file]
    })
    return [...fromPub, ...fromDec].slice(0, 6)   // REAL events only — no baseline padding
  }, [decisions, files, publishedFiles])
  const auditSrcRef = useRef(realAuditSrc)
  auditSrcRef.current = realAuditSrc
  // Show everything realAuditSrc holds (max 6) — the screen used to cap at 4 while
  // the exported evidence carried 6, so the export could contain events the
  // operator never saw on screen.
  const [audit, setAudit] = useState(() => realAuditSrc.map((e, i) => ({ e, id: -i })))
  const auditNext = useRef(1)

  // When decisions or published files change, refresh the visible audit trail.
  useEffect(() => {
    const decided = files.filter((f) => decisions[f.file])
    if (!decided.length && !publishedFiles.length) return
    setAudit(realAuditSrc.map((e, i) => ({ e, id: -(i + 100) })))
  }, [decisions, publishedFiles]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (SIM) return
    getSchedule().then((s) => {
      setSchedNext(s.next_at)
      setLastSweep(s.last_sweep || null)
      setSchedLastAt(s.last_at || null)
      const v = !s.enabled ? 'off' : s.interval_minutes <= 5 ? 'live' : s.interval_minutes <= 60 ? 'hourly' : s.interval_minutes <= 1440 ? 'daily' : 'weekly'
      setCad((prev) => Object.fromEntries((Object.keys(prev).length ? Object.keys(prev) : watch.map((w) => w.id)).map((k) => [k, v])))
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps


  return (
    <>

      {/* All behaviour settings (AI mode, scan triggers, schedule) collapsed into one
          panel at the top, so the tab leads with live status. Collapsed by default. */}
      <section className="panel" style={{ marginBottom: 14 }}>
        <button onClick={() => setControlsOpen((o) => !o)} aria-expanded={controlsOpen}
          style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                   background: 'none', border: 'none', cursor: 'pointer', padding: 0, font: 'inherit', textAlign: 'left' }}>
          <h2 style={{ margin: 0 }}>⚙ Monitoring settings <span className="muted">· AI mode, scan triggers &amp; schedule</span></h2>
          <span aria-hidden="true" style={{ fontSize: 13, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{controlsOpen ? '▴ hide' : '▾ show'}</span>
        </button>

        {controlsOpen && (
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 18 }}>
            {/* AI remediation mode */}
            <div>
              <h3 style={{ margin: '0 0 8px' }}>AI remediation mode <span className="muted" style={{ fontWeight: 400 }}>· controls which fixes are applied automatically</span></h3>
              <div className="aimodetoggle">
                <div className="aimoderow">
                  <div>
                    <div className="ctlsub">{aiEnabled ? 'AI-assisted mode (on)' : 'Deterministic-only mode (AI off)'}</div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
                      {aiEnabled
                        ? 'AI drafts fixes for semantic content (alt text, link labels, icon names). Deterministic rules (contrast, viewport, tabindex) run always.'
                        : 'Only deterministic rules run. AI-assisted fixes (alt text, link labels, icon names) are routed to the human review queue instead.'}
                    </div>
                  </div>
                  {onAiToggle && (
                    <button className={aiEnabled ? 'aitoggle on' : 'aitoggle'} onClick={() => onAiToggle(!aiEnabled)}
                      aria-pressed={aiEnabled}
                      title={aiEnabled ? 'Turn off AI — deterministic only' : 'Turn on AI-assisted remediation'}>
                      {aiEnabled ? 'AI on' : 'AI off'}
                    </button>
                  )}
                </div>
                {!aiEnabled && (
                  <div className="aioffnote">
                    AI-assisted rules affected: <b>1.1.1 alt text</b>, <b>2.4.4 link purpose</b>, <b>4.1.2 name/role/value</b>, <b>1.4.11 non-text contrast</b> &mdash; these are routed to human review.
                  </div>
                )}
              </div>
            </div>

            {/* Scan triggers & schedule */}
            <div>
              <h3 style={{ margin: '0 0 8px' }}>Scan triggers <span className="muted" style={{ fontWeight: 400 }}>· event-based automation (preview) — the live schedule is below</span></h3>
              <div className="scanctl">
                <div className="ctlcol">
                  <div className="ctlsub">Event-based triggers <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: 0.4, color: 'var(--warn-fg)', background: '#FBF1DF', border: '1px solid #EAD9BF', borderRadius: 4, padding: '1px 5px', marginLeft: 6, verticalAlign: 'middle' }}>PREVIEW</span></div>
                  <div className="muted" style={{ fontSize: 11.5, margin: '0 0 8px', lineHeight: 1.45 }}>Planned agent behaviour — needs Drive change-notifications; not wired yet. The <b>scheduled sweep</b> on the right <b>is live</b>.</div>
                  <div style={{ opacity: 0.5, pointerEvents: 'none' }} aria-hidden="true">
                  <Toggle label="Scan new files on arrival" hint="within 1 hour of landing in a watched source" on={triggers.newFile} set={(v) => setTriggers((t) => ({ ...t, newFile: v }))} />
                  <Toggle label="Re-scan on document edit" hint="detect drift the moment content changes" on={triggers.onEdit} set={(v) => setTriggers((t) => ({ ...t, onEdit: v }))} />
                  <Toggle label="Auto-remediate high-confidence fixes" hint="apply + re-certify without waiting for a sweep" on={triggers.autoRemediate} set={(v) => setTriggers((t) => ({ ...t, autoRemediate: v }))} />
                  <Toggle label="Alert owner on regression" hint="notify when a published doc drops > 5 points" on={triggers.alertRegression} set={(v) => setTriggers((t) => ({ ...t, alertRegression: v }))} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      <ComplianceDigest run={run} />

      <ScanActivityPanel run={run} scanList={scanList} />

      {trend.length > 1 && new Set(trend).size > 1 && (() => {
        const scored = [...scanList].filter((s) => s.completed_at && s.avg_score != null)
          .sort((a, b) => a.completed_at.localeCompare(b.completed_at))
        let velocity = null, etaLabel = null
        if (scored.length >= 2) {
          const first = scored[0], last = scored[scored.length - 1]
          const days = (new Date(last.completed_at) - new Date(first.completed_at)) / 86400000
          if (days >= 1) {
            velocity = ((last.avg_score - first.avg_score) / days) * 7
            if (velocity > 0.05 && last.avg_score < 90) {
              const weeksToTarget = (90 - last.avg_score) / velocity
              const eta = new Date(Date.now() + weeksToTarget * 7 * 86400000)
              etaLabel = eta.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
            }
          }
        }
        return (
          <section className="panel">
            <h2>Compliance trend <span className="muted">· {trend.length} scans</span></h2>
            <Sparkline points={trend} labels={trendDates} width={620} height={104} />
            {velocity != null && (
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span className="badge" style={{ background: velocity > 0 ? 'var(--success-bg)' : velocity < 0 ? '#FCEBEB' : '#EEEDEA',
                                                  color: velocity > 0 ? 'var(--success-fg)' : velocity < 0 ? 'var(--error-fg-strong)' : 'var(--muted)' }}>
                  {velocity > 0 ? '↑' : velocity < 0 ? '↓' : '→'} {Math.abs(velocity).toFixed(1)} pts/week
                </span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {etaLabel ? `at this pace, on track for 90/100 by ${etaLabel}` : velocity <= 0 ? 'flat or regressing — no projected path to 90/100 at this pace' : 'already at or above 90/100'}
                </span>
              </div>
            )}
          </section>
        )
      })()}

      {/* W7 — operational-failure lane. Corrupt files, expired source sign-ins, unreachable
          sources and worker errors show up here (retry → dead-letter) instead of vanishing.
          Owner-scoped and self-polling, so it needs no run/scan context. */}
      <FailureLane />

      <PublishedWatchdog run={run} scanList={scanList} publishedFiles={publishedFiles} />

      <RegressionRadar run={run} scanList={scanList} />

      <section className="panel" style={{ marginBottom: 14 }}>
        <div className="proghd">
          <div>
            <b>Remediation program &mdash; 2026 ADA Title II Compliance</b>
            <span className="muted" style={{ marginLeft: 10, fontSize: 12 }}>Deadline: {prog.deadline} &nbsp;&middot;&nbsp; {prog.total} files in scope</span>
            {!campaign && <SampleTag />}
          </div>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            {campaign ? (
              <>
                <span className={`trstatchip ${campaign.status === 'paused' ? 'defer' : 'inscope'}`} style={{ fontSize: 12 }}>{campaign.status}</span>
                <button className="ghost small" disabled={campaignBusy || readOnly} onClick={toggleCampaignPause}
                        title={readOnly ? 'Scan History replay — switch to the latest scan to manage the program' : undefined}>
                  {campaign.status === 'paused' ? '▶ resume' : '⏸ pause'}
                </button>
              </>
            ) : run?.id && (
              <button className="ghost small" disabled={campaignBusy || readOnly} onClick={persistProgram}
                      title={readOnly ? 'Scan History replay — switch to the latest scan to manage the program' : 'Save this program so pause/resume and progress survive a reload'}>
                {campaignBusy ? 'saving…' : '💾 persist this program'}
              </button>
            )}
            {campaignErr && <span style={{ fontSize: 12, color: 'var(--error-fg-strong)' }} role="alert">⚠ {campaignErr}</span>}
            <span className="trstatchip pending" style={{ fontSize: 12 }}>
              {prog.batches.reduce((a, b) => a + b.done, 0)} / {prog.batches.reduce((a, b) => a + b.count, 0)} resolved
            </span>
          </span>
        </div>
        <div className="progbatches">
          {prog.batches.map((b, i) => {
            const pct = b.count > 0 ? Math.round((b.done / b.count) * 100) : 100
            return (
              <div className="progrow" key={i}>
                <div className="proglabel">
                  <span style={{ color: b.textColor ?? b.color, fontWeight: 600, fontSize: 13 }}>{b.label}</span>
                  <span className="muted" style={{ fontSize: 11 }}>{b.note}</span>
                </div>
                <div className="progtrack">
                  <div className="progbar"><i style={{ width: `${pct}%`, background: b.color, opacity: 0.75 }} /></div>
                  <span className="progpct" style={{ color: b.textColor ?? b.color }}>{pct}%</span>
                  <span className="muted progn">{b.done} / {b.count}</span>
                </div>
              </div>
            )
          })}
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Phases run in parallel &mdash; auto-fixable files in Batch 1 clear with one &ldquo;Run batch&rdquo; click in the Remediate tab &middot; Batch 2 items route to the HITL queue
        </div>
      </section>

      <div className="moncards">
        <div className="moncard"><span className="muted">Documents in scope</span><b>{files.length.toLocaleString()}</b><span className="muted">{new Set(files.map((f) => f.sourceName).filter(Boolean)).size || 1} source{(new Set(files.map((f) => f.sourceName).filter(Boolean)).size || 1) !== 1 ? 's' : ''}</span></div>
        <div className="moncard"><span className="muted">In remediation plan</span><b>{prog.total.toLocaleString()}</b><span className="muted">across {prog.batches.length} batches</span></div>
        <div className="moncard"><span className="muted">Resolved</span><b style={{ color: 'var(--success-fg)' }}>{prog.batches.reduce((a, b) => a + b.done, 0).toLocaleString()}</b><span className="muted">of {prog.batches.reduce((a, b) => a + b.count, 0).toLocaleString()}</span></div>
      </div>

      {/* R5 — Source drift: REAL staleness from the source (getSourceStatus), the same signal the
          Release Center gates on. Not illustrative — no SampleTag. Only rendered for a real run. */}
      {!SIM && run?.id && (
        <section className="panel mon-drift" style={{ marginBottom: 14 }}>
          <div className="slahd">
            <h2 style={{ margin: 0 }}>Source drift <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: 0.4, color: 'var(--success-fg)', background: 'var(--success-bg)', border: '1px solid #C9E0B0', borderRadius: 4, padding: '1px 5px', marginLeft: 8, verticalAlign: 'middle' }}>LIVE</span> <span className="muted">· files changed at the source since this scan</span></h2>
            {drift.loaded && drift.stale > 0 && <span className="slachip breached">⚠ {drift.stale} changed</span>}
          </div>
          {!drift.loaded ? (
            <p className="muted" style={{ marginTop: 8 }}>Checking sources…</p>
          ) : drift.stale === 0 ? (
            <p className="muted" style={{ marginTop: 8 }}>
              No source changes since the last scan — every tracked file still matches what ACP assessed.
              {drift.untracked > 0 && ` (${drift.untracked} file${drift.untracked === 1 ? '' : 's'} not trackable for drift.)`}
            </p>
          ) : (
            <>
              <p className="muted" style={{ marginTop: 8 }}>
                {drift.stale} file{drift.stale === 1 ? '' : 's'} changed at the source since ACP scanned {drift.stale === 1 ? 'it' : 'them'} —
                {drift.stale === 1 ? ' its' : ' their'} certification is stale until re-scanned. Re-scan from the Release Center to refresh.
              </p>
              <ul className="mon-drift-list" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {drift.files.slice(0, 8).map((r) => (
                  <li key={r.file} style={{ fontSize: 13 }}><span className="fname">{r.file}</span></li>
                ))}
              </ul>
              {drift.files.length > 8 && (
                <p className="muted" style={{ marginTop: 4, fontSize: 12 }}>…and {drift.files.length - 8} more.</p>
              )}
            </>
          )}
        </section>
      )}

      {slaItems.length > 0 && (
        <section className="panel" style={{ marginBottom: 14 }}>
          <div className="slahd">
            <h2 style={{ margin: 0 }}>SLA tracking <span className="muted">· remediation deadlines from your business ontology</span></h2>
            {slaBreached.length > 0 && <span className="slachip breached">⚠ {slaBreached.length} breached</span>}
          </div>
          <div className="slastats">
            <div className="slastat"><b style={{ color: 'var(--info-fg)' }}>{slaItems.length}</b><span className="muted">under SLA</span></div>
            <div className="slastat"><b style={{ color: slaBreached.length ? 'var(--warn-fg)' : '#5F5E5A' }}>{slaBreached.length}</b><span className="muted">breached</span></div>
            <div className="slastat"><b style={{ color: '#996F08' }}>{slaAtRisk.length}</b><span className="muted">at risk</span></div>
            <div className="slastat"><b style={{ color: 'var(--success-fg)' }}>{slaOnTrack.length}</b><span className="muted">on track</span></div>
          </div>
          <div className="slalist">
            {slaItems.slice(0, 8).map((s, i) => (
              <div className="slarow" key={i}>
                <span className={`slatag ${s.status}`}>{s.status === 'breached' ? `${-s.remaining}d over` : `${s.remaining}d left`}</span>
                <div className="slamain"><div className="slafile">{s.f.file}</div><div className="muted" style={{ fontSize: 11 }}>{s.f.ont.priority} · {s.sla}-day SLA · rule: {s.f.ont.rule.name}</div></div>
                <span className="muted slasrc">{s.f.sourceName}</span>
              </div>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>Breaches surface here and on the executive dashboard — the agent flags them before the deadline, not after.</p>
        </section>
      )}

      <section className="panel" style={{ marginBottom: 14 }}>
        <div className="proghd">
          <h2 style={{ margin: 0 }}>Scheduled re-scans <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: 0.4, color: 'var(--success-fg)', background: 'var(--success-bg)', border: '1px solid #C9E0B0', borderRadius: 4, padding: '1px 5px', marginLeft: 8, verticalAlign: 'middle' }}>LIVE</span> <span className="muted">· automatic re-scan of your estate, server-side via the service account</span></h2>
          {schedNext && (Object.values(cad)[0] || 'off') !== 'off' && (
            <span className="trstatchip pending" style={{ fontSize: 12 }}>next {new Date(schedNext).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
          )}
        </div>
        <div className="muted" style={{ fontSize: 13, margin: '6px 0 10px' }}>
          {(Object.values(cad)[0] || 'off') === 'off'
            ? 'No schedule set — the estate is re-scanned only when you trigger one manually.'
            : `Re-scanning ${Object.values(cad)[0]}. The scheduled sweep runs server-side and writes results back to your scans + Langfuse.`}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="muted" style={{ fontSize: 13 }}>Cadence:</span>
          {['live', 'hourly', 'daily', 'weekly', 'off'].map((v) => {
            const on = (Object.values(cad)[0] || 'off') === v
            return (
              <button key={v} onClick={() => setAllCad(v)}
                style={{ fontSize: 12, padding: '4px 11px', borderRadius: 6, cursor: 'pointer', fontWeight: on ? 600 : 400,
                  border: '1px solid ' + (on ? '#7C3AED' : 'var(--line)'), background: on ? '#7C3AED' : '#fff', color: on ? '#fff' : 'var(--ink)' }}>{v}</button>
            )
          })}
          {schedErr && <span style={{ fontSize: 12, color: 'var(--error-fg-strong)' }} role="alert">⚠ {schedErr}</span>}
        </div>
        {lastSweep && lastSweep.ok === false && (
          <div role="alert" style={{ marginTop: 12, padding: '11px 14px', borderRadius: 8, fontSize: 13.5,
               background: '#FBE9E7', border: '1px solid #E7B4AC', color: '#8A2A20' }}>
            ⚠ <b>The last scheduled sweep failed — the estate below has not refreshed.</b>{' '}
            The {lastSweep.source || 'drive'} sweep at{' '}
            <b>{lastSweep.at ? new Date(lastSweep.at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'an unknown time'}</b>{' '}
            saved no scan, so every figure on this page still describes the previous scan
            {schedLastAt ? <> from <b>{new Date(schedLastAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</b></> : null}.
            {lastSweep.error && (
              <div style={{ marginTop: 6, fontSize: 12, fontFamily: 'ui-monospace, monospace', opacity: 0.85, wordBreak: 'break-word' }}>
                {lastSweep.error}
              </div>
            )}
          </div>
        )}
      </section>

      {/* "Monitor tells me why" — the operational deep dive, distinct from Assess's own
          in-scan "what is happening right now" panel and from Settings' capacity CONFIG.
          QueuePanel is already fully self-contained (own polling, own state) — reused
          here directly, not duplicated. Placed as its own section: this is a starting
          slice of a larger Workers & Queue console (worker health, queue lanes, retries,
          dead letters, stalled scans, job timelines) requested 2026-08-28 — not the whole
          of it. */}
      <section className="panel" style={{ marginTop: 14 }}>
        <h2 style={{ margin: '0 0 4px' }}>Workers &amp; Queue</h2>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          What the workers are doing right now, across every scan and assessment — reachable
          without an active run, so this no longer means checking Azure logs directly. Adjust
          how many are warm ahead of a large batch in Settings → Worker Configuration.
        </p>
        <QueuePanel focusScanId={focusScanId} onClearFocus={onClearFocus} />
        <RevisionHistoryPanel />
      </section>

      {me?.is_admin && providerHealth && (() => {
        const entries = Object.entries(providerHealth.providers || {})
        const active = entries.filter(([, s]) => s.calls > 0)
        const inactive = entries.filter(([, s]) => s.calls === 0).map(([p]) => p)
        if (!active.length && !inactive.length) return null
        return (
          <section className="panel" style={{ marginTop: 14 }}>
            <h2 style={{ margin: '0 0 4px' }}>AI Provider Health <span className="muted">· last {providerHealth.window_hours}h</span></h2>
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
              Real call evidence from the <code>ai_calls</code> log — never fabricated (ADR 0016).
            </p>
            {active.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {active.map(([provider, s]) => {
                  const errRate = s.calls > 0 ? ((s.errors / s.calls) * 100).toFixed(1) : '0.0'
                  const errColor = s.errors > 0 ? 'var(--warn-fg)' : 'var(--success-fg)'
                  return (
                    <div key={provider} style={{ flex: '1 1 220px', minWidth: 200, padding: '12px 14px',
                        border: '1px solid var(--line)', borderRadius: 8, background: 'var(--card-bg, #fff)' }}>
                      <div style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 6 }}>{provider}</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', fontSize: 12.5 }}>
                        <span><b>{s.calls}</b> <span className="muted">calls</span></span>
                        <span style={{ color: errColor }}><b>{errRate}%</b> <span className="muted">errors</span></span>
                        <span><b>{s.avg_latency_ms != null ? Math.round(s.avg_latency_ms) : '–'}</b> <span className="muted">ms avg</span></span>
                        <span><b>{s.p95_latency_ms != null ? Math.round(s.p95_latency_ms) : '–'}</b> <span className="muted">ms p95</span></span>
                      </div>
                      <div style={{ marginTop: 5, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {s.throttle_count > 0 && (
                          <span style={{ fontSize: 11, padding: '1px 7px', borderRadius: 5,
                              background: '#FFF3CD', border: '1px solid #FFD97D', color: '#7A5800' }}>
                            {s.throttle_count} throttle{s.throttle_count !== 1 ? 's' : ''}
                          </span>
                        )}
                        {s.cold_start_count > 0 && (
                          <span style={{ fontSize: 11, padding: '1px 7px', borderRadius: 5,
                              background: '#E7F0FB', border: '1px solid #A8CBEE', color: '#185FA5' }}>
                            {s.cold_start_count} cold start{s.cold_start_count !== 1 ? 's' : ''}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
            {inactive.length > 0 && (
              <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                No calls in window: {inactive.join(', ')}.
              </p>
            )}
          </section>
        )
      })()}

      <section className="panel" style={{ marginTop: 14 }} ref={evidenceRef}>
        <div className="monfeedhd">
          <h2 style={{ margin: 0 }}>Audit trail · live <span className="pulsedot" aria-hidden="true" /></h2>
          <button className="exportbtn" onClick={exportEvidence} disabled={exporting}>{exporting ? 'Generating…' : '⤓ Export evidence package'}</button>
        </div>
        <div className="auditfeed" style={{ marginTop: 10 }} role="log" aria-live="polite" aria-label="Audit trail">
          {ratified && ratified.total > 0 && (
            <div className="auditrow pinned">
              <span className="auditkind" style={{ background: '#EEEDFE', color: '#3C3489' }}>action plan</span>
              <span className="auditwhat">{ratified.total} recommendation{ratified.total === 1 ? '' : 's'} ratified · {ratified.auto} auto-fix, {ratified.assisted + ratified.review} to review</span>
              <span className="muted auditactor">you · just now</span>
            </div>
          )}
          {audit.map((row) => {
            const [kind, what, file] = row.e
            return (
              <div className="auditrow" key={row.id}>
                <span className="auditkind" style={{ background: ACOLOR[kind] + '1f', color: ACOLOR[kind] }}>{kind}</span>
                <span className="auditwhat">{what} · <span className="fname" style={{ fontSize: 12 }}>{file}</span></span>
                <span className="muted auditactor">{ACTOR[kind]}</span>
              </div>
            )
          })}
          {!audit.length && !(ratified && ratified.total > 0) && (
            <p className="muted" style={{ fontSize: 13, padding: '4px 2px' }}>No activity yet — decisions, auto-fixes, re-validations and publishes appear here as you work.</p>
          )}
        </div>
        <p className="muted" style={{ marginTop: 10 }}>Immutable who / when / what / which-engine log — your ADA &amp; EAA evidence trail.</p>
      </section>
    </>
  )
}
