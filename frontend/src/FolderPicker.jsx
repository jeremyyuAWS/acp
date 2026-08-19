// Folder picker — a breadcrumb modal that drills into a source's folders and hands back the
// chosen ones. Used by the Sources tab (choose the locations a connection scans, saved on the
// connection) and by the Discover tab (narrow one scan).
//
// TWO THINGS IT DOES THAT THE SINGLE-FOLDER VERSION DID NOT:
//
// 1. MULTI-SELECT. A real estate is "HR and Finance", not "HR". Selecting one folder at a time
//    forced a choice between scanning too much and running several scans whose counts then have
//    to be added up by hand — and a count you assembled yourself has no boundary recorded on it.
//
// 2. PLUGGABLE LISTER. Drive lists through GET /folders; OneDrive and SharePoint list through
//    GET /sharepoint/folders. The drill-down, selection and "everything inside it" semantics are
//    identical, so they share this component rather than growing a second one that drifts.
//    Graph ids arrive already in `<driveId>/<itemId>` form because a Graph item id is unique only
//    within its drive — the picker never re-assembles that pair itself.
//
// Recursion is automatic server-side (_search_folder / _sp_walk_folder BFS), so there is no
// "include subfolders" toggle: it would be a choice whose wrong answer silently under-reports.
import { useState, useCallback, useEffect } from 'react'
import { listFolders } from './api.js'

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}

