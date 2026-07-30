import { SIM, simIdentity, simGetSources, simStartScan, simGetJob, simGetScan, simListScans, simRules, simRemediationDiffs } from './sim.js'
import { CAPABILITY_FALLBACK } from './capability.js'

const BASE = import.meta.env.VITE_API ?? 'http://localhost:8077'

// Per-user tokens (real mode only). In SIM mode nothing touches a real Drive / OneDrive.
let driveToken = null
let spToken = null
let googleToken = null  // GIS Bearer token (auth mode = "gis")
export const setDriveToken = (t) => { driveToken = t }
export const setSPToken = (t) => { spToken = t }
export const setGoogleToken = (t) => { googleToken = t }
export const clearAllTokens = () => { googleToken = null; driveToken = null; spToken = null }
const headers = (extra = {}) => ({
  ...extra,
  ...(googleToken ? { 'Authorization': 'Bearer ' + googleToken } : {}),
  ...(driveToken ? { 'X-Drive-Token': driveToken } : {}),
  ...(spToken ? { 'X-SP-Token': spToken } : {}),
})

// Why the user was bounced to the sign-in screen. Carried on the event so that screen can SAY
// it. Being silently returned to sign-in, mid-task, with no explanation is indistinguishable
// from the app having lost your work: the token lives only in this module, so a reload or an
// expiry drops it, and every subsequent click quietly 401s.
export const SESSION_EXPIRED =
  'Your session expired, so you were signed out. Sign in again to pick up where you left off — anything already saved is safe.'

// Why a scan the client is holding cannot be loaded. Scans are scoped to the user who ran them
// (per-user isolation, 0a1b167), and a per-scan read for somebody else's scan answers 404 — not
// 403 — so an id is not an existence oracle across accounts. That is correct, and it is also
// invisible: found live 2026-07-29, an allow-listed user's client held an id it could never
// load and re-requested /traces and /diff for ~60s with every failure ending in
// `.catch(() => null)`. Assess produced no score and said nothing. An empty score the user
// cannot explain is worse than an error, so say it and move them somewhere that works.
export const SCAN_UNAVAILABLE =
  'That scan isn’t available to your account — scans are private to the person who ran them, and this one may belong to another account or have been removed.'

// Backend detail for exactly this case. Coupled deliberately, and NOT by status alone: a 404
// from a per-file or per-trace route under a scan the user does own is a different problem and
// must not evict their scan. tests/test_scan_not_found_detail.py pins the string server-side so
// this coupling cannot drift silently.
const SCAN_NOT_FOUND_DETAIL = /^scan not found$/i

// Backend marker for "Ollama answered, but the model it would need is not pulled". Coupled
// deliberately and NOT by status alone: /ai/suggest also 503s when the model IS pulled and the
// call merely failed, and that one must stay retryable per card. api/routes/ai.py owns the
// string (MODEL_NOT_PULLED) and tests/test_ai_model_not_pulled_detail.py pins it server-side.
//
// Flagged rather than rewritten: the server's detail already names the model and the `ollama pull`
// that fixes it, and the review card renders it verbatim. This only tells autoDraft.js that
// re-asking is pointless — see the circuit breaker there.
const AI_MODEL_NOT_PULLED_DETAIL = /\bmodel not pulled\b/i
// The scan id out of `<base>/scans/<id>[/...]`. Read off the Response, so it works for every
// wrapper below without threading the id through each one.
const SCAN_URL_RE = /\/scans\/([^/?#]+)/

const j = async (r) => {
  if (r.status === 401) {
    googleToken = null
    window.dispatchEvent(new CustomEvent('acp:session-expired', { detail: { reason: SESSION_EXPIRED } }))
    throw new Error(SESSION_EXPIRED)
  }
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const body = await r.json()
      if (body?.detail) detail = body.detail
    } catch (_) { /* body wasn't JSON */ }
    if (r.status === 404 && SCAN_NOT_FOUND_DETAIL.test(String(detail).trim())) {
      const m = SCAN_URL_RE.exec(r.url || '')
      const scanId = m ? decodeURIComponent(m[1]) : null
      // Announce BEFORE throwing, so the many callers that end in `.catch(() => null)` — the
      // whole reason this was silent — cannot suppress it.
      window.dispatchEvent(new CustomEvent('acp:scan-unavailable',
        { detail: { scanId, reason: SCAN_UNAVAILABLE } }))
      const e = new Error(SCAN_UNAVAILABLE)
      e.scanUnavailable = true
      e.scanId = scanId
      throw e
    }
    const e = new Error(detail)
    // A capability failure, not a transient one: every other card in the inbox would hit the
    // same missing model, so the auto-draft gate stops rather than asking N more times.
    if (r.status === 503 && AI_MODEL_NOT_PULLED_DETAIL.test(String(detail))) e.aiModelNotPulled = true
    throw e
  }
  return r.json()
}
const sim = (value, ms = 220) => new Promise((res) => setTimeout(() => res(value), ms))

