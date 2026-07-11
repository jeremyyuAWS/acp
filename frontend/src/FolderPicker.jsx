// Google Drive folder picker — a breadcrumb modal that drills into the user's Drive folders
// (GET /folders?parent=<id>, listFolders) and hands back the chosen folder id (or null for the
// whole Drive) to onScan. Shared by the Integrations tab and the Discover tab so both offer the
// same "choose exactly what to scan" experience. Recursion is automatic server-side
// (_search_folder BFS), so there is no "include subfolders" toggle to pass.
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

export default function FolderPicker({ onScan, onClose }) {
  const [stack, setStack] = useState([{ id: 'root', name: 'My Drive' }])
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const current = stack[stack.length - 1]

  const load = useCallback((folderId) => {
    setLoading(true); setErr('')
    listFolders(folderId)
      .then((r) => setFolders(r.folders || []))
      .catch((e) => setErr(e.message || 'Failed to load folders'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(current.id) }, [current.id, load])

  const enter = (folder) => setStack((s) => [...s, folder])
  const goTo  = (idx)    => setStack((s) => s.slice(0, idx + 1))

  return (
    <div className="setoverlay" onClick={onClose}>
      <div className="setpanel" style={{ maxWidth: 480, width: '100%', padding: '24px 28px 28px' }}
           onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Choose a folder to scan">

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <span style={{ fontSize: 15, fontWeight: 650, letterSpacing: '-0.01em' }}>Choose a folder to scan</span>
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
                      border: '1px solid var(--line)', borderRadius: 10, marginBottom: 20 }}>
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
            <button key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%',
              padding: '11px 18px', background: 'none', border: 'none', cursor: 'pointer',
              textAlign: 'left', fontSize: 13,
              borderBottom: idx < folders.length - 1 ? '1px solid var(--line)' : 'none' }}
              onMouseEnter={(e) => e.currentTarget.style.background = 'var(--hover, rgba(0,0,0,.04))'}
              onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
              onClick={() => enter(f)}>
              <FolderIcon />
              <span style={{ flex: 1, color: 'var(--ink)', fontWeight: 500 }}>{f.name}</span>
              <span style={{ color: 'var(--ink)', fontSize: 15 }}>›</span>
            </button>
          ))}
        </div>

        {/* Recursion note */}
        <div style={{ fontSize: 12.5, color: 'var(--ink)', marginBottom: 14,
                      background: '#F1EFF3', border: '1px solid var(--line)', borderRadius: 8,
                      padding: '9px 12px', display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.4 }}>
          <span aria-hidden="true" style={{ fontSize: 14 }}>↳</span>
          <span>Scans the chosen folder <strong>and everything inside it</strong> — all subfolders, recursively.</span>
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button className="ghost small" onClick={() => onScan(null)}>Scan all of My Drive</button>
          <button onClick={() => onScan(current.id === 'root' ? null : current.id)}>
            Scan "{current.name}" + subfolders
          </button>
        </div>
      </div>
    </div>
  )
}