export default function FolderPicker({
  onScan, onClose, onConfirm,
  lister = listFolders,
  rootName = 'My Drive',
  initial = [],
  title = 'Choose folders to scan',
}) {
  const [stack, setStack] = useState([{ id: 'root', name: rootName }])
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  // The running selection, as {id, name} so a chip can NAME the folder. Ids alone would render
  // the chips as opaque Drive/Graph ids, which is not a boundary a reader can check a count
  // against — the same reason scanner resolves folder_name / site_name server-side.
  const [picked, setPicked] = useState(() => initial.map((f) => ({ id: f.id, name: f.name })))
  const current = stack[stack.length - 1]

  const load = useCallback((folderId) => {
    setLoading(true); setErr('')
    Promise.resolve(lister(folderId))
      .then((r) => setFolders(r.folders || []))
      .catch((e) => setErr(e.message || 'Failed to load folders'))
      .finally(() => setLoading(false))
  }, [lister])

  useEffect(() => { load(current.id) }, [current.id, load])

  const enter = (folder) => setStack((s) => [...s, folder])
  const goTo  = (idx)    => setStack((s) => s.slice(0, idx + 1))
  const isPicked = (id) => picked.some((p) => p.id === id)
  const toggle = (f) => setPicked((s) => (s.some((p) => p.id === f.id)
    ? s.filter((p) => p.id !== f.id)
    : [...s, { id: f.id, name: f.name }]))

  // Multi-select mode is what the Sources tab uses; Discover still passes onScan and gets the
  // one-folder behaviour it always had, so that call site is unchanged by this growing a mode.
  const multi = typeof onConfirm === 'function'

  return (
    <div className="setoverlay" onClick={onClose}>
      <div className="setpanel" style={{ maxWidth: 480, width: '100%', padding: '24px 28px 28px' }}
           onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <span style={{ fontSize: 15, fontWeight: 650, letterSpacing: '-0.01em' }}>{title}</span>
          <button className="small ghost" onClick={onClose} aria-label="Close"
                  style={{ lineHeight: 1, padding: '4px 8px', fontSize: 16, marginRight: -4 }}>✕</button>
        </div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, marginBottom: 10,
                      flexWrap: 'wrap', color: 'var(--muted)', paddingBottom: 10,
                      borderBottom: '1px solid var(--line)' }}>
          {stack.map((f, i) => (
            <span key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {i > 0 && <span>›</span>}
              <button style={{ background: 'none', border: 'none', padding: 0, fontSize: 12,
                cursor: i < stack.length - 1 ? 'pointer' : 'default',
                color: i < stack.length - 1 ? 'var(--accent)' : 'var(--ink)',
                fontWeight: i === stack.length - 1 ? 600 : 400 }}
                onClick={() => i < stack.length - 1 && goTo(i)}>
                {f.name}
              </button>
            </span>
          ))}
        </div>

        {/* Folder list */}
        <div style={{ minHeight: 140, maxHeight: 300, overflowY: 'auto',
                      border: '1px solid var(--line)', borderRadius: 10, marginBottom: 14 }}>
          {loading && (
            <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              Loading…
            </div>
          )}
          {err && (
            <div style={{ padding: '20px 18px', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <span style={{ fontSize: 18, lineHeight: 1 }}>⚠️</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 4 }}>
                  Could not load folders
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>{err}</div>
              </div>
            </div>
          )}
          {!loading && !err && folders.length === 0 && (
            <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              No subfolders here
            </div>
          )}
          {!loading && !err && folders.map((f, idx) => (
            <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 10,
              padding: '11px 18px', fontSize: 13,
              borderBottom: idx < folders.length - 1 ? '1px solid var(--line)' : 'none' }}>
              {multi && (
                // Selecting and drilling in are DIFFERENT actions on the same row, so they get
                // different targets. One control doing both is the picker bug where opening a
                // folder to look inside it silently changes what you are about to scan.
                <input type="checkbox" checked={isPicked(f.id)} onChange={() => toggle(f)}
                       aria-label={`Select ${f.name}`} style={{ cursor: 'pointer' }} />
              )}
              <button style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1,
                background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
                fontSize: 13, padding: 0 }}
                onClick={() => (multi ? enter(f) : enter(f))}>
                <FolderIcon />
                <span style={{ flex: 1, color: 'var(--ink)', fontWeight: 500 }}>{f.name}</span>
                <span style={{ color: 'var(--ink)', fontSize: 15 }}>›</span>
              </button>
            </div>
          ))}
        </div>

        {/* The running selection, named. Rendered even when EMPTY, saying what empty means —
            "nothing selected" and "everything" are the same screen otherwise, and the reassuring
            reading of a blank picker is the wrong one. */}
        {multi && (
          <div style={{ marginBottom: 14 }}>
            {picked.length === 0 ? (
              <div className="muted" style={{ fontSize: 12.5 }}>
                Nothing selected — this source scans <strong>all of {rootName}</strong>.
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <span className="muted" style={{ fontSize: 12.5 }}>Scanning:</span>
                {picked.map((f) => (
                  <span key={f.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
                    fontSize: 12, background: '#F1EFF3', border: '1px solid var(--line)',
                    borderRadius: 999, padding: '3px 8px' }}>
                    📁 {f.name}
                    <button className="linklike" aria-label={`Remove ${f.name}`}
                            style={{ fontSize: 13, lineHeight: 1 }}
                            onClick={() => toggle(f)}>✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Recursion note */}
        <div style={{ fontSize: 12.5, color: 'var(--ink)', marginBottom: 14,
                      background: '#F1EFF3', border: '1px solid var(--line)', borderRadius: 8,
                      padding: '9px 12px', display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.4 }}>
          <span aria-hidden="true" style={{ fontSize: 14 }}>↳</span>
          <span>Scans the chosen folder{multi ? 's' : ''} <strong>and everything inside</strong> — all subfolders, recursively.</span>
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {multi ? (
            <>
              <button className="ghost small" onClick={() => onConfirm([])}>Scan all of {rootName}</button>
              <button onClick={() => onConfirm(picked)}>
                {picked.length ? `Save ${picked.length} location${picked.length === 1 ? '' : 's'}` : 'Save'}
              </button>
            </>
          ) : (
            <>
              <button className="ghost small" onClick={() => onScan(null)}>Scan all of {rootName}</button>
              <button onClick={() => onScan(current.id === 'root' ? null : current.id)}>
                Scan "{current.name}" + subfolders
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