// AI provenance (ADR 0019 Phase 0): the active model + local/cloud zone, cached from /config so
// any surface (the review card's "Generated by …" line + privacy badge) can read it without
// threading a prop through the tree. Null until the first getConfig resolves — callers tolerate it.
let _aiProv = null
export const aiProvenance = () => _aiProv
export const getConfig = () => (SIM ? sim({ google_client_id: null, auth: 'demo', sim: true, ai: { provider: 'ollama', model: 'llama3.1', vision_model: 'llava:13b', zone: 'local', host: 'localhost' }, langfuse_trace_base: 'https://acp-langfuse.demo/project/acp-compliance/traces' }) : fetch(`${BASE}/config`).then(j)).then((c) => { _aiProv = c.ai || _aiProv; return c })
// Langfuse deep-link base (from /config) → "📊 View trace" chips. traceUrl(null) when unset.
let lfTraceBase = null
export const setLangfuseBase = (b) => { lfTraceBase = b || null }
// Direct deep-link to the trace. Safe now that the backend caps per-document spans on the
// Scan trace (ACP_SCAN_TRACE_SPAN_CAP), so traces stay small enough for the Langfuse detail
// view to load even on large estates.
export const traceUrl = (traceId) => (lfTraceBase && traceId ? `${lfTraceBase}/${encodeURIComponent(traceId)}` : null)
// Reliable trace link: route the chip through the backend redirect endpoint. File-centric
// tracing (backend: lf.file_trace) — every file gets its OWN Langfuse trace, with Discover/
// Assess/Remediate as spans inside it, grouped into a session keyed by scan_id:
//   kind='file'    — scanId + file → that ONE file's full Discover→Assess→Remediate trace.
//                     Ensures it exists before 302-ing, so a click never lands on "Not Found".
//   kind='session' — scanId only   → the Langfuse session for the whole scan (every one of
//                     its file traces) — the "view this scan" replacement for the old single
//                     scan/assess/remediate trace. Never 404s, even before any file ran.
// Returns null when tracing isn't configured (no chip). SIM keeps a direct deep-link (no backend).
export const openTraceUrl = (scanId, kind = 'session', file = null) => {
  if (!scanId) return null
  if (SIM) return traceUrl(kind === 'file' && file ? `${scanId}::${file}` : scanId)
  if (!lfTraceBase) return null
  if (kind === 'file' && file) return `${BASE}/scans/${encodeURIComponent(scanId)}/trace/file/${encodeURIComponent(file)}`
  return `${BASE}/scans/${encodeURIComponent(scanId)}/trace/session`
}
export const getTraceStatus = (scanId, kind = 'session', file = null) => {
  if (!scanId || SIM) return Promise.resolve({ available: !!scanId })
  if (!lfTraceBase) return Promise.resolve({ available: false })
  if (kind === 'file' && file)
    return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/trace/file/${encodeURIComponent(file)}/exists`).then(j).catch(() => ({ available: false }))
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/trace/${kind}/exists`).then(j).catch(() => ({ available: false }))
}
// Sensitive-data (PII) findings for a scan (ADR 0006) — rollup + per-type counts (masked).
export const getScanPii = (scanId) => (SIM
  ? sim({ summary: { documents: 6, items: 23, by_type: [
      { pii_type: 'ssn', label: 'US SSN', count: 9, docs: 4 },
      { pii_type: 'credit_card', label: 'Credit card', count: 7, docs: 3 },
      { pii_type: 'email', label: 'Email address', count: 5, docs: 5 },
      { pii_type: 'phone', label: 'Phone number', count: 2, docs: 2 },
    ] }, files: [] })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/pii`, { headers: headers() }).then(j).catch(() => null))
// AI Compliance Digest (bundle #2) — exec paragraph grounded in real scan data + the facts.
export const getDigest = (scanId, refresh = false) => (SIM
  ? sim({
    headline: '52 of 175 documents conformant (79/100 average).', score: 79,
    narrative: 'Your estate sits at 79/100 with 52 of 175 documents fully conformant. Since the last scan the score rose 4 points, though 3 documents regressed after edits — most notably the public landing page, which lost contrast compliance. The single biggest systemic gap is missing alt text, failing on 89 documents; fixing it would move the most documents toward AA. Recommended: prioritise alt-text remediation across the estate and re-validate the three regressions.',
    changed: ['Estate score rose 4 points to 79/100 since the last scan.', '3 documents regressed — worst: marketing-public-landing-page.html (100→82).', '9 documents improved.', '6 documents contain sensitive data flagged for review.'],
    top_issue: 'Images have alt text (1.1.1) fails on 89 documents — the biggest systemic gap.',
    next_action: 'Fix Images have alt text across the estate — it clears the most documents toward AA.',
    ai: true, model: 'local model',   // SIM must not name a model the product never calls
  }, 1500)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/digest${refresh ? '?refresh=true' : ''}`, { headers: headers() }).then(j))
