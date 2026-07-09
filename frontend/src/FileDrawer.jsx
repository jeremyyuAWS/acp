import { useState, useEffect, Fragment } from 'react'
import Drawer from './Drawer.jsx'
import Tag from './Tag.jsx'
import { PRI_COLOR } from './ontology.js'
import { baFor, scOf, remediateHtml } from './BeforeAfter.jsx'
import { allRules, PLAIN_NAMES } from './rules/index.js'
import { explainFinding, getFileContent, uploadToDrive, markRemediated, remediateScan, getQueueJob, queueHitlReview, queueHitlVerify, getFileRemediationState, downloadRemediated, getRules, getRubric, getConfig } from './api.js'
import { WCAG } from './wcagCatalog.js'
import { confidenceForFinding, confidenceForCoverage, confClass } from './confidence.js'
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
// The WCAG rules the server-side remediator for each format actually fixes
// deterministically (mirrors remediate_pdf = language+title, remediate_office
// = +alt-text). Used to name the real rule under the progress bar as it's
// applied. HTML runs the broad rule-module set, so it keeps the generic stages.
// Every rule named here is one the engine genuinely fixes for this file — a
// HITL-deferred finding (contrast, link purpose) is never claimed as 'fixing'.
const REM_AUTOFIX_SC_BY_TYPE = { pdf: ['3.1.1', '2.4.2'], docx: ['1.1.1', '3.1.1', '2.4.2'], pptx: ['1.1.1', '3.1.1', '2.4.2', '1.4.3', '1.4.6', '1.3.2', '2.4.6'], xlsx: ['1.1.1', '3.1.1', '2.4.2', '1.4.3', '1.4.6'], html: ['3.1.1', '2.4.2', '1.3.1', '1.4.3', '1.4.6', '1.4.10', '1.4.4', '1.4.12', '1.4.2', '1.3.4'] }
const scOfWcag = (v) => ((v || '').replace(/^SC_/, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/) || [''])[0]

