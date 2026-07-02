import { useState, useEffect, Fragment } from 'react'
import Drawer from './Drawer.jsx'
import Tag from './Tag.jsx'
import { PRI_COLOR } from './ontology.js'
import { baFor, scOf, remediateHtml } from './BeforeAfter.jsx'
import { allRules, PLAIN_NAMES } from './rules/index.js'
import { explainFinding, getFileContent, uploadToDrive, markRemediated, remediateScan, getQueueJob, queueHitlReview, getFileRemediationState, downloadRemediated } from './api.js'
import { TraceChip } from './Transparency.jsx'

// Prescriptive-action styling, shared with the Discover inventory.
// Distinct hue per action so a long list scans at a glance. The human-touch
// actions form an intuitive escalation — blue (light approve) → amber (evaluate)
// → red (rebuild) — while no-human actions sit in the green/teal/slate family.
export const REC_STYLE = {
  auto: ['Auto-remediate', '#E3F1D8', '#2E6B0E', '⚡'],
  assisted: ['Remediate + review', '#E2EDFB', '#1F5FA8', '✎'],
  review: ['Human review', '#FBEBCB', '#8A5A00', '◐'],
  archive: ['Archive', '#ECEEF1', '#475569', '📦'],
  keep: ['Keep · monitor', '#D8F0EA', '#176B5B', '✓'],
  manual: ['Manual rebuild', '#E2EDFB', '#1F5FA8', '⚠'],
}
export const fmtEffort = (m) => m == null ? '—' : m === 0 ? 'no work' : m >= 90 ? `~${(m / 60).toFixed(1)} hrs` : `~${Math.round(m)} min`
const MODE_LABEL = { auto: 'fully automatic', assisted: 'AI + human review', manual: 'manual', monitor: 'monitor only' }

// Single-file remediation narration — mirrors the real pipeline order in
// api/handlers.py's _remediate_file: deterministic fix -> Blob (primary, must-succeed)
// -> Drive mirror (best-effort) -> record + re-verify. Staged by elapsed progress since
// the backend doesn't expose per-substep granularity for a single-file job.
const REM_STAGE_LINES = [
  'Applying deterministic fixes (alt text, headings, language)…',
  'Writing the fixed copy to Blob storage…',
  'Mirroring to Drive (best-effort)…',
  'Verifying the fix and updating records…',
]
const remStageLine = (pct) => REM_STAGE_LINES[Math.min(REM_STAGE_LINES.length - 1, Math.floor(pct / (100 / REM_STAGE_LINES.length)))]

// Where the document actually lives — so a reviewer can open it to remediate manually,
// or open a superseded doc to compare/replace. In the demo the link opens the source
// system; in production it deep-links straight to the file.
export const SOURCE_URL = {
  'SharePoint': 'https://www.office.com/launch/sharepoint', 'Google Drive': 'https://drive.google.com/drive/my-drive',
  'Box': 'https://app.box.com/folder/0', 'Confluence': 'https://www.atlassian.com/wiki', 'Website / CMS': null,
}
export function FileLocation({ file }) {
  const url = SOURCE_URL[file.sourceName]
  return (
    <div className="floc">
      <div className="flocpath"><span className="muted">location · </span>{file.sourceName || 'Source'} <span className="muted">›</span> {file.dept || 'Unfiled'} <span className="muted">›</span> <b>{file.file}</b></div>
      {url
        ? <a className="ghost small flocbtn" href={url} target="_blank" rel="noopener noreferrer">↗ Open in {file.sourceName}</a>
        : <span className="flocbtn muted" style={{ fontSize: 12 }}>public web page · open in your CMS</span>}
      {file.superseded && <div className="flocsuper">⚠ A <b>newer version</b> of this document exists — open the source to compare or replace the superseded copy.</div>}
    </div>
  )
}