// Regression diff vs a prior scan (ADR 0009) — which docs got worse/better + criteria that broke.
export const getScanDiff = (scanId, vs = null) => {
  if (SIM) return sim({
    cur_id: scanId, prev_id: 'h3', cur_at: '2026-06-29T17:00:00Z', prev_at: '2026-06-22T09:00:00Z',
    summary: { regressed: 3, improved: 9, new: 2, removed: 1 },
    regressed: [
      { file: 'marketing-public-landing-page.html', prev: 100, cur: 82, delta: -18, broke: [{ sc: '1.4.3', name: 'Contrast (minimum)' }] },
      { file: 'cardiology-patient-handbook.pdf', prev: 91, cur: 78, delta: -13, broke: [{ sc: '1.1.1', name: 'Images have alt text' }, { sc: '2.4.6', name: 'Headings & labels' }] },
      { file: 'q3-board-deck.pptx', prev: 88, cur: 84, delta: -4, broke: [] },
    ],
    improved: [
      { file: 'onboarding.pdf', prev: 72, cur: 100, delta: 28 },
      { file: 'benefits-guide.pdf', prev: 80, cur: 96, delta: 16 },
    ],
    new: [{ file: 'hr-policy-2026.docx', score: 64 }, { file: 'patient-intake-form-v2.pdf', score: 88 }],
    removed: [{ file: 'legacy-archive-page.html', score: 55 }],
  }, 220)
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/diff${vs ? `?vs=${encodeURIComponent(vs)}` : ''}`, { headers: headers() }).then(j)
}
// Per-WCAG-rule outcomes for a scan (PASS/FAIL/SKIP + finding counts), one row per file×rule.
// `file` narrows to one document — the route has always supported it (scans.py: get_scan_traces
// takes file=), the client just never passed it. Assess uses it to name the criteria a document
// failed the moment it finishes, without pulling every file's rows on every poll.
export const getScanTraces = (scanId, file = null) => {
  if (SIM) {
    const SCS = [['1.1.1', 'Images have alt text', 'A'], ['1.3.1', 'Info & relationships', 'A'], ['1.4.3', 'Contrast (minimum)', 'AA'], ['2.4.4', 'Link purpose', 'A'], ['2.4.6', 'Headings & labels', 'AA'], ['3.1.1', 'Language of page', 'A'], ['1.2.2', 'Captions', 'A'], ['4.1.2', 'Name, role, value', 'A'], ['2.4.7', 'Focus visible', 'AA'], ['1.4.11', 'Non-text contrast', 'AA'], ['3.3.2', 'Labels or instructions', 'A'], ['2.1.1', 'Keyboard', 'A']]
    const rows = []
    SCS.forEach(([id, name, level], k) => { for (let f = 0; f < 25; f++) { const r = (f * 7 + k * 3) % 10; const outcome = r < 2 ? 'SKIP' : (r < 5 ? 'FAIL' : 'PASS'); rows.push({ file: `doc-${f}.html`, rule_id: id, plain_name: name, level, outcome, finding_count: outcome === 'FAIL' ? r : 0 }) } })
    return sim(rows, 150)
  }
  const q = file ? `?file=${encodeURIComponent(file)}` : ''
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/traces${q}`, { headers: headers() }).then(j)
}
// The concrete values AI fixes wrote this scan (real vision alt text + a small image
// thumbnail), for the "Recent AI fixes" panel. Best-effort — [] on any error/SIM.
export const getAppliedFixes = (scanId) => (SIM || !scanId
  ? sim([])
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/applied-fixes`, { headers: headers() }).then(j).catch(() => []))
// The AI provenance ledger for a scan (ADR 0019 Phase 0b): one row per model call with surface /
// provider / model / privacy zone / latency / outcome — the auditable "what model saw my document,
// where did it run?" record behind the review card's audit panel. Best-effort — [] on any error/SIM.
export const getScanAiCalls = (scanId) => (SIM || !scanId
  ? sim([])
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/ai_calls`, { headers: headers() }).then(j).catch(() => []))
// Per-fix before→after evidence for one file — the original text/markup → remediated
// version, persisted only for fixes that verifiably cleared. Feeds the certification PDF's
// "Before → After" section, and the review drawer's evidence card. SIM serves the same
// fixtures as getScanRemediationDiffs, narrowed to the one file, on the same "only after the
// demo has actually remediated" gate.
export const getFileRemediationDiffs = (scanId, file) => {
  if (SIM) return sim(_simRemed.total ? simRemediationDiffs().filter((d) => d.file === file) : [])
  if (!scanId) return sim([])
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/remediation-diffs`,
               { headers: headers() }).then(j).catch(() => [])
}
// Scan-wide before→after evidence — every verified-cleared fix across all files, so the
// Remediation view can group REAL applied fixes by rule/category without fabricating counts.
// Covers all fix types (reading order, titles, headings, tables), unlike applied-fixes
// (image alt text only). Best-effort — [] on any error.
//
// SIM has no engine, so it serves fixtures — but only once the demo has actually run
// remediation (_simRemed.total). Returning them unconditionally would open the Remediation
// view already claiming "N issues fixed automatically" and marking the step done.
export const getScanRemediationDiffs = (scanId) => {
  if (SIM) return sim(_simRemed.total ? simRemediationDiffs() : [])
  if (!scanId) return sim([])
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/remediation-diffs`,
               { headers: headers() }).then(j).catch(() => [])
}
// Audit trail (maturity Phase 4): chronological provenance of one document in one scan —
// scanned → AI drafted → human decided → fix written → published. Every event is a real
// persisted row; [] on any error (the History panel simply doesn't render).
export const getDocumentTimeline = (scanId, file) => {
  if (SIM || !scanId || !file) return sim([])
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/timeline?file=${encodeURIComponent(file)}`,
               { headers: headers() }).then(j).catch(() => [])
}
export const getMe = () => (SIM ? sim(simIdentity()) : fetch(`${BASE}/me`, { headers: headers() }).then(j))
export const getSources = () => (SIM ? sim(simGetSources()) : fetch(`${BASE}/sources`, { headers: headers() }).then(j))
export const getRubric = () => (SIM
  ? sim({ name: 'WCAG 2.1 AA', version: '1', hash: 'e85fcf7e14f9040c', target: 'WCAG 2.1 AA', threshold: 90, criteria: {} })
  : fetch(`${BASE}/rubric`, { headers: headers() }).then(j))
export const getRules = () => (SIM ? sim(simRules()) : fetch(`${BASE}/rules`, { headers: headers() }).then(j))
// Per-(criterion × format) remediation capability — the single source of truth for which
// WCAG criteria are auto-fixable per file format (see capability.js). SIM and any fetch
// failure fall back to the bundled table, so the format-aware UI never regresses to the
// format-blind view even offline.
export const getCapability = () => (SIM
  ? sim({ formats: Object.keys(CAPABILITY_FALLBACK), capability: CAPABILITY_FALLBACK })
  : fetch(`${BASE}/capability`, { headers: headers() }).then(j)
      .catch(() => ({ formats: Object.keys(CAPABILITY_FALLBACK), capability: CAPABILITY_FALLBACK })))
export const updateRubric = (body) => (SIM
  ? sim({ hash: 'e85fcf7e14f9040c', disabled_rules: body.disabled_rules || [], threshold: body.compliant_threshold || 90 })
  : fetch(`${BASE}/rubric`, { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) }).then(j))
export const listScans = () => (SIM ? sim(simListScans()) : fetch(`${BASE}/scans`, { headers: headers() }).then(j))
// In-flight scan (for reconnecting after a reload). Returns {} when nothing is running.
export const getActiveScan = () => (SIM ? sim({}) : fetch(`${BASE}/scans/active`, { headers: headers() }).then(j))
// ADR 0014: push a freshly-minted GIS token to a running scan so long scans keep Drive auth.
export const refreshScanDriveToken = (scanId) => (SIM
  ? sim({ refreshed: true })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/drive-token`, { method: 'POST', headers: headers() }).then(j))
export const getScan = (id) => (SIM ? sim(simGetScan(id)) : fetch(`${BASE}/scans/${id}`, { headers: headers() }).then(j))
export const getInventory = () => (SIM ? sim([]) : fetch(`${BASE}/inventory`, { headers: headers() }).then(j))
export const reportUrl = (id) => (SIM ? '#' : `${BASE}/scans/${id}/report.pdf`)
// Fetch the report WITH the auth header (owner-scoped) → blob → download. Replaces the
// old tokenless <a href>, which let anyone pull another user's report by scan id.
export const openReport = (id, filename) => {
  if (SIM) return Promise.resolve()
  return fetch(`${BASE}/scans/${encodeURIComponent(id)}/report.pdf`, { headers: headers() })
    .then((r) => { if (!r.ok) throw new Error(`report ${r.status}`); return r.blob() })
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = filename || `acp-report-${id}.pdf`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    })
}
export const startScan = (source = 'local', folder = null, aiEnabled = true, pii = true, excludeRemediated = false, incremental = true) => (SIM ? sim(simStartScan(source), 120) : fetch(`${BASE}/scans?source=${source}${folder ? `&folder=${encodeURIComponent(folder)}` : ''}&ai=${aiEnabled}&pii=${pii}&exclude_remediated=${excludeRemediated}&incremental=${incremental}`, { method: 'POST', headers: headers() }).then(j))
export const getJob = (id) => (SIM ? sim(simGetJob(id), 60) : fetch(`${BASE}/scans/jobs/${id}`, { headers: headers() }).then(j))