// Pure per-criterion coverage computation — the SAME honest PASS/FAIL/FIXED/HUMAN/
// UNCHECKED logic the on-screen WCAG coverage table below uses, extracted so the
// certification-PDF export shares it exactly rather than risk drifting from what's
// shown on screen.
function computeCoverageRows(file, { catalogRules, targetLevel, remediatedRuleIds, effectiveRemediated, aiEnabled }) {
  const ext = (file.file || '').split('.').pop().toLowerCase()
  const fmt = /^html?$/.test(ext) ? 'html' : ['pdf', 'docx', 'pptx', 'xlsx'].includes(ext) ? ext : null
  const scFromRule = (r) => r.wcag_sc || ((r.wcag || '').startsWith('SC_') ? r.wcag.slice(3).replaceAll('_', '.') : scOf(r.wcag || ''))
  const checkedSCs = fmt === 'html'
    ? new Set(allRules.map((m) => m.meta.id))
    : new Set((((catalogRules || {})[fmt]) || []).map(scFromRule).filter(Boolean))
  const isHuman = (c) => /Human/i.test(c.approach || '') || c.source === 'MDK HITL'
  const DOC_HUMAN_WHEN_UNCHECKED = new Set(['1.4.1', '1.3.5', '2.5.3', '4.1.2'])
  const fixOf = (c) => {
    if ((c.tier || '').startsWith('Tier 1')) return '⚡ auto'
    if ((c.tier || '').startsWith('Tier 2')) return aiEnabled ? '✎ AI' : '✋ human'
    return '✋ human'
  }
  const issuesBySc = {}
  ;(file.issues || []).forEach((i) => {
    const sc = scOfWcag(i.wcag)
    if (sc) issuesBySc[sc] = (issuesBySc[sc] || 0) + 1
  })
  const LEVEL_RANK = { A: 1, AA: 2, AAA: 3 }
  const targetRank = LEVEL_RANK[targetLevel] || 2
  const OUT_RANK = { FAIL: 0, FIXED: 0.5, PASS: 1, HUMAN: 2, UNCHECKED: 3, WEB: 4 }
  const inScope = WCAG.filter((c) => c.docApplies !== false && (LEVEL_RANK[c.level] || 3) <= targetRank)
  return inScope.map((c) => {
    const count = issuesBySc[c.sc] || 0
    const wasFixed = count > 0 && (remediatedRuleIds.has(c.sc)
      || (effectiveRemediated && (REM_AUTOFIX_SC_BY_TYPE[file.type] || []).includes(c.sc)))
    const outcome = wasFixed ? 'FIXED'
      : count > 0 ? 'FAIL'
      : checkedSCs.has(c.sc) ? 'PASS'
      : isHuman(c) ? 'HUMAN'
      : (DOC_HUMAN_WHEN_UNCHECKED.has(c.sc) && fmt && fmt !== 'html') ? 'HUMAN'
      : 'UNCHECKED'
    const confidence = confidenceForCoverage({ sc: c.sc, outcome, verifiedCleared: remediatedRuleIds.has(c.sc) })
    return { id: c.sc, name: c.name, plain: PLAIN_NAMES[c.sc] || c.name, level: c.level, fix: fixOf(c), outcome, count, confidence }
  }).sort((a, b) => (OUT_RANK[a.outcome] ?? 3) - (OUT_RANK[b.outcome] ?? 3))
}
// Named rules step across the first 80% of the bar; the last 20% is the
// write-to-store + re-verify stage. Client-paced (a single-file job streams no
// per-rule events) but over the file's REAL auto-fixable findings, in order.
const remStageFor = (pct, rules) => {
  if (!rules.length) return remStageLine(pct)
  if (pct >= 80) return 'Writing the fixed copy & re-verifying…'
  const r = rules[Math.min(rules.length - 1, Math.floor((pct / 80) * rules.length))]
  return `Fixing ${r.sc} ${r.name}…`
}

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
  ['critical', '#1F5FA8', '#E2EDFB', "Completely blocks a group of users — e.g. an unlabelled image or a keyboard trap. Almost always WCAG Level A."],
  ['serious', '#2A5E9E', '#E6EFFB', "A major barrier that's hard to work around — e.g. missing table headers or an empty document title."],
  ['moderate', '#854F0B', '#FAEEDA', "Noticeable difficulty, but the content is still reachable — e.g. wrong reading order or undeclared language."],
  ['minor', '#5F5E5A', '#F1EFE8', "A minor annoyance or best-practice gap — e.g. unclear worksheet names."],
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
  // Engine rule catalog (docx/pptx/xlsx/pdf groups) — tells the coverage table
  // which WCAG criteria the engine ACTUALLY evaluates for this file type, so a
  // PASS is never claimed for something that was never checked. Fetched once.
  const [catalogRules, setCatalogRules] = useState(null)
  // Conformance target (e.g. 'WCAG 2.1 AA') scopes the coverage table to the
  // level the platform is actually certifying against — AAA rows hide at AA.
  const [targetLevel, setTargetLevel] = useState('AA')
  useEffect(() => {
    let on = true
    getRules().then((r) => { if (on) setCatalogRules(r) }).catch(() => {})
    getRubric().then((r) => {
      const m = (r?.target || '').match(/\b(AAA|AA|A)\s*$/)
      if (on && m) setTargetLevel(m[1])
    }).catch(() => {})
    return () => { on = false }
  }, [])
  const fetchExplanation = (ruleId) => {
    if (!scanId || explanations[ruleId]?.loading) return   // error/stale results are retryable
    setExplanations((e) => ({ ...e, [ruleId]: { loading: true } }))
    // Bound the wait client-side too: a wedged Ollama used to leave "thinking…"
    // up for minutes with no way out. 45s covers a cold model load + generation.
    const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 45000))
    Promise.race([explainFinding(scanId, file.file, ruleId), timeout])
      .then((res) => setExplanations((e) => ({ ...e, [ruleId]: res })))
      .catch((err) => setExplanations((e) => ({ ...e, [ruleId]: { error: true, detail: err?.message } })))
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
      window.dispatchEvent(new CustomEvent('acp:file-remediated', { detail: { scanId, file: file.file } }))
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
  // Per-finding live status for the queue view: sc -> 'queued'|'fixing'|'fixed'|'review'.
  // Auto-fixable findings step queued→fixing→fixed as the job runs; findings the
  // remediator can't touch (contrast, link purpose, structure) are 'review' from the
  // outset — shown routed to a human, never claimed as being fixed.
  const [findStatus, setFindStatus] = useState({})
  const [hitlQueued, setHitlQueued] = useState(false)
  // Download the stored fixed copy. downloadRemediated() rejects on a non-2xx (e.g. the
  // 404 an ADR 0011 incremental re-scan produced for a file whose fixed copy lives under
  // an earlier scan_id) — but the bare onClick used to drop that rejection, so the button
  // silently did nothing. Await + catch so the failure is surfaced. The backend now falls
  // back across the owner's scans, so a residual error genuinely means no copy exists yet.
  const [dl, setDl] = useState(null) // null | 'loading' | { error }
  const downloadFixedCopy = async () => {
    if (dl === 'loading') return
    setDl('loading')
    try {
      await downloadRemediated(scanId, file.file)
      setDl(null)
    } catch (e) {
      setDl({ error: 'Fixed copy not available for this scan — re-remediate to refresh it.' })
    }
  }
  const remediateNow = async () => {
    if (!scanId || remNow === 'queued') return
    setRemNow('queued'); setRemProgress(4); setRemStage('Queued — waiting for a worker…')
    // The file's failing findings the server-side remediator actually fixes for this
    // format (REM_AUTOFIX_SC_BY_TYPE); everything else routes to human review.
    const failingSCs = new Set((file.issues || []).map((i) => scOfWcag(i.wcag)).filter(Boolean))
    const remRules = (REM_AUTOFIX_SC_BY_TYPE[file.type] || [])
      .filter((sc) => failingSCs.has(sc)).map((sc) => ({ sc, name: PLAIN_NAMES[sc] || sc }))
    const isAutoSC = (sc) => remRules.some((r) => r.sc === sc)
    setFindStatus(Object.fromEntries([...failingSCs].map((sc) => [sc, isAutoSC(sc) ? 'queued' : 'review'])))
    // An AI-assisted fix still needs human sign-off — remediate-now must not let a
    // file skip the review the batch flow would route it through. The server-side
    // auto-queue is idempotent, so repeat clicks never duplicate queue items.
    const finish = () => {
      if (['assisted', 'review'].includes(file.rec?.action) || (file.issues || []).some((i) => i.auto === false)) {
        queueHitlReview(scanId).catch(() => {})
      } else {
        // Fully-automatic fixes get a post-fix VERIFICATION item (user decision
        // 2026-07-02): a human spot-checks the automatic result — no unreviewed
        // fix reaches Publish on trust alone.
        queueHitlVerify(scanId, file.file).catch(() => {})
      }
      setHitlQueued(true)
      setFindStatus((prev) => { const n = { ...prev }; remRules.forEach((r) => { n[r.sc] = 'fixed' }); return n })
      setRemProgress(100); setRemNow({ done: true })
      // Announce completion app-wide (same event pattern as acp:session-expired):
      // App refetches the scan, so triage/publish/discover reflect this fix
      // without a page reload.
      window.dispatchEvent(new CustomEvent('acp:file-remediated', { detail: { scanId, file: file.file } }))
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
          setRemProgress(pct); setRemStage(remStageFor(pct, remRules))
          const activeIdx = Math.min(remRules.length - 1, Math.floor((pct / 80) * remRules.length))
          setFindStatus((prev) => { const n = { ...prev }; remRules.forEach((r, i2) => { if (n[r.sc] !== 'fixed') n[r.sc] = i2 < activeIdx ? 'fixed' : i2 === activeIdx ? 'fixing' : 'queued' }) ; return n })
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
  const [certExporting, setCertExporting] = useState(false)
  useEffect(() => {
    setDl(null)   // clear a stale download error/spinner when switching files or scans
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
  const isRemediated = !!(file.acp_stamped || file.remediated_at || file.drive_write_url || remNow?.done)
  // remediation_state can know the file is fixed before the files prop refreshes
  // (the fix ran in an earlier session / another tab): when every failing criterion
  // has a completed remediation row, the file IS remediated — the drawer must not
  // keep offering "Remediate this file now" while the coverage table below says
  // "pass — remediated".
  const allFailingFixed = issues.length > 0 && issues.every((i) => remediatedRuleIds.has(scOf(i.wcag)))
  const effectiveRemediated = isRemediated || allFailingFixed
  const states = journeyStates(st, effectiveRemediated ? { done: true } : remNow)

  const sizeKB = file.sizeKB ?? file.size_kb   // SIM uses sizeKB; real scans store size_kb
  const hasAnyMeta = file.modifiedAge || file.lastAccessed || file.views90d != null || sizeKB || file.duration || file.pages || file.sheets || file.owner || overrideOwner
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
          <div><span className="muted">Size</span><b>{sizeKB ? (sizeKB >= 1024 ? `${(sizeKB / 1024).toFixed(1)} MB` : `${sizeKB} KB`) : '—'}</b></div>
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
        {file.locked && <div className="lockbanner">🔒 Could not open — <b>{file.openIssue}</b>. Discovered from its metadata, but the content couldn't be read.</div>}
        {provBlock}
        {scanId && <div style={{ margin: '0 0 12px' }}><TraceChip scanId={scanId} kind="file" file={file.file} label="View this document's trace" refreshKey={remNow?.done ? 1 : 0} /></div>}
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
      {scanId && <div style={{ margin: '0 0 12px' }}><TraceChip scanId={scanId} kind="file" file={file.file} label="View this document's trace" refreshKey={remNow?.done ? 1 : 0} /></div>}
      <div className="drawerstats">
        <span className="badge" style={{ background: sbg, color: sfg }}>{st}</span>
        <span className="drawerscore">{file.score === null ? 'n/a' : `${st === 'uncertain' ? '≤' : ''}${file.score}`}<span className="muted"> / 100</span></span>
        {st === 'uncertain' && <span className="muted">{file.skipped_rules} rule(s) skipped — score is an upper bound</span>}
        {effectiveRemediated && st === 'issues' && <span className="muted">score reflects the original scan — the fixed copy is stored; re-validate to refresh</span>}
        {(remNow?.done || effectiveRemediated) && (
          <>
            <button className="ghost small dlfixed" style={{ marginLeft: 'auto' }} disabled={remNow === 'queued' || dl === 'loading'}
                    title={remNow === 'queued' ? 'Available once this remediation finishes' : 'Download the fixed copy (Blob primary, Drive-mirror fallback)'}
                    onClick={downloadFixedCopy}>
              {dl === 'loading' ? '⏳ Preparing…' : '⤓ Download fixed copy'}
            </button>
            {dl?.error && (
              <div className="muted" role="status" aria-live="polite" style={{ flexBasis: '100%', color: '#B43A2A', fontSize: 12 }}>
                {dl.error}
              </div>
            )}
          </>
        )}
        {st !== 'unanalysable' && (
          <button className="ghost small" style={(remNow?.done || effectiveRemediated) ? undefined : { marginLeft: 'auto' }} disabled={certExporting}
                  title="Download a branded, timestamped WCAG certification PDF for this file — built from the same coverage data shown below"
                  onClick={async () => {
                    if (certExporting) return
                    setCertExporting(true)
                    try {
                      const rows = computeCoverageRows(file, { catalogRules, targetLevel, remediatedRuleIds, effectiveRemediated, aiEnabled })
                      const now = new Date()
                      const cfg = await getConfig().catch(() => null)
                      const { exportFileCertification } = await import('./pdfReport.js')
                      await exportFileCertification({
                        file: file.file, score: file.score, targetLevel, rows,
                        date: now.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }),
                        timestamp: now.toLocaleString('en-US', { year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }),
                        engine: file.engine, sourceName: file.sourceName, department: file.department || file.dept,
                        platformVersion: cfg?.version,
                      })
                    } catch (e) { console.error('certification PDF export failed', e) }
                    finally { setTimeout(() => setCertExporting(false), 500) }
                  }}>
            {certExporting ? '⏳ Generating…' : '⤓ Certification PDF'}
          </button>
        )}
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
            </div>
            {scanId && r.mode !== 'manual' && r.mode !== 'monitor' && (
              <div style={{ marginTop: 10 }}>
                {remNow === null && (
                  <button className="ctago" disabled={readOnly || effectiveRemediated}
                          title={readOnly ? 'Time-travel replay — switch to the latest scan to remediate'
                                 : effectiveRemediated ? 'Already remediated — the fixed copy is stored; re-validate to refresh the score' : undefined}
                          onClick={remediateNow}>{effectiveRemediated ? '✓ Remediated — fixed copy stored' : '⚡ Remediate this file now'}</button>
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
            {(() => {
              // Engines emit one finding per occurrence (e.g. reading order: one
              // per slide) with no per-occurrence context to display — collapse
              // identical (criterion, severity, detail) rows into one with a count.
              const groups = []
              const byKey = {}
              issues.forEach((i) => {
                const k = `${scOf(i.wcag) || i.wcag}::${i.severity || ''}::${i.detail || ''}`
                if (byKey[k] == null) { byKey[k] = groups.length; groups.push({ ...i, count: 1 }) }
                else groups[byKey[k]].count++
              })
              return groups.map((i, n) => {
              const [bg, fg] = SEV[i.severity] || SEV.MINOR
              return (
                <div className="finding" key={n}>
                  <span className="badge" style={{ background: bg, color: fg }}>{(i.severity || '').toLowerCase()}</span>
                  <div className="findingmain">
                    <div className="findingtop">{critLabel(i.wcag)}{i.count > 1 && <span className="findingcount" title={`${i.count} occurrences of this finding in the file`}>× {i.count}</span>}{i.level && <span className="lvlchip">Level {i.level}</span>}{(() => {
                      // scOfWcag (not scOf): the file's issues carry the engine form
                      // 'SC_3_1_1', which scOf can't parse (it wants a leading digit) — so
                      // the live-queue keys (findStatus) and the per-format auto map are all
                      // built with scOfWcag. Using scOf here would look up findStatus[''] and
                      // silently drop every live badge, leaving even an auto-fixed finding to
                      // fall through to the persisted 'human review' branch.
                      const sc = scOfWcag(i.wcag); const s = findStatus[sc]
                      if (s === 'queued') return <span className="dectag" style={{ background: '#EFEFEF', color: '#666' }}>⏳ queued</span>
                      if (s === 'fixing') return <span className="dectag" style={{ background: '#FDF3E0', color: '#B26A00' }}><span className="spinner" style={{ width: 9, height: 9 }} /> fixing…</span>
                      if (s === 'fixed') return <span className="dectag ok">✓ fixed</span>
                      if (s === 'review') return <span className="dectag" style={{ background: '#ECECF6', color: '#4A4A8A' }}>→ human review</span>
                      // No live status → persisted state. A finding is only ever shown
                      // remediated if it's auto-fixable for this format (per-format map,
                      // else the finding's own auto flag); HITL-deferred findings that a
                      // remediated file left for review show 'human review', not 'remediated'.
                      const fmtAuto = REM_AUTOFIX_SC_BY_TYPE[file.type]
                      const autoFixable = fmtAuto ? fmtAuto.includes(sc) : (i.auto !== false)
                      if (autoFixable && (remediatedRuleIds.has(sc) || isRemediated)) return <span className="dectag ok">✓ remediated</span>
                      if (!autoFixable && isRemediated) return <span className="dectag" style={{ background: '#ECECF6', color: '#4A4A8A' }}>→ human review</span>
                      return null
                    })()}</div>
                    {i.detail && <div className="findingdetail">{i.detail}</div>}
                    {i.impact && <div className="muted findingimpact">{i.impact}</div>}
                    {i.fix && <div className="findingfix"><span className={i.auto ? 'fixauto' : 'fixreview'}>{i.auto ? '⚡ auto-fixable' : '✎ needs review'}</span> · {i.fix}<span className="muted"> · {i.rule_id ?? i.ruleId}</span></div>}
                    {(() => {
                      // Evidence-based confidence (confidence.js) — never a fabricated %.
                      // The basis is always shown next to the level so the signal is auditable.
                      const sc = scOfWcag(i.wcag)
                      const fmtAuto = REM_AUTOFIX_SC_BY_TYPE[file.type]
                      const autoFixable = fmtAuto ? fmtAuto.includes(sc) : (i.auto !== false)
                      const verifiedCleared = remediatedRuleIds.has(sc)
                      const reportedFixedUnverified = !verifiedCleared && isRemediated && autoFixable
                      const { level, basis } = confidenceForFinding({ sc, verifiedCleared, reportedFixedUnverified })
                      return (
                        <div className="findingconf">
                          <span className={confClass(level)} title={`Confidence: ${level.label} — ${basis}`}>{level.label} confidence</span>
                          <span className="muted"> · {basis}</span>
                        </div>
                      )
                    })()}
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
            }) })()}
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
          <details className="sevhelp">
            <summary>How is confidence derived?</summary>
            <p className="muted" style={{ margin: '8px 0' }}>Confidence is a <b>genuine, evidence-based</b> signal — never a made-up percentage. Every level traces to a concrete signal the pipeline already produces, shown as the <i>basis</i> next to it.</p>
            <div className="sevrow"><span className="conf conf-high" style={{ flex: '0 0 auto' }}>High</span><span className="muted">A deterministic rule check (structural/attribute test), a checksum-validated PII match, or a fix that <b>cleared the residual re-scan</b>.</span></div>
            <div className="sevrow"><span className="conf conf-medium" style={{ flex: '0 0 auto' }}>Medium</span><span className="muted">An AI / heuristic detection lane (alt text, link purpose, structure), a pattern-only PII match, or a fix applied but not yet re-scan-confirmed.</span></div>
            <div className="sevrow"><span className="conf conf-low" style={{ flex: '0 0 auto' }}>Low</span><span className="muted">A criterion that requires human judgement — routed to review with no automated signal to stand on.</span></div>
          </details>
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
        // FULL WCAG coverage (2.1 + 2.2, all 87 criteria from wcagCatalog.js) —
        // every criterion gets an HONEST per-file status: FAIL (engine findings),
        // PASS (the engine for this file type checked it and found nothing),
        // HUMAN (a person must verify — HITL-tier criterion), UNCHECKED (not yet
        // automated for this file type), or WEB (web-only criterion that cannot
        // apply to a document). A PASS is only ever claimed for a checked rule.
        const ext = (file.file || '').split('.').pop().toLowerCase()
        const fmt = /^html?$/.test(ext) ? 'html' : ['pdf', 'docx', 'pptx', 'xlsx'].includes(ext) ? ext : null
        const scFromRule = (r) => r.wcag_sc || ((r.wcag || '').startsWith('SC_') ? r.wcag.slice(3).replaceAll('_', '.') : scOf(r.wcag || ''))
        const checkedSCs = fmt === 'html'
          ? new Set(allRules.map((m) => m.meta.id))
          : new Set((((catalogRules || {})[fmt]) || []).map(scFromRule).filter(Boolean))
        const isHuman = (c) => /Human/i.test(c.approach || '') || c.source === 'MDK HITL'
        // Required criteria auto-detected for HTML but not (yet) for document
        // formats — they genuinely apply to PDF/Office forms and colour-coded
        // content, so on a document they route to human review instead of reading
        // as 'not auto-checked'. NOT a blanket flip: web-only criteria (Resize
        // Text, Reflow, Focus Order/Visible…) stay N-A for a static document.
        const DOC_HUMAN_WHEN_UNCHECKED = new Set(['1.4.1', '1.3.5', '2.5.3', '4.1.2'])
        const fixOf = (c) => {
          if ((c.tier || '').startsWith('Tier 1')) return '⚡ auto'
          if ((c.tier || '').startsWith('Tier 2')) return aiEnabled ? '✎ AI' : '✋ human'
          return '✋ human'
        }
        // An unreadable file ran ZERO checks — claiming any PASS would be false.
        if (st === 'unanalysable') {
          return (
            <details className="covmanifest">
              <summary className="covmanifest-sum">WCAG coverage — file could not be analysed</summary>
              <div className="covmanifest-note muted">The engine could not open this file (corrupt or password-protected), so no checks ran and no criterion can be claimed as passing. Fix or replace the source file, then re-scan.</div>
            </details>
          )
        }
        const LEVEL_RANK = { A: 1, AA: 2, AAA: 3 }
        const targetRank = LEVEL_RANK[targetLevel] || 2
        const OUT_RANK = { FAIL: 0, FIXED: 0.5, PASS: 1, HUMAN: 2, UNCHECKED: 3, WEB: 4 }
        const OUT_TXT = { PASS: 'pass', FAIL: 'fail', FIXED: 'fixed · re-validate', HUMAN: 'human review', UNCHECKED: 'not auto-checked', WEB: 'web-only' }
        const OUT_TIP = {
          FIXED: 'Remediated in this session — the fixed copy is stored; re-validate (re-scan the fixed copy) to confirm the pass',
          HUMAN: 'This criterion needs a person to verify — it routes through the HITL workflow, not the engine',
          UNCHECKED: 'Not yet automated for this file type — no engine rule evaluates it',
          WEB: 'Web-page criterion — cannot apply to a document file',
        }
        // Issues carry wcag as either 'SC_1_3_1' (engine records) or '1.3.1 name'
        // (axe-style) — normalize both to the bare SC id.
        const scOfIssue = (v) => ((v || '').replace(/^SC_/, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/) || [''])[0]
        const issuesBySc = {}
        ;(file.issues || []).forEach((i) => {
          const sc = scOfIssue(i.wcag)
          if (sc) { if (!issuesBySc[sc]) issuesBySc[sc] = []; issuesBySc[sc].push(i) }
        })
        // Scope: only criteria that can apply to documents, at or below the
        // certification target. Web-only and above-target rows are counted in
        // the footnote instead of listed — 87 rows of mostly-N/A is noise.
        const inScope = WCAG.filter((c) => c.docApplies !== false && (LEVEL_RANK[c.level] || 3) <= targetRank)
        const hiddenAboveLevel = WCAG.filter((c) => c.docApplies !== false && (LEVEL_RANK[c.level] || 3) > targetRank).length
        const hiddenWebOnly = WCAG.length - inScope.length - hiddenAboveLevel
        const rows = inScope.map((c) => {
          const fileIssues = issuesBySc[c.sc] || []
          const count = fileIssues.length
          const wasFixed = count > 0 && (remediatedRuleIds.has(c.sc)
            || (effectiveRemediated && (REM_AUTOFIX_SC_BY_TYPE[file.type] || []).includes(c.sc)))
          const outcome = wasFixed ? 'FIXED'
            : count > 0 ? 'FAIL'
            : checkedSCs.has(c.sc) ? 'PASS'
            : isHuman(c) ? 'HUMAN'
            : (DOC_HUMAN_WHEN_UNCHECKED.has(c.sc) && fmt && fmt !== 'html') ? 'HUMAN'
            : 'UNCHECKED'
          const confidence = confidenceForCoverage({ sc: c.sc, outcome, verifiedCleared: remediatedRuleIds.has(c.sc) })
          return { id: c.sc, name: c.name, plain: PLAIN_NAMES[c.sc] || c.name, req: c.req, level: c.level, fix: fixOf(c), outcome, count, fileIssues, confidence }
        }).sort((a, b) => (OUT_RANK[a.outcome] ?? 3) - (OUT_RANK[b.outcome] ?? 3))
        const n = (o) => rows.filter((r) => r.outcome === o).length
        return (
          <details className="covmanifest" open>
            <summary className="covmanifest-sum">
              WCAG coverage · {rows.length} criteria at {targetLevel} · documents
              <span className="covstat pass">{n('PASS')} pass</span>
              {n('FAIL') > 0 && <span className="covstat fail">{n('FAIL')} fail</span>}
              {n('FIXED') > 0 && <span className="covstat pass">{n('FIXED')} fixed · re-validate</span>}
              {n('HUMAN') > 0 && <span className="covstat skip">{n('HUMAN')} human review</span>}
              {n('UNCHECKED') > 0 && <span className="covstat skip">{n('UNCHECKED')} not auto-checked</span>}
            </summary>
            <div className="covmanifest-note muted">Criteria that apply to documents, at your {targetLevel} certification target — <b>pass</b> is only claimed where the {fmt || 'file'} engine actually evaluates the criterion; <b>human review</b> routes through the HITL workflow. Hidden: {hiddenAboveLevel} above-{targetLevel} and {hiddenWebOnly} web-only criteria.</div>
            <table className="covtable">
              <thead><tr><th>SC</th><th>Name</th><th>Lvl</th><th>Fix</th><th>Outcome</th><th>Confidence</th></tr></thead>
              <tbody>
                {rows.map((r) => {
                  const exp = explanations[r.id]
                  return (
                    <Fragment key={r.id}>
                      <tr className={`covrow ${r.outcome === 'FAIL' ? 'fail' : (r.outcome === 'PASS' || r.outcome === 'FIXED') ? 'pass' : 'skip'}`}>
                        <td className="covsc">{r.id}</td>
                        <td>{r.plain}<div className="muted" style={{ fontSize: 11 }}>{r.plain === r.name ? (r.req || '').slice(0, 90) : r.name}</div></td>
                        <td className="muted">{r.level}</td>
                        <td className="muted">{r.fix}</td>
                        <td className={`covoutcome ${r.outcome === 'FAIL' ? 'fail' : (r.outcome === 'PASS' || r.outcome === 'FIXED') ? 'pass' : 'skip'}`} title={OUT_TIP[r.outcome]}>
                          {(r.outcome === 'PASS' || r.outcome === 'FIXED') ? '✓' : r.outcome === 'FAIL' ? `✕ ${r.count}` : r.outcome === 'HUMAN' ? '👤' : '—'}
                          <span className="covouttxt">{r.outcome === 'PASS' && remediatedRuleIds.has(r.id) ? 'pass — remediated' : OUT_TXT[r.outcome]}</span>
                          {r.outcome === 'FAIL' && scanId && !exp && (
                            <button className="explain-btn" onClick={() => fetchExplanation(r.id)} title="Get AI explanation">Why?</button>
                          )}
                        </td>
                        <td className="covconf">
                          {r.confidence
                            ? <span className={confClass(r.confidence.level)} title={`Confidence: ${r.confidence.level.label} — ${r.confidence.basis}`}>{r.confidence.level.label}</span>
                            : <span className="muted">—</span>}
                        </td>
                      </tr>
                      {r.outcome === 'FAIL' && r.fileIssues.length > 0 && (
                        <tr className="covrow-issues">
                          <td colSpan={6}>
                            {r.fileIssues.map((issue, idx) => {
                              const [bg, fg] = SEV[issue.severity] || SEV.MINOR
                              return (
                                <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: 7, padding: '3px 0 3px 10px', borderLeft: `2px solid ${bg}` }}>
                                  <span className="badge" style={{ background: bg, color: fg, fontSize: 10, padding: '1px 5px', flexShrink: 0 }}>{(issue.severity || '').toLowerCase()}</span>
                                  <div style={{ fontSize: 12, lineHeight: 1.4 }}>
                                    {issue.fix && <span>{issue.fix}</span>}
                                    {issue.detail && !issue.fix && <span>{issue.detail}</span>}
                                    {issue.auto != null && <span className={issue.auto ? 'fixauto' : 'fixreview'} style={{ marginLeft: 6, fontSize: 11 }}>{issue.auto ? '⚡ auto' : '✎ review'}</span>}
                                  </div>
                                </div>
                              )
                            })}
                          </td>
                        </tr>
                      )}
                      {r.outcome === 'FAIL' && exp && (
                        <tr className="covrow-explain">
                          <td colSpan={6}>
                            {exp.loading && <span className="explain-loading">⏳ thinking…</span>}
                            {exp.error && <span className="explain-error muted">AI explanation unavailable{exp.detail === 'timeout' ? ' — timed out after 45s' : ''} — is Ollama running? <button className="explain-btn" onClick={() => fetchExplanation(r.id)}>retry</button></span>}
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
