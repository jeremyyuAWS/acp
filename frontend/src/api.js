import { SIM, simIdentity, simGetSources, simStartScan, simGetJob, simGetScan, simListScans, simRules } from './sim.js'

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

const j = async (r) => {
  if (r.status === 401) {
    googleToken = null
    window.dispatchEvent(new CustomEvent('acp:session-expired'))
    throw new Error('Session expired — please sign in again')
  }
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const body = await r.json()
      if (body?.detail) detail = body.detail
    } catch (_) { /* body wasn't JSON */ }
    throw new Error(detail)
  }
  return r.json()
}
const sim = (value, ms = 220) => new Promise((res) => setTimeout(() => res(value), ms))

export const getConfig = () => (SIM ? sim({ google_client_id: null, auth: 'demo', sim: true, langfuse_trace_base: 'https://acp-langfuse.demo/project/acp-compliance/traces' }) : fetch(`${BASE}/config`).then(j))
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
    ai: true, model: 'claude-opus-4-8',
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
export const getScanTraces = (scanId) => {
  if (SIM) {
    const SCS = [['1.1.1', 'Images have alt text', 'A'], ['1.3.1', 'Info & relationships', 'A'], ['1.4.3', 'Contrast (minimum)', 'AA'], ['2.4.4', 'Link purpose', 'A'], ['2.4.6', 'Headings & labels', 'AA'], ['3.1.1', 'Language of page', 'A'], ['1.2.2', 'Captions', 'A'], ['4.1.2', 'Name, role, value', 'A'], ['2.4.7', 'Focus visible', 'AA'], ['1.4.11', 'Non-text contrast', 'AA'], ['3.3.2', 'Labels or instructions', 'A'], ['2.1.1', 'Keyboard', 'A']]
    const rows = []
    SCS.forEach(([id, name, level], k) => { for (let f = 0; f < 25; f++) { const r = (f * 7 + k * 3) % 10; const outcome = r < 2 ? 'SKIP' : (r < 5 ? 'FAIL' : 'PASS'); rows.push({ file: `doc-${f}.html`, rule_id: id, plain_name: name, level, outcome, finding_count: outcome === 'FAIL' ? r : 0 }) } })
    return sim(rows, 150)
  }
  return fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/traces`, { headers: headers() }).then(j)
}
export const getMe = () => (SIM ? sim(simIdentity()) : fetch(`${BASE}/me`, { headers: headers() }).then(j))
export const getSources = () => (SIM ? sim(simGetSources()) : fetch(`${BASE}/sources`, { headers: headers() }).then(j))
export const getRubric = () => (SIM
  ? sim({ name: 'WCAG 2.1 AA', version: '1', hash: 'e85fcf7e14f9040c', target: 'WCAG 2.1 AA', threshold: 90, criteria: {} })
  : fetch(`${BASE}/rubric`, { headers: headers() }).then(j))
export const getRules = () => (SIM ? sim(simRules()) : fetch(`${BASE}/rules`, { headers: headers() }).then(j))
export const updateRubric = (body) => (SIM
  ? sim({ hash: 'e85fcf7e14f9040c', disabled_rules: body.disabled_rules || [], threshold: body.compliant_threshold || 90 })
  : fetch(`${BASE}/rubric`, { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) }).then(j))
export const listScans = () => (SIM ? sim(simListScans()) : fetch(`${BASE}/scans`, { headers: headers() }).then(j))
// In-flight scan (for reconnecting after a reload). Returns {} when nothing is running.
export const getActiveScan = () => (SIM ? sim({}) : fetch(`${BASE}/scans/active`, { headers: headers() }).then(j))
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
export const updateSettings = (patch) => (SIM
  ? sim({ ai_enabled: true, drive_mirror_enabled: true, drive_mirror_folder: 'Remediated', ...patch })
  : fetch(`${BASE}/settings`, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(patch),
    }).then(j))
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

export const getAiStatus = () => (SIM
  ? sim({ available: true, base_url: 'http://localhost:11434', model: 'llama3.2' })
  : fetch(`${BASE}/ai/status`, { headers: headers() }).then(j))
