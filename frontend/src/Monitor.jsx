import { useEffect, useMemo, useRef, useState } from 'react'
import { monitoringState, sourceWatch, IDENTITY, SIM } from './sim.js'
import { getSchedule, putSchedule } from './api.js'
import { prefersReducedMotion } from './a11y.js'
import QueuePanel from './QueuePanel.jsx'
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

// Baseline audit entries — shown when no real decisions have been made yet.
const BASELINE_AUDIT = [
  ['auto-fix', 'alt-text added to figure 3', 'benefits-guide.pdf'],
  ['review', 'approved table-header fix', 'q3-board-deck.pptx'],
  ['publish', 'replaced in place', 'hr-policy-2026.docx'],
  ['re-scan', 'verified 100 / 100', 'onboarding.pdf'],
  ['archive', 'superseded version archived', '2019-policy-old.docx'],
  ['auto-fix', 'reading order corrected', 'annual-report.pdf'],
]
const DEC_ACT = { auto: 'auto-fix', assisted: 'review', review: 'review', archive: 'archive', keep: 'archive', manual: 'review' }
const DEC_WHAT = { auto: 'issues auto-remediated', assisted: 'AI fix queued for approval', review: 'flagged for manual review', archive: 'archived — superseded', keep: 'kept as-is', manual: 'flagged for manual rebuild' }
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