const CRIT = {
  SC_1_1_1: '1.1.1 non-text content', SC_1_3_1: '1.3.1 info & relationships',
  SC_1_3_2: '1.3.2 meaningful sequence', SC_2_1_1: '2.1.1 keyboard',
  SC_2_4_2: '2.4.2 page titled', SC_2_4_4: '2.4.4 link purpose',
  SC_3_1_1: '3.1.1 language of page', SC_1_4_3: '1.4.3 contrast',
  SC_1_2_1: '1.2.1 audio/video transcript', SC_1_2_2: '1.2.2 captions',
  SC_1_2_3: '1.2.3 audio description / alt', SC_1_2_5: '1.2.5 audio description',
  SC_1_4_6: '1.4.6 contrast (enhanced)', SC_2_4_9: '2.4.9 link purpose (link only)',
}
export const critLabel = (w) => CRIT[w] ?? (w || '').replace(/^SC_/, '').replace(/_/g, '.')
const SEV = {
  CRITICAL: ['#E2EDFB', '#1F5FA8'], SERIOUS: ['#E6EFFB', '#2A5E9E'],
  MODERATE: ['#FAEEDA', '#854F0B'], MINOR: ['#F1EFE8', '#5F5E5A'],
}
const SEV_LEGEND = [
  ['critical', '#1F5FA8', '#E2EDFB', 'Completely blocks a group of users — e.g. an unlabelled image or a keyboard trap. Almost always WCAG Level A.'],
  ['serious', '#2A5E9E', '#E6EFFB', 'A major barrier that’s hard to work around — e.g. missing table headers or an empty document title.'],
  ['moderate', '#854F0B', '#FAEEDA', 'Noticeable difficulty, but the content is still reachable — e.g. wrong reading order or undeclared language.'],
  ['minor', '#5F5E5A', '#F1EFE8', 'A minor annoyance or best-practice gap — e.g. unclear worksheet names.'],
]
export const statusOf = (f) => (f.status === 'error' ? 'unanalysable' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'certifiable' : 'issues')
export const STATUS_BADGE = {
  certifiable: ['#E7F0DC', '#3B6D11'], issues: ['#FAEEDA', '#854F0B'],
  uncertain: ['#E6EFFB', '#2A5E9E'], unanalysable: ['#EEEDEA', '#5F5E5A'],
}

// Retention/lifecycle recommendation (step 3 · Retain / Archive / Delete) — based
// purely on metadata + risk flags, NOT on accessibility findings (that's Assess).
export function retentionOf(f) {
  if (f.locked) return { label: 'Could not open', bg: '#EEEDEA', fg: '#5F5E5A', why: `${f.openIssue || 'could not open'} — provide credentials or an accessible export so this document can be classified and assessed.` }
  if ((f.tags || []).includes('legal-hold')) return { label: 'Retain · legal hold', bg: '#FAEEDA', fg: '#854F0B', why: 'Under legal hold — must be retained regardless of age or usage.' }
  if (f.superseded) return { label: 'Archive', bg: '#EEEDFE', fg: '#3C3489', why: 'A newer version exists — archive to shrink the audited estate.' }
  if (f.ageDays >= 540 && f.views90d < 60) return { label: 'Archive candidate', bg: '#EEEDFE', fg: '#3C3489', why: `Last edited ${f.modifiedAge} with ${f.views90d} views/90d — low value to keep live.` }
  return { label: 'Keep', bg: '#E7F0DC', fg: '#3B6D11', why: 'Active and in use — keep in the live estate.' }
}