// ── Durable async queue (ADR 0004/0005) ───────────────────────────────────────
// Queued scan: runs in the worker pool, survives restarts, shows in /jobs + Grafana.
export const startScanQueued = (source = 'local', folder = null, aiEnabled = true, pii = true, excludeRemediated = false, incremental = true) => (SIM
  ? sim({ scan_id: 'sim-scan', job_id: 'sim-job', queued: true, workers: 4 })
  : fetch(`${BASE}/scans?source=${source}${folder ? `&folder=${encodeURIComponent(folder)}` : ''}&ai=${aiEnabled}&pii=${pii}&exclude_remediated=${excludeRemediated}&incremental=${incremental}&queue=true&fanout=true`, { method: 'POST', headers: headers() }).then(j))
// Stop an in-flight durable scan: kills its outstanding jobs server-side and closes the run
// as 'cancelled' (files already analysed keep their records). Owner-scoped — 409 otherwise.
export const cancelScan = (scanId) => (SIM
  ? sim({ scan_id: scanId, status: 'cancelled' })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/cancel`, { method: 'POST', headers: headers() }).then(j))
// Async server-side remediation: one remediate_file job per HTML file in the scan.
// SIM keeps a tiny drain state so getRemediationStatus ticks down over a few polls —
// the demo then shows the live KPI / progress-bar updates instead of finishing instantly.
let _simRemed = { remaining: 0, total: 0 }
export const remediateScan = (scanId, scope) => {
  if (SIM) { const n = scope ? scope.length : 3; _simRemed = { remaining: n, total: n }; return sim({ scan_id: scanId, enqueued: n, job_ids: ['a', 'b', 'c'], workers: 4 }) }
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/remediate`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify(scope ? { scope } : {}) }).then(j)
}
// Access allow-list (who can use the app) — managed from Settings.
export const getAllowlist = () => (SIM
  ? sim({ emails: ['demo@sim'], owner: 'demo@sim', domains: [] })
  : fetch(`${BASE}/admin/allowlist`, { headers: headers() }).then(j))
export const setAllowlist = (emails) => (SIM
  ? sim({ emails })
  : fetch(`${BASE}/admin/allowlist`, { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify({ emails }) }).then(j))
// Per-scan decision snapshots (PRD: time-travel) — restore/persist triage + action decisions.
export const getDecisions = (scanId) => (SIM
  ? sim({})
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/decisions`, { headers: headers() }).then(j))
export const saveDecision = (scanId, file, kind, value) => (SIM
  ? sim({ ok: true })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/decisions/${encodeURIComponent(file)}?kind=${kind}`,
          { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify({ value }) }).then(j))
export const saveDecisionsBatch = (scanId, items) => (SIM
  ? sim({ ok: true })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/decisions`,
          { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify({ items }) }).then(j))
// Run the WCAG assessment into Langfuse on demand (separate from the scan trace).
export const assessScan = (scanId, level = 'AA') => (SIM
  ? sim({ ok: true })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/assess?level=${encodeURIComponent(level)}`,
          { method: 'POST', headers: headers() }).then(j))
// Live remediation progress: in-flight jobs + latest fixed file (drives the Remediate bar).
export const getRemediationStatus = (scanId) => {
  if (SIM) {
    const step = Math.max(1, Math.ceil(_simRemed.total / 4))   // drain over ~4 polls
    _simRemed.remaining = Math.max(0, _simRemed.remaining - step)
    const fixedSoFar = _simRemed.total - _simRemed.remaining
    return sim({ in_flight: _simRemed.remaining, failed: 0,
                 latest_file: _simRemed.remaining ? `report-${fixedSoFar}.html` : `report-${_simRemed.total}.html` }, 120)
  }
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/remediation-status`, { headers: headers() }).then(j)
}
// Per-violation remediation state (ADR 0003 Phase 2) for one file — which rule_ids were
// actually auto-fixed, so the rule coverage table can say "pass — remediated" instead of
// just "pass" for a criterion that used to fail. SIM has no per-violation state to draw
// on, so it returns nothing rather than fabricate it.
export const getFileRemediationState = (scanId, file) => (SIM
  ? sim([])
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/remediation-state`,
          { headers: headers() }).then(j))
// Platform settings (admin) — includes ADR 0010's Drive-mirror on/off + folder name.
export const getSettings = () => (SIM
  ? sim({ ai_enabled: true, drive_mirror_enabled: true, drive_mirror_folder: 'Remediated' })
  : fetch(`${BASE}/settings`, { headers: headers() }).then(j))
// AI usage + cost governance rollup (ADR 0019 Phase 1) — today / month / all-time.
const _emptyRoll = { calls: 0, ok: 0, failed: 0, cost_usd: 0, avg_latency_ms: 0, scans: 0, by_provider: [], by_zone: [], by_surface: [] }
export const getAiCosts = () => (SIM
  ? sim({ today: _emptyRoll, month: _emptyRoll, all_time: _emptyRoll })
  : fetch(`${BASE}/ai/costs`, { headers: headers() }).then(j).catch(() => ({ today: _emptyRoll, month: _emptyRoll, all_time: _emptyRoll })))
// AI provider gateway config (ADR 0019 §6). The API returns only SAFE views — never a key value,
// just whether the referenced secret is present. putAiProvider sends the secret's reference NAME,
// never a key (the backend rejects a pasted key).
// The error is NOT swallowed here: a 403 means this signed-in user is not the owner, so the
// admin forms must be disabled rather than presented as editable fields whose save can only
// fail. Callers that just want a list can still .catch() themselves.
export const getAiProviders = () => (SIM
  ? sim({ providers: [] })
  : fetch(`${BASE}/ai/providers`, { headers: headers() }).then(j))
export const putAiProvider = (patch) => (SIM
  ? sim({ providers: [] })
  : fetch(`${BASE}/ai/providers`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(patch),
    }).then(j))
export const updateSettings = (patch) => (SIM
  ? sim({ ai_enabled: true, drive_mirror_enabled: true, drive_mirror_folder: 'Remediated', ...patch })
  : fetch(`${BASE}/settings`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(patch),
    }).then(j))
