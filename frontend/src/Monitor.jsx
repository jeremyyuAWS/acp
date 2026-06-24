import { useEffect, useMemo, useRef, useState } from 'react'
import { monitoringState, sourceWatch, IDENTITY } from './sim.js'
import { prefersReducedMotion } from './a11y.js'

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

export default function Monitor({ sources = [], files = [], ratified, decisions = {}, publishedFiles = [] }) {
  const m = monitoringState(files)
  const watch = sourceWatch(sources, files)

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
  const evidenceRef = useRef(null)
  const [exporting, setExporting] = useState(false)
  const exportEvidence = async () => {
    if (exporting) return
    setExporting(true)
    try {
      const { exportEvidenceReport } = await import('./pdfReport.js')
      await exportEvidenceReport({
        org: IDENTITY.org,
        date: new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }),
        summary: `Watching ${m.watchedSources} sources and ${m.watchedDocs.toLocaleString()} documents. Re-scans ${m.cadence}; last ${m.lastRescan}, next ${m.nextRescan}. ${m.coveragePct}% re-scan coverage over 7 days, ${m.slaPct}% within SLA.`,
        metrics: [
          { label: 'Documents watched', value: m.watchedDocs.toLocaleString() },
          { label: 'Sources', value: m.watchedSources },
          { label: 'Re-scan coverage · 7d', value: m.coveragePct + '%', color: '#3B6D11' },
          { label: 'Open alerts', value: m.alerts.length, color: '#1F5FA8' },
        ],
        events: realAuditSrc.map(([action, change, document]) => ({ action, actor: ACTOR[action] || 'mova engine', change, document })),
      })
    } catch (e) { console.error('evidence export failed', e) }
    finally { setTimeout(() => setExporting(false), 600) }
  }
  const [triggers, setTriggers] = useState({ newFile: true, onEdit: true, autoRemediate: true, alertRegression: true })
  const [cad, setCad] = useState(() => Object.fromEntries(watch.map((w) => [w.id, w.cadence])))
  const setAllCad = (v) => setCad(Object.fromEntries(watch.map((w) => [w.id, v])))
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
    const combined = [...fromPub, ...fromDec]
    const pad = BASELINE_AUDIT.slice(0, Math.max(2, 4 - combined.length))
    return [...combined, ...pad].slice(0, 6)
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
    if (paused || prefersReducedMotion()) return
    const t = setInterval(() => push(POOL[next.current % POOL.length]), 4200)
    const a = setInterval(() => {
      const src = auditSrcRef.current
      setAudit((f) => [{ e: src[auditNext.current % src.length], id: auditNext.current++ }, ...f].slice(0, 6))
    }, 2600)
    return () => { clearInterval(t); clearInterval(a) }
  }, [paused]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="estatebar" style={{ marginTop: 6 }}>
        <div>
          <span className="monlive"><span className="livedot" aria-hidden="true" /> Continuous monitoring · ON</span>
          <div className="muted" style={{ marginTop: 3 }}>watching {m.watchedSources} sources · {m.watchedDocs} documents · re-scans {m.cadence} · last {m.lastRescan} · next {m.nextRescan}</div>
        </div>
        <button className={paused ? '' : 'ghost'} onClick={() => setPaused((p) => !p)}>{paused ? '▶ Resume live feed' : '⏸ Pause live feed'}</button>
      </div>

      <div className="moncards">
        <div className="moncard"><span className="muted">Documents watched</span><b>{m.watchedDocs}</b><span className="muted">{m.watchedSources} sources</span></div>
        <div className="moncard"><span className="muted">Re-scan coverage · 7d</span><b style={{ color: '#3B6D11' }}>{m.coveragePct}%</b><span className="muted">{m.slaPct}% within SLA</span></div>
        <div className="moncard"><span className="muted">New / changed · 7d</span><b>{watch.reduce((a, w) => a + w.newFiles, 0)} / {watch.reduce((a, w) => a + w.changed, 0)}</b><span className="muted">detected &amp; re-assessed</span></div>
        <div className="moncard"><span className="muted">Remediation backlog</span><b>{hrs(m.backlogMin)}</b><span className="muted">{m.autoPct}% automatic</span></div>
        <div className="moncard"><span className="muted">Open alerts · 7d</span><b style={{ color: '#1F5FA8' }}>{m.alerts.length}</b><span className="muted">drift &amp; regressions</span></div>
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
        <h2>Scan triggers &amp; schedule <span className="muted">· how the agent decides when to scan</span></h2>
        <div className="scanctl">
          <div className="ctlcol">
            <div className="ctlsub">Event-based triggers</div>
            <Toggle label="Scan new files on arrival" hint="within 1 hour of landing in a watched source" on={triggers.newFile} set={(v) => setTriggers((t) => ({ ...t, newFile: v }))} />
            <Toggle label="Re-scan on document edit" hint="detect drift the moment content changes" on={triggers.onEdit} set={(v) => setTriggers((t) => ({ ...t, onEdit: v }))} />
            <Toggle label="Auto-remediate high-confidence fixes" hint="apply + re-certify without waiting for a sweep" on={triggers.autoRemediate} set={(v) => setTriggers((t) => ({ ...t, autoRemediate: v }))} />
            <Toggle label="Alert owner on regression" hint="notify when a published doc drops > 5 points" on={triggers.alertRegression} set={(v) => setTriggers((t) => ({ ...t, alertRegression: v }))} />
          </div>
          <div className="ctlcol">
            <div className="ctlsub">Scheduled sweeps</div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Estate default — set every source at once, or override per source below.</div>
            <div className="seg">
              {['live', 'hourly', 'daily', 'weekly', 'off'].map((v) => (
                <button key={v} className={'segbtn'} onClick={() => setAllCad(v)}>{v}</button>
              ))}
            </div>
            <div className="cadsummary">
              {['live', 'hourly', 'daily', 'weekly', 'off'].map((v) => cadCount(v) ? <span key={v} className="cadpill">{cadCount(v)} {v}</span> : null)}
            </div>
          </div>
        </div>
      </section>

      <section className="panel" style={{ marginBottom: 14 }}>
        <h2>Watched sources <span className="muted">· polled continuously for new files &amp; edits</span></h2>
        <div className="watchgrid">
          {watch.map((w) => (
            <div className="watchcard" key={w.id}>
              <div className="watchtop">
                <span className="watchico" aria-hidden="true">{SRC_ICON[w.kind] || '📁'}</span>
                <div className="watchname">{w.name}<div className="muted" style={{ fontSize: 11 }}>{w.docs} docs</div></div>
                <span className="watchpulse" title="watching"><span className="livedot" aria-hidden="true" /></span>
              </div>
              <div className="watchmeta">
                <span className="muted">polled {w.polled}</span>
                <label htmlFor={`cad-${w.id}`} className="cadsel">scan
                  <select id={`cad-${w.id}`} value={cad[w.id]} onChange={(e) => setCad((c) => ({ ...c, [w.id]: e.target.value }))}>
                    {['live', 'hourly', 'daily', 'weekly', 'off'].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </label>
              </div>
              <div className="watchchips">
                {cad[w.id] === 'off' ? <span className="wchip off">paused</span> : (<>
                  {w.newFiles ? <span className="wchip new">+{w.newFiles} new</span> : null}
                  {w.changed ? <span className="wchip chg">{w.changed} changed</span> : null}
                  {!w.newFiles && !w.changed ? <span className="wchip ok">in sync</span> : null}
                </>)}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="monsplit">
        <section className="panel">
          <div className="monfeedhd">
            <h2 style={{ margin: 0 }}>Live monitoring feed <span className="livedot" aria-hidden="true" /></h2>
            <div className="simbtns">
              <button className="ghost small" onClick={() => push(POOL[0])}>＋ Simulate new file</button>
              <button className="ghost small" onClick={() => push(POOL[2])}>✎ Simulate an edit</button>
            </div>
          </div>
          <div className="monfeed" style={{ marginTop: 10 }} role="log" aria-live="polite" aria-label="Live monitoring feed">
            {events.map((e) => {
              const [glyph, fg, bg, label] = KIND[e.kind] || KIND.clean
              return (
                <div className="monrow" key={e.id}>
                  <span className="monicon" style={{ color: fg, background: bg }} aria-hidden="true">{glyph}</span>
                  <div className="monmain">
                    <div>{e.text}</div>
                    <div className="muted" style={{ fontSize: 12 }}><span className="evkind" style={{ color: fg }}>{label}</span> · {e.src} · <span className="fname">{e.doc}</span> · {e.when}</div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <div>
          <section className="panel" style={{ marginBottom: 14 }}>
            <h2>Scheduled re-scans</h2>
            <div className="schedlist">
              {watch.slice(0, 6).map((w) => (
                <div className="schedrow" key={w.id}>
                  <span className="schedname">{w.name}</span>
                  <span className="schedcad muted">{w.cadence}</span>
                  <span className="schednext">{w.next}</span>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2>Active monitoring rules</h2>
            <ul className="monrules">
              {m.rules.map((r) => <li key={r}><span className="ruledot" aria-hidden="true" />{r}</li>)}
            </ul>
          </section>
        </div>
      </div>

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
        </div>
        <p className="muted" style={{ marginTop: 10 }}>Immutable who / when / what / which-engine log — your ADA &amp; EAA evidence trail.</p>
      </section>
    </>
  )
}
