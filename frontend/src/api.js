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

export const getConfig = () => (SIM ? sim({ google_client_id: null, auth: 'demo', sim: true }) : fetch(`${BASE}/config`).then(j))
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
export const getScan = (id) => (SIM ? sim(simGetScan(id)) : fetch(`${BASE}/scans/${id}`, { headers: headers() }).then(j))
export const getInventory = () => (SIM ? sim([]) : fetch(`${BASE}/inventory`, { headers: headers() }).then(j))
export const reportUrl = (id) => (SIM ? '#' : `${BASE}/scans/${id}/report.pdf`)
export const startScan = (source = 'local', folder = null, aiEnabled = true, pii = true) => (SIM ? sim(simStartScan(source), 120) : fetch(`${BASE}/scans?source=${source}${folder ? `&folder=${encodeURIComponent(folder)}` : ''}&ai=${aiEnabled}&pii=${pii}`, { method: 'POST', headers: headers() }).then(j))
export const getJob = (id) => (SIM ? sim(simGetJob(id), 60) : fetch(`${BASE}/scans/jobs/${id}`, { headers: headers() }).then(j))

// ── Durable async queue (ADR 0004/0005) ───────────────────────────────────────
// Queued scan: runs in the worker pool, survives restarts, shows in /jobs + Grafana.
export const startScanQueued = (source = 'local', folder = null, aiEnabled = true, pii = true) => (SIM
  ? sim({ scan_id: 'sim-scan', job_id: 'sim-job', queued: true, workers: 4 })
  : fetch(`${BASE}/scans?source=${source}${folder ? `&folder=${encodeURIComponent(folder)}` : ''}&ai=${aiEnabled}&pii=${pii}&queue=true`, { method: 'POST', headers: headers() }).then(j))
// Async server-side remediation: one remediate_file job per HTML file in the scan.
export const remediateScan = (scanId) => (SIM
  ? sim({ scan_id: scanId, enqueued: 3, job_ids: ['a', 'b', 'c'], workers: 4 })
  : fetch(`${BASE}/scans/${encodeURIComponent(scanId)}/remediate`, { method: 'POST', headers: headers() }).then(j))
// Queue state: depth by status + recent jobs (drives the in-app queue panel).
export const getJobs = (status = null) => (SIM
  ? sim({ workers: 4, stats: { done: 12, running: 1, queued: 3 }, jobs: [] })
  : fetch(`${BASE}/jobs${status ? `?status=${status}` : ''}`, { headers: headers() }).then(j))
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
