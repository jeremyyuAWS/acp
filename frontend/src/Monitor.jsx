import { useEffect, useMemo, useRef, useState } from 'react'
import { monitoringState, sourceWatch, IDENTITY, SIM } from './sim.js'
import { getSchedule, putSchedule, listCampaigns, createCampaign, setCampaignStatus, getScanDiff } from './api.js'
import { prefersReducedMotion } from './a11y.js'
import RegressionRadar from './RegressionRadar.jsx'
import ComplianceDigest from './ComplianceDigest.jsx'

// Step 10 · Monitor — the always-on surface. Shows every connected source being
// continuously watched for new files and changes, a live event stream (with demo
// controls to inject events), scheduled re-scans, drift detection, and the rules.
const KIND = {
  new: ['＋', '#185FA5', '#E7F0FB', 'new file'],
  changed: ['✎', '#854F0B', '#FAEEDA', 'changed'],
  scanned: ['◷', '#3C3489', '#EEEDFE', 'scanned'],
  regressed: ['▼', '#1F5FA8', '#E2EDFB', 'regression'],
  recertified: ['✓', '#3B6D11', '#E7F0DC', 're-certified'],
  clean: ['✓', '#5F5E5A', '#EFEDEA', 'no change'],
}
const SRC_ICON = { sharepoint: '▤', gdrive: '▣', box: '◰', confluence: '❖', cms: '🌐', s3: '☁', onedrive: '☁' }
const hrs = (m) => m >= 90 ? `${(m / 60).toFixed(1)} hrs` : `${Math.round(m)} min`

const DEC_ACT = { auto: 'auto-fix', assisted: 'review', review: 'review', archive: 'archive', keep: 'archive', manual: 'review' }
const DEC_WHAT = { auto: 'issues auto-remediated', assisted: 'AI fix queued for approval', review: 'flagged for manual review', archive: 'marked for archive — superseded', keep: 'kept as-is', manual: 'flagged for manual rebuild' }
const ACTOR = { 'auto-fix': 'mova engine', review: 'you', publish: 'mova engine', 're-scan': 'mova engine', archive: 'mova engine' }
const ACOLOR = { 'auto-fix': '#157A56', review: '#854F0B', publish: '#185FA5', 're-scan': '#3B6D11', archive: '#5F5E5A' }

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
      { label: 'Batch 2 · SERIOUS HITL review',  count: sim ? 189 : b2.length, done: sim ? 44 : decided(b2), color: '#854F0B', bg: '#FAEEDA', note: 'human approval needed' },
      { label: 'Batch 3 · MODERATE sweep',       count: sim ? 521 : b3.length, done: sim ? 0  : decided(b3), color: '#1F5FA8', bg: '#E2EDFB', note: 'auto-fix + spot-check' },
      { label: 'N/A · excluded from plan',       count: sim ? 490 : na.length, done: sim ? 490: na.length,  color: '#9a948f', bg: '#EFEDEA', note: 'internal / compliant / junk' },
    ],
  }
}

export default function Monitor({ run, scanList = [], sources = [], files = [], ratified, decisions = {}, publishedFiles = [], aiEnabled = true, onAiToggle, busy = false, progress = null, scanPct = 0, scanStatus = '', readOnly = false, me }) {
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
          { label: 'Resolved', value: prog.batches.reduce((a, b) => a + b.done, 0).toLocaleString(), color: '#3B6D11' },
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
                  <div className="ctlsub">Event-based triggers <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: 0.4, color: '#854F0B', background: '#FBF1DF', border: '1px solid #EAD9BF', borderRadius: 4, padding: '1px 5px', marginLeft: 6, verticalAlign: 'middle' }}>PREVIEW</span></div>
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
                        title={readOnly ? 'Time-travel replay — switch to the latest scan to manage the program' : undefined}>
                  {campaign.status === 'paused' ? '▶ resume' : '⏸ pause'}
                </button>
              </>
            ) : run?.id && (
              <button className="ghost small" disabled={campaignBusy || readOnly} onClick={persistProgram}
                      title={readOnly ? 'Time-travel replay — switch to the latest scan to manage the program' : 'Save this program so pause/resume and progress survive a reload'}>
                {campaignBusy ? 'saving…' : '💾 persist this program'}
              </button>
            )}
            {campaignErr && <span style={{ fontSize: 12, color: '#A32D2D' }} role="alert">⚠ {campaignErr}</span>}
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
                  <span style={{ color: b.color, fontWeight: 600, fontSize: 13 }}>{b.label}</span>
                  <span className="muted" style={{ fontSize: 11 }}>{b.note}</span>
                </div>
                <div className="progtrack">
                  <div className="progbar"><i style={{ width: `${pct}%`, background: b.color, opacity: 0.75 }} /></div>
                  <span className="progpct" style={{ color: b.color }}>{pct}%</span>
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
        <div className="moncard"><span className="muted">Resolved</span><b style={{ color: '#3B6D11' }}>{prog.batches.reduce((a, b) => a + b.done, 0).toLocaleString()}</b><span className="muted">of {prog.batches.reduce((a, b) => a + b.count, 0).toLocaleString()}</span></div>
      </div>

      {slaItems.length > 0 && (
        <section className="panel" style={{ marginBottom: 14 }}>
          <div className="slahd">
            <h2 style={{ margin: 0 }}>SLA tracking <span className="muted">· remediation deadlines from your business ontology</span></h2>
            {slaBreached.length > 0 && <span className="slachip breached">⚠ {slaBreached.length} breached</span>}
          </div>
          <div className="slastats">
            <div className="slastat"><b style={{ color: '#1F5FA8' }}>{slaItems.length}</b><span className="muted">under SLA</span></div>
            <div className="slastat"><b style={{ color: slaBreached.length ? '#854F0B' : '#5F5E5A' }}>{slaBreached.length}</b><span className="muted">breached</span></div>
            <div className="slastat"><b style={{ color: '#996F08' }}>{slaAtRisk.length}</b><span className="muted">at risk</span></div>
            <div className="slastat"><b style={{ color: '#3B6D11' }}>{slaOnTrack.length}</b><span className="muted">on track</span></div>
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
          <h2 style={{ margin: 0 }}>Scheduled re-scans <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: 0.4, color: '#3B6D11', background: '#E7F0DC', border: '1px solid #C9E0B0', borderRadius: 4, padding: '1px 5px', marginLeft: 8, verticalAlign: 'middle' }}>LIVE</span> <span className="muted">· automatic re-scan of your estate, server-side via the service account</span></h2>
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
          {schedErr && <span style={{ fontSize: 12, color: '#A32D2D' }} role="alert">⚠ {schedErr}</span>}
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
