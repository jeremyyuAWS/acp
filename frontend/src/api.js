import { SIM, simIdentity, simGetSources, simStartScan, simGetJob, simGetScan, simListScans, simRules } from './sim.js'

const BASE = import.meta.env.VITE_API ?? 'http://localhost:8077'

// Per-user tokens (real mode only). In SIM mode nothing touches a real Drive / OneDrive.
let driveToken = null
let spToken = null
export const setDriveToken = (t) => { driveToken = t }
export const setSPToken = (t) => { spToken = t }
const headers = (extra = {}) => ({
  ...extra,
  ...(driveToken ? { 'X-Drive-Token': driveToken } : {}),
  ...(spToken ? { 'X-SP-Token': spToken } : {}),
})

const j = (r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json() }
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
export const startScan = (source = 'local', folder = null) => (SIM ? sim(simStartScan(source), 120) : fetch(`${BASE}/scans?source=${source}${folder ? `&folder=${encodeURIComponent(folder)}` : ''}`, { method: 'POST', headers: headers() }).then(j))
export const getJob = (id) => (SIM ? sim(simGetJob(id), 60) : fetch(`${BASE}/scans/jobs/${id}`, { headers: headers() }).then(j))
export const listFolders = (parent = 'root') => (SIM ? sim({ parent, name: 'My Drive', folders: [] }) : fetch(`${BASE}/folders?parent=${encodeURIComponent(parent)}`, { headers: headers() }).then(j))
