const BASE = import.meta.env.VITE_API ?? 'http://localhost:8077'

const j = (r) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export const getMe = () => fetch(`${BASE}/me`).then(j)
export const getSources = () => fetch(`${BASE}/sources`).then(j)
export const getRubric = () => fetch(`${BASE}/rubric`).then(j)
export const listScans = () => fetch(`${BASE}/scans`).then(j)
export const getScan = (id) => fetch(`${BASE}/scans/${id}`).then(j)
export const getInventory = () => fetch(`${BASE}/inventory`).then(j)
export const runScan = (source = 'local') =>
  fetch(`${BASE}/scans?source=${source}`, { method: 'POST' }).then(j)