const STEPS = ['Discover', 'Classify', 'Retain', 'Assess', 'Risk score', 'Remediate', 'Human review', 'Re-validate', 'Publish', 'Monitor']
function journeyStates(st, remNow) {
  if (st === 'unanalysable') return ['done', 'done', 'done', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked']
  const base = ['done', 'done', 'done', 'done', 'done']
  if (st === 'certifiable') return [...base, 'remediated', 'reviewed', 'done', 'proj', 'proj']
  // `st` is derived from the file prop, which the parent doesn't refresh after a
  // remediate-now run completes -- so without this, the journey stays stuck on
  // "Remediate · in progress" even once the job is done. remNow is this component's
  // own live state for that run, so it's the one source of truth we DO have fresh.
  if (remNow?.done) return [...base, 'remediated', 'proj', 'proj', 'proj', 'proj']
  return [...base, 'current', 'proj', 'proj', 'proj', 'proj'] // issues / uncertain
}
const STATE = {
  done:       ['✓', '#3B6D11', '#E7F0DC'],
  remediated: ['✓', '#3B6D11', '#E7F0DC'],
  reviewed:   ['✓', '#3B6D11', '#E7F0DC'],
  current:    ['●', '#854F0B', '#FAEEDA'],
  proj:       ['◯', '#716B76', '#f1eff4'],
  blocked:    ['✕', '#1F5FA8', '#E2EDFB'],
  skip:       ['–', '#716B76', '#f1eff4'],
}
const STATE_NOTE = {
  proj: 'projected', skip: 'not needed', blocked: 'blocked', current: 'in progress',
  remediated: 'auto-remediated', reviewed: 'no findings — cleared',
}

export default function FileDrawer({ file, onClose, context = 'full', overrideOwner = null, delegatedFrom = null, decision = null, aiEnabled = true, scanId = null, readOnly = false }) {
  const [explanations, setExplanations] = useState({})
  const fetchExplanation = (ruleId) => {
    if (!scanId || explanations[ruleId]) return
    setExplanations((e) => ({ ...e, [ruleId]: { loading: true } }))
    explainFinding(scanId, file.file, ruleId)
      .then((res) => setExplanations((e) => ({ ...e, [ruleId]: res })))
      .catch(() => setExplanations((e) => ({ ...e, [ruleId]: { error: true } })))
  }

  const [driveRem, setDriveRem] = useState(null) // {status, url, error}
  const remediateAndSaveToDrive = async () => {
    setDriveRem({ status: 'loading' })
    try {
      const buf = await getFileContent(scanId, file.file)
      if (!buf) { setDriveRem({ status: 'error', error: 'Could not fetch file from Drive' }); return }
      const text = new TextDecoder().decode(buf)
      const result = remediateHtml(text, { aiEnabled })
      if (!result) { setDriveRem({ status: 'error', error: 'HTML parse failed' }); return }
      const blob = new Blob([result.html], { type: 'text/html' })
      const certDate = new Date().toISOString().split('T')[0]
      const certName = file.file.replace(/\.html?$/i, '') + `_a11y-certified-${certDate}.html`
      const up = await uploadToDrive(scanId, certName, blob, 'text/html')
      await markRemediated(scanId, file.file).catch(() => {})
      setDriveRem({ status: 'done', url: up.url, name: certName })
    } catch (e) {
      setDriveRem({ status: 'error', error: e.message || 'Upload failed' })
    }
  }

  // One-click remediation right from the file detail, for any file type — not just the
  // HTML client-side path above (drive-rem-panel, Remediate-tab only). Goes through the
  // same async remediate_file job the bulk Remediate flow uses (server-side HTML/PDF/
  // Office remediators — ADR 0005 step 4), scoped to just this one file, so a reviewer
  // looking at a single document's recommendation can see it acted on immediately instead
  // of having to switch to Remediate and run/filter the whole-estate flow.
  const [remNow, setRemNow] = useState(null) // null | 'queued' | 'error' | {done: true, url?}
  const REM_POLL_MAX = 60 // ceiling on polling the REAL job — no longer a fake timer
  const [remProgress, setRemProgress] = useState(0)
  const [remStage, setRemStage] = useState('')
  const [hitlQueued, setHitlQueued] = useState(false)
  const remediateNow = async () => {
    if (!scanId || remNow === 'queued') return
    setRemNow('queued'); setRemProgress(4); setRemStage('Queued — waiting for a worker…')
    // An AI-assisted fix still needs human sign-off — remediate-now must not let a
    // file skip the review the batch flow would route it through. The server-side
    // auto-queue is idempotent, so repeat clicks never duplicate queue items.
    const finish = () => {
      if (['assisted', 'review'].includes(file.rec?.action) || (file.issues || []).some((i) => i.auto === false)) {
        queueHitlReview(scanId).catch(() => {})
        setHitlQueued(true)
      }
      setRemProgress(100); setRemNow({ done: true })
    }
    try {
      const res = await remediateScan(scanId, [file.file])
      const jid = res?.job_ids?.[0]
      if (!jid) {
        // Nothing eligible for the server-side queue (no findings / no Drive id) —
        // record the remediation directly, as the old flow did.
        await markRemediated(scanId, file.file).catch(() => {})
        finish(); return
      }
      // Poll the actual job (queued → running → done/dead): the bar only advances
      // while a worker is really on it, and completion means the fix really landed —
      // the old version swept a 30s timer and declared success unconditionally.
      let running = 0
      for (let i = 0; i < REM_POLL_MAX; i++) {
        await new Promise((r) => setTimeout(r, 1000))
        const jb = await getQueueJob(jid).catch(() => null)
        if (jb?.status === 'done') { finish(); return }
        if (jb?.status === 'dead') { setRemNow('error'); return }
        if (jb?.status === 'running') {
          running += 1
          const pct = Math.min(90, 10 + running * 8)
          setRemProgress(pct); setRemStage(remStageLine(pct))
        }
      }
      setRemNow('error')   // still not done after the ceiling — honest failure + retry
    } catch (e) {
      setRemNow('error')
    }
  }

  // ADR 0003 Phase 2: which specific WCAG rules were actually auto-fixed (vs. always
  // having passed) — so the coverage table below can say "pass — remediated" instead of
  // a plain "pass" for a criterion that only passes because remediation fixed it.
  // Re-fetches once remNow?.done flips true, so a same-session fix shows up immediately.
  const [remediatedRuleIds, setRemediatedRuleIds] = useState(new Set())
  useEffect(() => {
    if (!scanId || !file?.file) { setRemediatedRuleIds(new Set()); return }
    let cancelled = false
    getFileRemediationState(scanId, file.file)
      .then((rows) => { if (!cancelled) setRemediatedRuleIds(new Set((rows || []).filter((r) => r.state === 'complete').map((r) => r.rule_id))) })
      .catch(() => { if (!cancelled) setRemediatedRuleIds(new Set()) })
    return () => { cancelled = true }
  }, [scanId, file?.file, remNow?.done])

  if (!file) return null
  const st = statusOf(file)
  const [sbg, sfg] = STATUS_BADGE[st]
  const issues = file.issues || []
  const byCrit = {}
  issues.forEach((i) => { byCrit[i.wcag] = (byCrit[i.wcag] || 0) + 1 })
  const states = journeyStates(st, remNow)
  const isRemediated = !!(file.acp_stamped || file.remediated_at || file.drive_write_url || remNow?.done)

  const hasAnyMeta = file.modifiedAge || file.lastAccessed || file.views90d != null || file.sizeKB || file.duration || file.pages || file.sheets || file.owner || overrideOwner
  const metaBlock = (
    <>
      <h4 className="drawerh">Document metadata</h4>
      <div className="metagrid">
        <div><span className="muted">File name</span><b style={{ wordBreak: 'break-all' }}>{file.file || '—'}</b></div>
        <div><span className="muted">Type</span><b>{(file.type || file.engine || '').toUpperCase() || '—'}</b></div>
        <div><span className="muted">Source</span><b>{file.sourceName || '—'}</b></div>
        <div><span className="muted">Department</span><b>{file.department || file.dept || '—'}</b></div>
        {hasAnyMeta ? (<>
          <div><span className="muted">Last modified</span><b>{file.modifiedAge || '—'}</b></div>
          <div><span className="muted">Last accessed</span><b>{file.lastAccessed || '—'}</b></div>
          <div><span className="muted">Views · 90d</span><b>{file.views90d != null ? file.views90d.toLocaleString() : '—'}</b></div>
          <div><span className="muted">Size</span><b>{file.sizeKB ? (file.sizeKB >= 1024 ? `${(file.sizeKB / 1024).toFixed(1)} MB` : `${file.sizeKB} KB`) : '—'}</b></div>
          <div><span className="muted">{file.duration ? 'Duration' : file.sheets ? 'Sheets' : 'Pages'}</span><b>{file.duration || file.pages || file.sheets || '—'}</b></div>
          <div><span className="muted">Owner</span><b>{overrideOwner || file.owner || '—'}{delegatedFrom && <span className="badge" style={{ marginLeft: 6, background: '#E7F0DC', color: '#3B6D11', fontSize: 10, fontWeight: 400 }}>delegated from {delegatedFrom}</span>}</b></div>
        </>) : (
          <div style={{ gridColumn: '1 / -1' }}><span className="muted" style={{ fontSize: 12 }}>Extended metadata (modified date, views, owner) not returned by this source connector.</span></div>
        )}
      </div>
    </>
  )
  const ontBlock = file.ont && (
    <>
      <h4 className="drawerh">Business classification · your ontology</h4>
      <div className="ontdrawer">
        <span className="pritag" style={{ background: PRI_COLOR[file.ont.priority][1], color: PRI_COLOR[file.ont.priority][0] }}>{file.ont.priority}</span>
        {file.ont.label && <span className="ontlabelpill" style={{ color: file.ont.label.color, background: file.ont.label.color + '22' }}>{file.ont.label.name}</span>}
        {file.ont.sla && <span className="muted">{file.ont.sla}-day SLA</span>}
        <div className="muted ontdrawerwhy">Matched rule: {file.ont.rule.name} · weighted business risk {Math.round(file.ont.score)}</div>
      </div>
    </>
  )
  const STATUS_TAGS = new Set(['certified', 'needs-review', 'auto-fixable', 'remediation-queued'])
  const shownTags = context === 'discover' ? (file.tags || []).filter((t) => !STATUS_TAGS.has(t)) : (file.tags || [])
  const provBlock = file.acp_stamped ? (
    <div style={{ margin: '0 0 12px', padding: '8px 12px', borderRadius: 8, background: '#E7F0DC',
                  border: '1px solid #C5DBA8', fontSize: 12.5, color: '#2F5310',
                  display: 'flex', alignItems: 'center', gap: 8 }}>
      <span aria-hidden="true">🛡️</span>
      <span>Remediated by <b>Mova.io ACP</b>{file.acp_stamped !== 'yes' ? ` · ${file.acp_stamped}` : ''} — carries an ACP provenance stamp.</span>
    </div>
  ) : null

  const tagBlock = shownTags.length > 0 && (
    <>
      <h4 className="drawerh">{context === 'discover' ? 'Classification · auto-assigned by agent' : 'Tags · auto-assigned by agent'}</h4>
      <div className="taglist">{shownTags.map((t) => <Tag key={t} t={t} />)}</div>
    </>
  )

  // Discover (steps 1–3): inventory · classify · retain — NO accessibility assessment.
  if (context === 'discover') {
    const ret = retentionOf(file)
    return (
      <Drawer title={file.file} subtitle={`${file.sourceName ? `${file.sourceName} · ${file.dept || file.department || '—'} · ` : ''}${(file.type || '').toUpperCase()}`} onClose={onClose}>
        {file.locked && <div className="lockbanner">🔒 Could not open — <b>{file.openIssue}</b>. Discovered from its metadata, but the content couldn’t be read.</div>}
        {provBlock}
        {scanId && <div style={{ margin: '0 0 12px' }}><TraceChip scanId={scanId} kind="file" file={file.file} label="View this document's trace" /></div>}
        {tagBlock}
        {ontBlock}
        {metaBlock}
        <FileLocation file={file} />
        <h4 className="drawerh">Retention recommendation</h4>
        <div className="reccard" style={{ borderColor: ret.fg + '55' }}>
          <span className="recbadge" style={{ background: ret.bg, color: ret.fg }}>{ret.label}</span>
          <p className="recwhy" style={{ marginBottom: 0, marginTop: 9 }}>{ret.why}</p>
        </div>
        <p className="muted" style={{ marginTop: 14, fontSize: 12 }}>Accessibility findings &amp; score are evaluated in the Assess step.</p>
      </Drawer>
    )
  }

  return (
    <Drawer title={file.file} subtitle={`${file.sourceName ? `${file.sourceName} · ${file.dept || file.department || '—'} · ` : ''}${file.engine}`} onClose={onClose}>
      {provBlock}
      {/* This document's full Discover→Assess→Remediate trace, all on one Langfuse trace
          (file-centric tracing — lf.file_trace). Needs scanId, which not every FileDrawer
          caller passes yet (Discover/Integrations/KnowledgeGraph don't) — renders nothing
          when absent, same as before this existed. */}
      {scanId && <div style={{ margin: '0 0 12px' }}><TraceChip scanId={scanId} kind="file" file={file.file} label="View this document's trace" /></div>}
      <div className="drawerstats">
        <span className="badge" style={{ background: sbg, color: sfg }}>{st}</span>
        <span className="drawerscore">{file.score === null ? 'n/a' : `${st === 'uncertain' ? '≤' : ''}${file.score}`}<span className="muted"> / 100</span></span>
        {st === 'uncertain' && <span className="muted">{file.skipped_rules} rule(s) skipped — score is an upper bound</span>}
      </div>

      {ontBlock}

      {file.rec && (() => {
        const r = file.rec; const [label, bg, fg, icon] = REC_STYLE[r.action] || REC_STYLE.review
        return (
          <div className="reccard" style={{ borderColor: fg + '55' }}>
            <div className="recheadrow">
              <span className="recbadge" style={{ background: bg, color: fg }}>{icon} {label}</span>
              <span className="receta">{fmtEffort(r.etaMin)}</span>
            </div>
            <p className="recwhy">{r.rationale}</p>
            <div className="recmeta">
              <span><b>{MODE_LABEL[r.mode] || r.mode}</b><span className="muted"> mode</span></span>
              {r.confidence != null && <span><b>{r.confidence}%</b><span className="muted"> confidence</span></span>}
            </div>
            {scanId && r.mode !== 'manual' && r.mode !== 'monitor' && (
              <div style={{ marginTop: 10 }}>
                {remNow === null && (
                  <button className="ctago" disabled={readOnly} title={readOnly ? 'Time-travel replay — switch to the latest scan to remediate' : undefined} onClick={remediateNow}>⚡ Remediate this file now</button>
                )}
                {remNow === 'queued' && (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 7, flex: '0 0 auto' }}>
                        <span className="spinner" /> Remediating…
                      </span>
                      <span className="track" style={{ width: 120 }}>
                        <i style={{ width: `${remProgress}%`, background: 'var(--plum)', transition: 'width .4s linear' }} />
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 5 }} role="status" aria-live="polite">
                      {remStage || remStageLine(remProgress)}
                    </div>
                  </div>
                )}
                {remNow?.done && (
                  <span className="dectag ok" style={{ fontSize: 12, padding: '3px 10px' }}>✓ Remediated — fixed copy stored{hitlQueued ? ' · queued for human review' : ''}</span>
                )}
                {(remNow?.done || file.remediated_at) && (
                  <button className="ghost small" style={{ marginLeft: 8 }} disabled={remNow === 'queued'}
                          title={remNow === 'queued' ? 'Available once this remediation finishes' : 'Download the fixed copy (Blob primary, Drive-mirror fallback)'}
                          onClick={() => downloadRemediated(scanId, file.file)}>
                    ⤓ Download fixed copy
                  </button>
                )}
                {remNow === 'error' && (
                  <span style={{ color: '#B43A2A' }}>
                    Couldn't remediate this file — <button className="ghost small" onClick={remediateNow}>try again</button>
                  </span>
                )}
              </div>
            )}
          </div>
        )
      })()}

      {metaBlock}
      <FileLocation file={file} />

      {tagBlock}

      <h4 className="drawerh">Findings {issues.length > 0 && <span className="muted">({issues.length})</span>}</h4>
      {issues.length === 0 ? (
        <p className="muted">{st === 'unanalysable' ? 'Could not analyse — file unreadable.' : 'No findings — clean.'}</p>
      ) : (
        <>
          <div className="findings">
            {issues.map((i, n) => {
              const [bg, fg] = SEV[i.severity] || SEV.MINOR
              return (
                <div className="finding" key={n}>
                  <span className="badge" style={{ background: bg, color: fg }}>{(i.severity || '').toLowerCase()}</span>
                  <div className="findingmain">
                    <div className="findingtop">{critLabel(i.wcag)}{i.level && <span className="lvlchip">Level {i.level}</span>}{isRemediated && <span className="dectag ok">✓ remediated</span>}</div>
                    {i.detail && <div className="findingdetail">{i.detail}</div>}
                    {i.impact && <div className="muted findingimpact">{i.impact}</div>}
                    {i.fix && <div className="findingfix"><span className={i.auto ? 'fixauto' : 'fixreview'}>{i.auto ? '⚡ auto-fixable' : '✎ needs review'}</span> · {i.fix}<span className="muted"> · {i.rule_id ?? i.ruleId}</span></div>}
                    {context === 'remediate' && (() => {
                      const sc = scOf(i.wcag)
                      const ba = sc ? baFor(sc, (file?.file || '').replace(/\.[^.]+$/, '')) : null
                      if (!ba) return null
                      return (
                        <div style={{ marginTop: 8 }}>
                          <div className="diffbox before" style={{ marginTop: 0 }}><span className="difftag">before</span>{ba.before}</div>
                          <div className="diffbox after" style={{ marginTop: 4 }}><span className="difftag">after</span>{ba.after}</div>
                        </div>
                      )
                    })()}
                  </div>
                </div>
              )
            })}
          </div>
          <details className="sevhelp">
            <summary>How is severity classified?</summary>
            <p className="muted" style={{ margin: '8px 0' }}>Severity reflects <b>user impact × how many users are affected × the WCAG level</b> (A is the most fundamental). It follows the axe-core / engine impact model — independent of which rule fired.</p>
            {SEV_LEGEND.map(([name, fg, bg, desc]) => (
              <div className="sevrow" key={name}>
                <span className="badge" style={{ background: bg, color: fg, flex: '0 0 auto' }}>{name}</span>
                <span className="muted">{desc}</span>
              </div>
            ))}
          </details>
        </>
      )}

      {Object.keys(byCrit).length > 0 && (
        <>
          <h4 className="drawerh">WCAG criteria failing</h4>
          <div className="critlist">
            {Object.entries(byCrit).sort((a, b) => b[1] - a[1]).map(([w, n]) => (
              <div className="critlistrow" key={w}><span>{critLabel(w)}</span><b>{n}</b></div>
            ))}
          </div>
        </>
      )}

      {context === 'remediate' && /\.html?$/i.test(file.file || '') && scanId && (
        <div className="drive-rem-panel">
          <b>Remediate HTML → Google Drive</b>
          <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>fetches original from Drive, applies auto-fixes, saves to Remediated/</span>
          <div style={{ marginTop: 8 }}>
            {!driveRem && (
              <button className="ghost small" onClick={remediateAndSaveToDrive}>☁ Remediate &amp; save to Drive</button>
            )}
            {driveRem?.status === 'loading' && <span className="muted" style={{ fontSize: 12 }}>⏳ fetching, fixing, uploading…</span>}
            {driveRem?.status === 'done' && (
              <span style={{ fontSize: 12 }}>
                ✓ Saved → {driveRem.url
                  ? <a href={driveRem.url} target="_blank" rel="noreferrer">Drive/Remediated/{driveRem.name}</a>
                  : `Drive/Remediated/${driveRem.name}`}
                {' '}<button className="explain-btn" onClick={() => setDriveRem(null)}>redo</button>
              </span>
            )}
            {driveRem?.status === 'error' && (
              <span style={{ fontSize: 12, color: 'var(--red, #c0392b)' }}>
                ✕ {driveRem.error}{' '}
                <button className="explain-btn" onClick={() => setDriveRem(null)}>retry</button>
              </span>
            )}
          </div>
        </div>
      )}

      {(() => {
        // Cross-reference the rule manifest against this file's actual issues to
        // produce a per-rule outcome row: PASS (no findings) / FAIL (N findings) /
        // SKIP (rule not applicable to this file type). Was gated to context==='remediate'
        // only — but allRules is a static import (./rules/index.js, no remediate-specific
        // state) and aiEnabled defaults to true, so there was no real dependency forcing
        // this to one context. The Assess tab (context='full', the default) is arguably
        // where you want this MOST — it's exactly where "why did this score what it did,
        // per WCAG rule" is the question being asked.
        const isHtmlFile = /\.html?$/i.test(file.file || '')
        const issuesBySc = {}
        ;(file.issues || []).forEach((i) => {
          const sc = scOf(i.wcag)
          if (sc) issuesBySc[sc] = (issuesBySc[sc] || 0) + 1
        })
        const rows = allRules.map((mod) => {
          const { id, name, level, fixMode } = mod.meta
          const effectiveFixMode = !aiEnabled && fixMode === 'ai-assisted' ? 'human-only' : fixMode
          const count = issuesBySc[id] || 0
          const outcome = !isHtmlFile && id !== '1.1.1' && id !== '1.3.1' && id !== '2.4.2' && id !== '3.1.1'
            ? 'SKIP'
            : count > 0 ? 'FAIL' : 'PASS'
          return { id, name, plain: PLAIN_NAMES[id] || name, level, fixMode: effectiveFixMode, outcome, count }
        })
        const passCount = rows.filter((r) => r.outcome === 'PASS').length
        const failCount = rows.filter((r) => r.outcome === 'FAIL').length
        const skipCount = rows.filter((r) => r.outcome === 'SKIP').length
        return (
          <details className="covmanifest" open={failCount > 0}>
            <summary className="covmanifest-sum">
              Rule coverage · {allRules.length} checks
              <span className="covstat pass">{passCount} pass</span>
              {failCount > 0 && <span className="covstat fail">{failCount} fail</span>}
              {skipCount > 0 && <span className="covstat skip">{skipCount} N/A</span>}
            </summary>
            <div className="covmanifest-note muted">HTML files are checked against every rule; PDF/Office engines check the subset they can evaluate. <b>N/A</b> = this criterion isn’t covered by the {file.engine || 'engine'} for this file type — it’s not an error or a failure.</div>
            <table className="covtable">
              <thead><tr><th>SC</th><th>Name</th><th>Lvl</th><th>Fix</th><th>Outcome</th></tr></thead>
              <tbody>
                {rows.map((r) => {
                  const exp = explanations[r.id]
                  return (
                    <Fragment key={r.id}>
                      <tr className={`covrow ${r.outcome.toLowerCase()}`}>
                        <td className="covsc">{r.id}</td>
                        <td>{r.plain}<div className="muted" style={{ fontSize: 11 }}>{r.name}</div></td>
                        <td className="muted">{r.level}</td>
                        <td className="muted">{r.fixMode === 'auto' ? '⚡ auto' : r.fixMode === 'ai-assisted' ? '✎ AI' : '✋ human'}</td>
                        <td className={`covoutcome ${r.outcome.toLowerCase()}`}
                          title={r.outcome === 'SKIP' ? `N/A — this criterion isn’t checked by the ${file.engine || 'engine'} for this file type (not an error)` : undefined}>
                          {r.outcome === 'PASS' ? '✓' : r.outcome === 'FAIL' ? `✕ ${r.count}` : 'N/A'}
                          <span className="covouttxt">{r.outcome === 'PASS' ? (remediatedRuleIds.has(r.id) ? 'pass — remediated' : 'pass') : r.outcome === 'FAIL' ? 'fail' : 'not applicable'}</span>
                          {r.outcome === 'FAIL' && scanId && !exp && (
                            <button className="explain-btn" onClick={() => fetchExplanation(r.id)} title="Get AI explanation">Why?</button>
                          )}
                        </td>
                      </tr>
                      {r.outcome === 'FAIL' && exp && (
                        <tr className="covrow-explain">
                          <td colSpan={5}>
                            {exp.loading && <span className="explain-loading">⏳ thinking…</span>}
                            {exp.error && <span className="explain-error muted">AI explanation unavailable — is Ollama running?</span>}
                            {exp.why && (
                              <div className="explain-body">
                                <div className="explain-why"><b>Why it matters:</b> {exp.why}</div>
                                {exp.fix && <div className="explain-fix"><b>Fix:</b> <code>{exp.fix}</code></div>}
                                <span className="explain-model muted">{exp.model}</span>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </details>
        )
      })()}

      <h4 className="drawerh">Document journey</h4>
      <ol className="journeyline">
        {STEPS.map((label, i) => {
          const [glyph, color, bg] = STATE[states[i]]
          const note = STATE_NOTE[states[i]]
          return (
            <li className="jrow" key={label}>
              <span className="jdot" style={{ color, background: bg }} aria-hidden="true">{glyph}</span>
              <span className="jlabel">{label}{i === 3 && file.score !== null ? ` · ${st === 'uncertain' ? '≤' : ''}${file.score}` : ''}</span>
              {note && <span className="muted jnote">{note}</span>}
            </li>
          )
        })}
      </ol>
    </Drawer>
  )
}
