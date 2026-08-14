// Persist the AI Work Inbox's VIEW controls — search, the severity/criterion filters, and the
// group-by-file toggle — so a reviewer who leaves the Remediate tab and comes back (the component
// unmounts and remounts, resetting its useState) lands where they were instead of on a reset
// queue. Scoped per scan (keyed by run id) so two scans don't share a filter, and held in
// sessionStorage so it lasts the working session and no longer.
//
// The single OPEN finding (`openId`) IS persisted — the review queue is a single-open accordion, so
// restoring which one finding the reviewer had open lands them back on the finding they were working,
// which is the real papercut. (This replaces the old per-card collapse MAP, which was deliberately
// not persisted because restoring a stale multi-open map fought the fresh-collapsed seeding.)

const PREFIX = 'acp:inbox:'
const DEFAULTS = { query: '', severity: null, criterion: null, groupByFile: false, openId: null }

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
      openId: p.openId != null ? p.openId : null,
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
      openId: (prefs && prefs.openId != null) ? prefs.openId : null,
    }))
  } catch { /* storage full or disabled — persistence is a nicety, never fatal */ }
}
