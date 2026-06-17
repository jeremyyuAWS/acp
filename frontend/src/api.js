const BASE = import.meta.env.VITE_API ?? 'http://localhost:8077'

// Per-user Drive access token from GIS "Sign in with Google" (demo mode: stays null
// and the server falls back to its ADC identity).
let driveToken = null
export const setDriveToken = (t) => { driveToken = t }

const headers = (extra = {}) => ({ ...extra, ...(driveToken ? { 'X-Drive-Token': driveToken } : {}) })

const j = (r) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const getConfig = () => fetch(`${BASE}/config`).then(j)
export const getMe = () => fetch(`${BASE}/me`, { headers: headers() }).then(j)
export const getSources = () => fetch(`${BASE}/sources`, { headers: headers() }).then(j)
export const getRubric = () => fetch(`${BASE}/rubric`, { headers: headers() }).then(j)
export const getRules = () => fetch(`${BASE}/rules`, { headers: headers() }).then(j)
export const updateRubric = (body) =>
  fetch(`${BASE}/rubric`, { method: 'PUT', headers: headers({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) }).then(j)
export const listScans = () => fetch(`${BASE}/scans`, { headers: headers() }).then(j)
export const getScan = (id) => fetch(`${BASE}/scans/${id}`, { headers: headers() }).then(j)
export const getInventory = () => fetch(`${BASE}/inventory`, { headers: headers() }).then(j)
export const reportUrl = (id) => `${BASE}/scans/${id}/report.pdf`
export const startScan = (source = 'local') =>
  fetch(`${BASE}/scans?source=${source}`, { method: 'POST', headers: headers() }).then(j)
export const getJob = (id) => fetch(`${BASE}/scans/jobs/${id}`, { headers: headers() }).then(j)
