// Persist the AI Work Inbox's VIEW controls — search, the severity/criterion filters, and the
// group-by-file toggle — so a reviewer who leaves the Remediate tab and comes back (the component
// unmounts and remounts, resetting its useState) lands where they were instead of on a reset
// queue. Scoped per scan (keyed by run id) so two scans don't share a filter, and held in
// sessionStorage so it lasts the working session and no longer.
//
// The per-card COLLAPSE map is deliberately NOT persisted: cards are seeded fresh (collapsed) on
// each mount, and restoring a stale collapse map would fight that seeding for no real gain. This
// module carries only the view controls, which are cheap, safe to restore, and the actual papercut.

const PREFIX = 'acp:inbox:'
const DEFAULTS = { query: '', severity: null, criterion: null, groupByFile: false }

export function inboxPrefsKey(runId) {
  return PREFIX + (runId || 'none')
}

function _session(storage) {
  if (storage) return storage
  try { return typeof sessionStorage !== 'undefined' ? sessionStorage : null } catch { return null }
}

export function loadInboxPrefs(runId, storage) {
  const store = _session(storage)
  if (!store) return { ...DEFAULTS }
  try {
    const raw = store.getItem(inboxPrefsKey(runId))
    if (!raw) return { ...DEFAULTS }
    const p = JSON.parse(raw) || {}
    return {
      query: typeof p.query === 'string' ? p.query : '',
      severity: p.severity || null,
      criterion: p.criterion || null,
      groupByFile: !!p.groupByFile,
    }
  } catch { return { ...DEFAULTS } }
}

export function saveInboxPrefs(runId, prefs, storage) {
  const store = _session(storage)
  if (!store) return
  try {
    store.setItem(inboxPrefsKey(runId), JSON.stringify({
      query: (prefs && prefs.query) || '',
      severity: (prefs && prefs.severity) || null,
      criterion: (prefs && prefs.criterion) || null,
      groupByFile: !!(prefs && prefs.groupByFile),
    }))
  } catch { /* storage full or disabled — persistence is a nicety, never fatal */ }
}