export default function Monitor({ run, scanList = [], sources = [], files = [], ratified, decisions = {}, publishedFiles = [], aiEnabled = true, onAiToggle }) {
  const m = monitoringState(files)
  const watch = sourceWatch(sources, files)
  const prog = useProgramBatches(files, decisions)

  // SLA enforcement — uses f.age (days since last edit) as elapsed time proxy.
  const daysInQueue = (f) => Math.floor((f.age || 30) * 0.4)
  const slaItems = files
    .filter((f) => f.ont?.sla && f.status !== 'certifiable' && f.status !== 'error')
    .map((f) => { const elapsed = daysInQueue(f); const remaining = f.ont.sla - elapsed; return { f, sla: f.ont.sla, remaining, status: remaining < 0 ? 'breached' : remaining <= Math.max(3, f.ont.sla * 0.25) ? 'at-risk' : 'on-track' } })
    .sort((a, b) => a.remaining - b.remaining)
  const slaBreached = slaItems.filter((s) => s.status === 'breached')
  const slaAtRisk = slaItems.filter((s) => s.status === 'at-risk')
  const slaOnTrack = slaItems.filter((s) => s.status === 'on-track')

  // event pool grounded in real corpus docs
  const pub = files.find((f) => (f.tags || []).includes('public-facing'))?.file || 'public-page.html'
  const cert = files.find((f) => f.status === 'certifiable')?.file || 'onboarding.pdf'
  const iss = files.find((f) => (f.issues || []).length)?.file || 'care-pathway.pdf'
  const POOL = [
    { kind: 'new', src: 'SharePoint · HR', doc: 'hr-policy-2026.docx', text: 'New file landed — auto-queued for scan' },
    { kind: 'scanned', src: 'Box · Cardiology', doc: iss, text: 'Auto-scanned a new document — 2 findings, score 71' },
    { kind: 'changed', src: 'Google Drive', doc: cert, text: 'Document edited — re-assessment triggered' },
    { kind: 'regressed', src: 'CMS · public site', doc: pub, text: 'Score dropped 100 → 82 after an edit — alert raised' },
    { kind: 'recertified', src: 'Box · Cardiology', doc: iss, text: 'Auto-remediated & re-certified at 100/100' },
    { kind: 'clean', src: 'Confluence', doc: cert, text: 'Scheduled re-scan complete — no change' },
  ]
  const seed = [3, 2, 1, 0].map((k, i) => ({ ...POOL[k], id: -i, when: ['just now', '4m ago', '9m ago', '15m ago'][i] }))
  const [events, setEvents] = useState(seed)
  const [paused, setPaused] = useState(false)
  const [controlsOpen, setControlsOpen] = useState(false)  // collapsible settings at top
  const evidenceRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const [schedNext, setSchedNext] = useState(null)
  const exportEvidence = async () => {
    if (exporting) return
    setExporting(true)
    try {
      const { exportEvidenceReport } = await import('./pdfReport.js')
      await exportEvidenceReport({
        org: IDENTITY.org,
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
  const setAllCad = (v) => {
    setCad(Object.fromEntries(watch.map((w) => [w.id, v])))
    if (!SIM) {
      const minMap = { live: 5, hourly: 60, daily: 1440, weekly: 10080 }
      putSchedule({ enabled: v !== 'off', interval_minutes: minMap[v] ?? 60 })
        .then((s) => setSchedNext(s.next_at))
        .catch(() => {})
    }
  }
  const cadCount = (v) => Object.values(cad).filter((c) => c === v).length
  const next = useRef(1)
  const push = (e) => setEvents((cur) => [{ ...e, id: next.current++, when: 'just now' }, ...cur].slice(0, 9))

  // Build the live audit trail: published files first, then remediation decisions, padded with baseline.
  const realAuditSrc = useMemo(() => {
    const fromPub = publishedFiles.slice(-3).reverse().map((file) => ['publish', 'replaced in place · owner notified', file])
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
  const [audit, setAudit] = useState(() => realAuditSrc.slice(0, 4).map((e, i) => ({ e, id: -i })))
  const auditNext = useRef(1)

  // When decisions or published files change, refresh the visible audit trail.
  useEffect(() => {
    const decided = files.filter((f) => decisions[f.file])
    if (!decided.length && !publishedFiles.length) return
    setAudit(realAuditSrc.slice(0, 4).map((e, i) => ({ e, id: -(i + 100) })))
  }, [decisions, publishedFiles]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (SIM) return
    getSchedule().then((s) => {
      setSchedNext(s.next_at)
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
              <h3 style={{ margin: '0 0 8px' }}>Scan triggers &amp; schedule <span className="muted" style={{ fontWeight: 400 }}>· how the agent decides when to scan</span></h3>
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
                <div className="ctlcol">
                  <div className="ctlsub">Scheduled sweeps <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: 0.4, color: '#3B6D11', background: '#E7F0DC', border: '1px solid #C9E0B0', borderRadius: 4, padding: '1px 5px', marginLeft: 6, verticalAlign: 'middle' }}>LIVE</span></div>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Re-scans your source on this cadence (background, via the service account) and attributes the scan to you.</div>
                  <div className="seg">
                    {['live', 'hourly', 'daily', 'weekly', 'off'].map((v) => {
                      const isActive = watch.length > 0 && cadCount(v) === watch.length
                      return (
                        <button key={v} className="segbtn"
                          style={isActive ? { background: '#185FA5', color: '#fff', borderColor: '#185FA5' } : {}}
                          onClick={() => setAllCad(v)}>{v}</button>
                      )
                    })}
                  </div>
                  <div className="cadsummary">
                    {['live', 'hourly', 'daily', 'weekly', 'off'].map((v) => cadCount(v) ? <span key={v} className="cadpill">{cadCount(v)} {v}</span> : null)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      <ComplianceDigest run={run} />

      <QueuePanel />

      <RegressionRadar run={run} scanList={scanList} />

      <section className="panel" style={{ marginBottom: 14 }}>
        <div className="proghd">
          <div>
            <b>Remediation program &mdash; 2026 ADA Title II Compliance</b>
            <span className="muted" style={{ marginLeft: 10, fontSize: 12 }}>Deadline: {prog.deadline} &nbsp;&middot;&nbsp; {prog.total} files in scope</span>
          </div>
          <span className="trstatchip pending" style={{ fontSize: 12 }}>
            {prog.batches.reduce((a, b) => a + b.done, 0)} / {prog.batches.reduce((a, b) => a + b.count, 0)} resolved
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
          <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>Breaches notify the document owner and surface on the executive dashboard — the agent escalates before the deadline, not after.</p>
        </section>
      )}

      <section className="panel" style={{ marginBottom: 14 }}>
        <div className="proghd">
          <h2 style={{ margin: 0 }}>Scheduled re-scans <span className="muted">· automatic re-scan of your estate</span></h2>
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
        </div>
      </section>

      <section className="panel" style={{ marginTop: 14 }} ref={evidenceRef}>
        <div className="monfeedhd">
          <h2 style={{ margin: 0 }}>Audit trail · live <span className="livedot" aria-hidden="true" /></h2>
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