// Download a remediated file's fixed bytes (ADR 0010) — Blob primary, Drive-mirror
// fallback server-side. Authenticated fetch → blob → download, same pattern as
// openReport (a bare <a href> would drop the Authorization header).
export const downloadRemediated = (scanId, file) => {
  if (SIM) return Promise.resolve()
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/remediated`,
               { headers: headers() })
    .then((r) => { if (!r.ok) throw new Error(`download ${r.status}`); return r.blob() })
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = file
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    })
}
// Status of one durable-queue job — real progress for a single-file remediation
// (queued → running → done/dead) instead of a timed guess. SIM scripts a quick
// two-poll running → done sequence per job id.
const _simJobs = {}
export const getQueueJob = (jobId) => {
  if (SIM) {
    _simJobs[jobId] = (_simJobs[jobId] ?? 3) - 1
    return sim({ id: jobId, type: 'remediate_file', status: _simJobs[jobId] > 0 ? 'running' : 'done' }, 120)
  }
  return fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}`, { headers: headers() }).then(j)
}
// Send this scan's review-needing findings to the server HITL queue (idempotent
// POST /hitl/queue/{sid}/auto) — called after a single-file remediate-now so an
// AI-assisted fix still gets human sign-off instead of silently skipping review.
export const queueHitlReview = (scanId) => (SIM
  ? sim({ queued: 1 })
  : fetch(`${BASE}/hitl/queue/${encodeURIComponent(scanId)}/auto`, { method: 'POST', headers: headers() }).then(j))
// ── Phased remediation campaigns (ADR 0003 Phase 4) ─────────────────────────────
export const createCampaign = (scanId, name, deadline = null) => (SIM
  ? sim({ campaign_id: 'sim-campaign', name, status: 'active', batches: [] }, 200)
  : fetch(`${BASE}/campaigns`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ scan_id: scanId, name, deadline }),
    }).then(j))
export const listCampaigns = (scanId) => (SIM
  ? sim([])
  : fetch(`${BASE}/campaigns?scan_id=${encodeURIComponent(scanId)}`, { headers: headers() }).then(j))
export const getCampaign = (campaignId) => (SIM
  ? sim(null)
  : fetch(`${BASE}/campaigns/${encodeURIComponent(campaignId)}`, { headers: headers() }).then(j))
export const setCampaignStatus = (campaignId, status) => (SIM
  ? sim({ campaign_id: campaignId, status })
  : fetch(`${BASE}/campaigns/${encodeURIComponent(campaignId)}/status`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ status }),
    }).then(j))
// ── HITL review queue ─────────────────────────────────────────────────────────
// Auto-populate HITL queue from AI-assisted FAILs in a scan (idempotent).
export const autoPopulateHitlQueue = (scanId) => (SIM
  ? sim({ queued: 0, items: [] })
  : fetch(`${BASE}/hitl/queue/${encodeURIComponent(scanId)}/auto`, { method: 'POST', headers: headers() }).then(j))
// List ALL HITL items across scans (the global "AI Work Inbox" bell). No scan_id → the
// backend returns every item; status omitted → every status (metrics need resolved ones).
export const listAllHitl = (status = null) => (SIM
  ? sim([], 60)
  : fetch(`${BASE}/hitl/queue${status ? `?status=${status}` : ''}`, { headers: headers() }).then(j))
// List HITL items for a scan, optionally filtered by status.
export const listHitlQueue = (scanId, status = null) => (SIM
  ? sim([])
  : fetch(`${BASE}/hitl/queue?scan_id=${encodeURIComponent(scanId)}${status ? `&status=${status}` : ''}`, { headers: headers() }).then(j))
// Update a HITL item (approved / rejected / skipped) with an optional reviewer note
// and/or the reviewer's final (AI-drafted or hand-edited) approved_value.
// opts (optional) carries review telemetry for the Intelligent Review Workspace:
// { edited } — reviewer changed the AI draft before approving (confidence-calibration signal);
// { reviewMs } — time from card-open to decision (the reviewer-time-saved metric);
// { aiValue } — the AI-proposed value shown, so the server stores proposed-vs-final.
// opts.approvedValues — one final text per proposal, positionally (the row holds one proposal
// per image). A null/'' entry accepts that proposal's own draft. The server writes them into
// the document; approved_value stays the single headline value, for the audit log.
export const updateHitlItem = (itemId, status, reviewerNote = null, approvedValue = null, opts = {}) => (SIM
  ? sim({ id: itemId, status })
  : fetch(`${BASE}/hitl/queue/${encodeURIComponent(itemId)}`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ status, reviewer_note: reviewerNote, approved_value: approvedValue,
        approved_values: opts.approvedValues ?? null,
        edited: !!opts.edited, review_ms: opts.reviewMs ?? null, ai_value: opts.aiValue ?? null,
        // Feedback intelligence: WHY a rejection happened (enum; bulk/keyboard paths send 'unspecified')
        reject_reason: opts.rejectReason ?? null,
        // WCAG exception the reviewer applied instead of writing a fix: 'decorative' (1.1.1 — image
        // conveys nothing, no text alternative required) or 'essential_exception' (1.4.5/1.4.9 —
        // a logo/brand mark is exempt). Recorded in the audit trail as WHY the finding is resolved.
        resolution: opts.resolution ?? null }),
    }).then(j))
// HITL review telemetry for the workspace dashboard — decisions by action, approval rate,
// edit rate (confidence-calibration signal), avg review time (reviewer-time-saved). Scan-scoped.
export const getHitlAnalytics = (scanId = null) => (SIM
  ? sim({ total: 0, by_action: {}, reviewed: 0, approval_rate: null, edit_rate: null, avg_review_ms: null })
  : fetch(`${BASE}/hitl/analytics${scanId ? `?scan_id=${encodeURIComponent(scanId)}` : ''}`, { headers: headers() }).then(j).catch(() => null))
// Draft a concrete fix value (alt text / link text / title) via the local AI model
// for one semantic finding. Reviewer accepts/edits it — never auto-applied here.
//
// `locator` names WHICH embedded image to describe (hitl_queue.evidence[].locator). Without it
// a 1.1.1 suggestion can only ever be a fill-in template: the endpoint has no image to hand a
// vision model, so the text model guesses from the filename. Omitted for the other criteria,
// which need no picture.
// `style` ('shorter' | 'detailed' | 'regenerate') lets a reviewer re-draft an image description at a
// different length (#131) — a bounded steer the backend allowlists; anything else is ignored.
// Second-opinion cross-check of a drafted alt text (#123): the model independently re-describes the
// image and we compare → {verdict: 'consistent'|'divergent', second_opinion, shared_terms}. {} when
// no image / model down / SIM. Never a score.
export const validateAlt = (scanId, file, ruleId, locator, alt) => (SIM || !alt
  ? sim({})
  : fetch(`${BASE}/ai/validate?scan_id=${encodeURIComponent(scanId)}&file=${encodeURIComponent(file)}&rule_id=${encodeURIComponent(ruleId)}&alt=${encodeURIComponent(alt)}`
      + (locator ? `&locator=${encodeURIComponent(locator)}` : ''),
      { headers: headers() }).then(j).catch(() => ({})))

export const suggestFix = (scanId, file, ruleId, locator = null, style = null) => (SIM
  ? sim({ suggestion: 'AI draft unavailable in demo mode — edit manually', kind: 'fix', is_template: true })
  : fetch(`${BASE}/ai/suggest?scan_id=${encodeURIComponent(scanId)}&file=${encodeURIComponent(file)}&rule_id=${encodeURIComponent(ruleId)}`
      + (locator ? `&locator=${encodeURIComponent(locator)}` : '')
      + (style ? `&style=${encodeURIComponent(style)}` : ''),
      { headers: headers() }).then(j))

// Re-download and re-score ONE file the user fixed externally. Returns {job_id} for polling.
export const rescoreFile = (scanId, file) => (SIM
  ? sim({ job_id: 'sim-rescore', workers: 1 }, 200)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/rescore?file=${encodeURIComponent(file)}`, { method: 'POST', headers: headers() }).then(j))
// Record a file (or files) as published back to its source. Body drives both forms.
export const publishFile = (scanId, file) => (SIM
  ? sim({ published: [{ file, published_at: new Date().toISOString() }] }, 150)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/publish`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ file }),
    }).then(j))
export const publishAllFiles = (scanId, files) => (SIM
  ? sim({ published: files.map((f) => ({ file: f, published_at: new Date().toISOString() })) }, 150)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/publish`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ files }),
    }).then(j))

// Queue state: depth by status + recent jobs (drives the in-app queue panel).
export const getJobs = (status = null) => (SIM
  ? sim({ workers: 4, stats: { done: 12, running: 1, queued: 3 }, dead_letters: { by_type: {}, top_errors: [] }, jobs: [
    { id: 'j1a2', type: 'remediate_file', status: 'running', scan_id: 'sim-all', payload: '{"file":"cardiology-policy.html"}', created_at: '2026-06-29T17:05:01Z', updated_at: '2026-06-29T17:05:04Z' },
    { id: 'j1a3', type: 'scan_file', status: 'done', scan_id: 'sim-all', payload: '{"file":"patient-intake-form.pdf"}', created_at: '2026-06-29T17:04:40Z', updated_at: '2026-06-29T17:04:43Z' },
    { id: 'j1a4', type: 'assess_trace', status: 'done', scan_id: 'sim-all', payload: '{}', created_at: '2026-06-29T17:04:10Z', updated_at: '2026-06-29T17:04:12Z' },
    { id: 'j1a5', type: 'scan_batch', status: 'queued', scan_id: 'sim-all', payload: '{"items":[]}', created_at: '2026-06-29T17:05:05Z', updated_at: '2026-06-29T17:05:05Z' },
  ] })
  : fetch(`${BASE}/jobs${status ? `?status=${status}` : ''}`, { headers: headers() }).then(j))
// Delete unrecoverable dead-lettered jobs (signed-in admins only).
export const clearDeadJobs = () => (SIM
  ? sim({ purged: 0 })
  : fetch(`${BASE}/admin/jobs/clear-dead`, { method: 'POST', headers: headers() }).then(j))
// Live-scale the in-process worker pool (0–16). Persisted server-side.
export const setWorkers = (count) => (SIM
  ? sim({ workers: count })
  : fetch(`${BASE}/workers?count=${count}`, { method: 'PUT', headers: headers() }).then(j))
// Reset demo data — clears scan results (Grafana) and/or Langfuse traces. Keeps settings.
export const resetDemoData = (scope = 'all') => (SIM
  ? sim({ scope, cleared_tables: [], langfuse_traces_deleted: 0 })
  : fetch(`${BASE}/admin/reset?scope=${scope}&confirm=true`, { method: 'POST', headers: headers() }).then(j))
export const listFolders = (parent = 'root') => (SIM ? sim({ parent, name: 'My Drive', folders: [] }) : fetch(`${BASE}/folders?parent=${encodeURIComponent(parent)}`, { headers: headers() }).then(j))
export const getSchedule = () => (SIM
  ? sim({ enabled: false, interval_minutes: 60, next_at: null, last_at: null })
  : fetch(`${BASE}/schedule`, { headers: headers() }).then(j))
export const putSchedule = (body) => (SIM
  ? sim({ ...body, next_at: null, last_at: null })
  : fetch(`${BASE}/schedule`, { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) }).then(j))

export const markRemediated = (scanId, file) => (SIM
  ? sim({ remediated_at: new Date().toISOString() })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/remediate`, { method: 'POST', headers: headers() }).then(j))

export const getFileContent = (scanId, file) => (SIM
  ? sim(null)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/content`, { headers: headers() }).then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.arrayBuffer() }))

// Page-1 preview image (ADR 0015). Resolves to a PNG Blob, or null when there's no preview
// (unsupported type, source unreachable, render failed, or SIM mode). NEVER rejects — a
// missing thumbnail must degrade silently, never surface as an error to the caller.
export const getFileThumbnail = (scanId, file) => (SIM
  ? sim(null)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/thumbnail`, { headers: headers() })
      .then(r => (r.ok ? r.blob() : null))
      .catch(() => null))
// Rendered PNG of page N — the "locate in document" evidence primitive. The backend clamps
// `page` to the document's range; null (→ placeholder) for non-PDF, SIM, or any failure.
export const getFilePage = (scanId, file, page = 1) => (SIM || !scanId
  ? sim(null)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/page/${page}`, { headers: headers() })
      .then(r => (r.ok ? r.blob() : null))
      .catch(() => null))

// Normalized bounding box {page,x,y,w,h} for the shape a finding's `part#rId` locator names —
// the rectangle the review card overlays on the page render (ADR 0018 Slice 2). null (→ no box,
// plain preview) for SIM, a non-pptx format, an unattributable shape, or any failure: a box is
// only ever a real measured rectangle (ADR 0016), never guessed.
export const getFileGeometry = (scanId, file, locator) => (SIM || !scanId || !file || !locator
  ? sim(null)
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/geometry?locator=${encodeURIComponent(locator)}`, { headers: headers() })
      .then(r => (r.ok ? r.json() : null))
      .then(d => (d && d.bbox) || null)
      .catch(() => null))

// ADR 0024 Tier B.1 — render-verified 1.4.3-hybrid contrast, ON DEMAND. With no locator the
// backend re-derives every text-over-picture/gradient shape and MEASURES each from real pixels,
// returning {measured:true, worst_ratio, any_fail_aa, shapes:[…], checked, total} or an honest
// {measured:false, reason:…}. Upgrades a 🟡 flag to a measured value; never a certified pass.
export const getFileContrast = (scanId, file) => (SIM || !scanId || !file
  ? sim({ measured: false, reason: 'unavailable' })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/verify-contrast`, { headers: headers() })
      .then(r => (r.ok ? r.json() : { measured: false, reason: 'error' }))
      .catch(() => ({ measured: false, reason: 'error' })))

// ADR 0024 Tier B.2 — render-verified 1.4.4 Resize Text, ON DEMAND. Renders each fixed-size
// (no-autofit) text box and MEASURES how much of it the text fills; enlarging to 200% needs ≥2×
// that height. Returns {measured:true, worst_fill, any_overflow_at_200, boxes:[…]} or an honest
// {measured:false, reason:…}. Upgrades a 🟡 flag to a measured overflow/headroom; never a pass.
export const getFileResize = (scanId, file) => (SIM || !scanId || !file
  ? sim({ measured: false, reason: 'unavailable' })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/verify-resize`, { headers: headers() })
      .then(r => (r.ok ? r.json() : { measured: false, reason: 'error' }))
      .catch(() => ({ measured: false, reason: 'error' })))

// ADR 0025 Tier B — render-verified 1.4.3 text-over-image contrast for PDF, ON DEMAND. The scan
// flags text sitting over a raster image (declared colour can't prove contrast there); this renders
// the page (pdfium, no LibreOffice) and MEASURES the text-vs-image contrast per run. Returns
// {measured:true, worst_ratio, any_fail_aa, runs:[…], checked, total} or {measured:false, reason:…}.
// Upgrades a 🟡 flag to a measured value; never a certified pass.
export const getFilePdfContrast = (scanId, file) => (SIM || !scanId || !file
  ? sim({ measured: false, reason: 'unavailable' })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/verify-pdf-contrast`, { headers: headers() })
      .then(r => (r.ok ? r.json() : { measured: false, reason: 'error' }))
      .catch(() => ({ measured: false, reason: 'error' })))

// ADR 0026 — the authoritative Accessibility Status for one file. Derived-at-read from the same
// certification facts the coverage matrix uses, so the hero card never disagrees with the detail.
// Returns the six-bucket model + coverage + state + one CTA, or {available:false}.
export const getFileStatus = (scanId, file) => (SIM
  ? sim({
      available: true, in_scope: 20, coverage: { evaluable: 18, total: 20 }, resolved: 16,
      automatically_verified: 16, human_verified: 0, needs_review: 2, needs_remediation: 0,
      not_automatically_assessable: 2, not_applicable: 0, unapplied_approved: 0,
      est_review_secs: 120, state: 'ready_after_review', cta: 'Review Findings',
    })
  : (!scanId || !file
      ? sim({ available: false })
      : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/status`, { headers: headers() })
          .then((r) => (r.ok ? r.json() : { available: false }))
          .catch(() => ({ available: false }))))

// ADR 0026 PR 3 — the scan-scope Accessibility Status: per-file models summed server-side, state
// re-derived over the totals. Powers the scan-level card + the Confidence Dashboard.
export const getScanStatus = (scanId) => (SIM
  ? sim({ available: true, scope: 'scan', documents: 12, in_scope: 240,
      coverage: { evaluable: 210, total: 240 }, resolved: 190,
      automatically_verified: 180, human_verified: 10, needs_review: 14, needs_remediation: 6,
      not_automatically_assessable: 30, not_applicable: 0, unapplied_approved: 0,
      est_review_secs: 630, state: 'needs_remediation', cta: 'Start Remediation' })
  : (!scanId ? sim({ available: false })
      : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/status`, { headers: headers() })
          .then((r) => (r.ok ? r.json() : { available: false }))
          .catch(() => ({ available: false }))))

// Examined-element denominators (ADR 0026 Epic 2): the engine-reported inventory counts from
// classify() at scan time — real walks, so "of N images examined" is a count, never an estimate.
export const getExamined = (scanId, file) => (SIM
  ? sim({ available: true, pages: 12, images: 18, has_text: true, is_scanned: false })
  : (!scanId || !file
      ? sim({ available: false })
      : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/examined`, { headers: headers() })
          .then((r) => (r.ok ? r.json() : { available: false }))
          .catch(() => ({ available: false }))))

// Confirm-the-pass (ADR 0026 / Epic 3): record a human's verification of a 🟡 review criterion.
// Writes the same immutable hitl.approved decision the review queue writes; the backend refuses
// anything whose outcome isn't REVIEW (a FAIL needs a fix, not a signature).
export const confirmCriterion = (scanId, file, sc, note) => (SIM || !scanId || !file
  ? sim({ ok: true, sc })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/files/${encodeURIComponent(file)}/confirm`, {
      method: 'POST', headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ sc, note }),
    }).then((r) => (r.ok ? r.json() : { ok: false, reason: 'error' }))
      .catch(() => ({ ok: false, reason: 'error' })))

export const uploadToDrive = (scanId, file, blob, contentType) => {
  if (SIM) return sim({ url: 'https://drive.google.com/file/d/sim/view', file_id: 'sim' })
  const fd = new FormData()
  fd.append('scan_id', scanId)
  fd.append('file', file)
  fd.append('blob', new File([blob], file, { type: contentType }))
  return fetch(`${BASE}/drive/upload`, { method: 'POST', headers: headers(), body: fd }).then(j)
}

export const explainFinding = (scanId, file, ruleId) => (SIM
  ? sim({ why: 'Screen readers cannot announce this element — blind users get no information about it.', fix: 'Add a descriptive alt attribute: <img src="logo.png" alt="Company logo">', model: 'llama3.2 (simulated)' })
  : fetch(`${BASE}/ai/explain?scan_id=${encodeURIComponent(scanId)}&file=${encodeURIComponent(file)}&rule_id=${encodeURIComponent(ruleId)}`, { headers: headers() }).then(j))

// SIM is the Netlify/offline build. Its AI, when keys are configured, is the serverless
// functions in frontend/netlify/functions — which POST to api.anthropic.com and
// api.openai.com. It is NOT a local backend, and must never claim to be: PrivateAiBadge
// renders its "no OpenAI/Anthropic, no external tokens" promise off `backend === 'ollama'`,
// so a fabricated 'ollama' here printed a false privacy guarantee on the one deployment
// that actually sends document content to a third party.
// The stub must carry EVERY field the panel reads, including the negative ones. It omitted
// vision_available and vision_unavailable_reason, and the Settings warning is gated on both —
// so on a Netlify preview the "genuine alt text is off" line could not render, and the panel
// looked healthy no matter what. On 2026-07-30 that read as a fix having worked: the button was
// clicked here, the warning vanished, and production still had the stale override pinned.
// A stub that answers fewer questions than the real endpoint reports good news it cannot know.
export const getAiStatus = () => (SIM
  ? sim({ available: false, base_url: null, model: null, vision_model: null, ai_enabled: true,
          backend: 'netlify-functions', model_available: false, vision_available: false,
          vision_unavailable_reason: 'this demo has no local Ollama — genuine image alt text needs one, '
                                    + 'so 1.1.1 findings get a fill-in template for a human to complete',
          config_source: { base_url: 'env', vision_model: 'env', model: 'env' } })
  : fetch(`${BASE}/ai/status`, { headers: headers() }).then(j))

// ── Disposition policies (ADR 0003 Phase 3) — admin-only lifecycle ────────────
// Policies are created DISABLED and approval-gated by default; delete is always
// Drive trash, never permanent. SIM keeps a tiny in-memory store so the whole
// create → enable → execute → approve loop is drivable in the demo.
const _simDisp = { policies: [], approvals: [], seq: 0 }
export const listDispositionPolicies = () => (SIM
  ? sim([..._simDisp.policies])
  : fetch(`${BASE}/disposition/policies`, { headers: headers() }).then(j))
export const createDispositionPolicy = (name, match, action, actionConfig = {}, requiresApproval = true) => (SIM
  ? sim((() => {
      const p = { policy_id: `sim-p${++_simDisp.seq}`, name, match: JSON.stringify(match), action,
                  action_config: JSON.stringify(actionConfig), requires_approval: requiresApproval ? 1 : 0, enabled: 0 }
      _simDisp.policies.push(p); return p
    })())
  : fetch(`${BASE}/disposition/policies`, {
      method: 'POST', headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ name, match, action, action_config: actionConfig, requires_approval: requiresApproval }),
    }).then(j))
export const setDispositionPolicyEnabled = (policyId, enabled) => (SIM
  ? sim((() => {
      const p = _simDisp.policies.find((x) => x.policy_id === policyId)
      if (p) p.enabled = enabled ? 1 : 0
      return p
    })())
  : fetch(`${BASE}/disposition/policies/${encodeURIComponent(policyId)}/enabled?enabled=${enabled}`, { method: 'PUT', headers: headers() }).then(j))
export const previewDispositionPolicy = (policyId) => (SIM
  ? sim({ policy_id: policyId, would_match: 3, documents: [
      { doc_id: 'drive:sim1', path: 'HR Handbook 2019.pdf', department: 'HR', age_days: 1460 },
      { doc_id: 'drive:sim2', path: 'Old Expense Policy.docx', department: 'Finance', age_days: 1220 },
      { doc_id: 'drive:sim3', path: 'Legacy Onboarding.pptx', department: 'HR', age_days: 1105 }] })
  : fetch(`${BASE}/disposition/policies/${encodeURIComponent(policyId)}/preview`, { method: 'POST', headers: headers() }).then(j))
export const executeDispositionPolicy = (policyId) => {
  if (SIM) {
    const p = _simDisp.policies.find((x) => x.policy_id === policyId)
    if (!p || !p.enabled) return Promise.reject(new Error('policy is disabled — enable it before executing'))
    const already = _simDisp.approvals.filter((a) => a.policy_id === policyId && a.result !== 'rejected').length
    let queued = 0
    if (p.requires_approval && already === 0) {
      ;['HR Handbook 2019.pdf', 'Old Expense Policy.docx', 'Legacy Onboarding.pptx'].forEach((f, i) => {
        _simDisp.approvals.push({ id: `sim-a${++_simDisp.seq}`, doc_id: `drive:sim${i + 1}`, policy_id: policyId,
                                  action: p.action, result: 'pending_approval',
                                  detail: `queued by policy '${p.name}' — awaiting approval (${f})` })
        queued += 1
      })
    }
    return sim({ policy_id: policyId, matched: 3, pending_approval: queued,
                 applied: 0, failed: 0, skipped: 3 - queued })
  }
  return fetch(`${BASE}/disposition/policies/${encodeURIComponent(policyId)}/execute`, { method: 'POST', headers: headers() }).then(j)
}
export const listDispositionApprovals = () => (SIM
  ? sim(_simDisp.approvals.filter((a) => a.result === 'pending_approval'))
  : fetch(`${BASE}/disposition/approvals`, { headers: headers() }).then(j))
export const approveDisposition = (auditId) => (SIM
  ? sim((() => { const a = _simDisp.approvals.find((x) => x.id === auditId); if (a) { a.result = 'applied'; a.detail = 'applied (simulated)' } return a })())
  : fetch(`${BASE}/disposition/approvals/${encodeURIComponent(auditId)}/approve`, { method: 'POST', headers: headers() }).then(j))
export const rejectDisposition = (auditId) => (SIM
  ? sim((() => { const a = _simDisp.approvals.find((x) => x.id === auditId); if (a) { a.result = 'rejected'; a.detail = 'declined by admin' } return a })())
  : fetch(`${BASE}/disposition/approvals/${encodeURIComponent(auditId)}/reject`, { method: 'POST', headers: headers() }).then(j))

export const listDispositionAudit = (limit = 100) => (SIM
  ? sim([..._simDisp.approvals].slice().reverse())
  : fetch(`${BASE}/disposition/audit?limit=${limit}`, { headers: headers() }).then(j))

export const queueHitlVerify = (scanId, file) => (SIM
  ? sim({ queued: 1 })
  : fetch(`${BASE}/hitl/queue/${encodeURIComponent(scanId)}/verify?file=${encodeURIComponent(file)}`, { method: 'POST', headers: headers() }).then(j))
