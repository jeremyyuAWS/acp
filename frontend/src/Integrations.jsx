import { useState, useEffect, useCallback } from 'react'
import { listFolders } from './api.js'
import { SIM } from './sim.js'
import SourceDrawer from './SourceDrawer.jsx'
import FileDrawer from './FileDrawer.jsx'

// Unified compliance across sources. The simulated estate connects several content
// stores; the mova Agent monitors each continuously. (Demo data — no real connections.)

function DriveMark() {
  return (
    <svg viewBox="0 0 87 78" width="24" height="24" aria-hidden="true">
      <path fill="#0066da" d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" />
      <path fill="#00ac47" d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9 9 0 0 0-1.2 4.5h27.5z" />
      <path fill="#ea4335" d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.85 11.5z" />
      <path fill="#00832d" d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" />
      <path fill="#2684fc" d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
      <path fill="#ffba00" d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" />
    </svg>
  )
}
const Tile = ({ bg, children }) => <span style={{ width: 40, height: 40, borderRadius: 10, background: bg, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', flex: '0 0 auto' }}>{children}</span>
const G = (d) => <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
const LOGO = {
  google_drive: <Tile bg="#fff"><DriveMark /></Tile>,
  sharepoint: <Tile bg="#036C70"><b style={{ fontSize: 15 }}>S</b></Tile>,
  confluence: <Tile bg="#1868DB"><b style={{ fontSize: 15 }}>C</b></Tile>,
  box: <Tile bg="#0061D5"><b style={{ fontSize: 12 }}>box</b></Tile>,
  web: <Tile bg="#5F6B7A">{G('M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c2.5 2.5 2.5 15.5 0 18M12 3c-2.5 2.5-2.5 15.5 0 18')}</Tile>,
}
const FUTURE_ALL = [
  { name: 'SharePoint', logo: <Tile bg="#036C70"><b style={{ fontSize: 15 }}>S</b></Tile> },
  { name: 'OneDrive', logo: <Tile bg="#0364B8">{G('M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6-1.5A3.5 3.5 0 0 1 19 18z')}</Tile> },
  { name: 'File Shares', logo: <Tile bg="#E8A400">{G('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z')}</Tile> },
  { name: 'S3 / Blob', logo: <Tile bg="#2E72C9"><b style={{ fontSize: 12 }}>S3</b></Tile> },
]

// Synthetic OneDrive source card shown when the user has an MS token.
const SP_SOURCE = {
  id: 'sp-root',
  type: 'sharepoint',
  name: 'OneDrive',
  files: null,
  access: 'read-only',
}

// ── Folder picker modal ────────────────────────────────────────────────────────

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}

function FolderPicker({ onScan, onClose }) {
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
  const goTo = (idx) => setStack((s) => s.slice(0, idx + 1))

  return (
    <div className="setoverlay" onClick={onClose}>
      <div className="setpanel" style={{ maxWidth: 460, width: '100%' }} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Choose a folder to scan">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <strong>Choose a folder to scan</strong>
          <button className="small ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, marginBottom: 10, flexWrap: 'wrap' }}>
          {stack.map((f, i) => (
            <span key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {i > 0 && <span style={{ color: 'var(--muted)' }}>›</span>}
              <button
                style={{ background: 'none', border: 'none', cursor: i < stack.length - 1 ? 'pointer' : 'default',
                  color: i < stack.length - 1 ? 'var(--accent)' : 'inherit', fontWeight: i === stack.length - 1 ? 600 : 400, padding: 0 }}
                onClick={() => i < stack.length - 1 && goTo(i)}
              >
                {f.name}
              </button>
            </span>
          ))}
        </div>

        {/* Folder list */}
        <div style={{ minHeight: 120, maxHeight: 280, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, marginBottom: 14 }}>
          {loading && <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>Loading…</div>}
          {err && <div style={{ padding: '16px', color: '#A32D2D', fontSize: 13 }}>{err}</div>}
          {!loading && !err && folders.length === 0 && (
            <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>No subfolders in this location</div>
          )}
          {!loading && folders.map((f) => (
            <button
              key={f.id}
              style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '9px 14px', background: 'none',
                border: 'none', borderBottom: '1px solid var(--border)', cursor: 'pointer', textAlign: 'left', fontSize: 13 }}
              onClick={() => enter(f)}
            >
              <FolderIcon /> {f.name}
              <span style={{ marginLeft: 'auto', color: 'var(--muted)' }}>›</span>
            </button>
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button className="ghost small" onClick={() => onScan(null)}>
            Scan all of My Drive
          </button>
          <button onClick={() => onScan(current.id === 'root' ? null : current.id)}>
            Scan "{current.name}"
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Integrations({ sources, files = [], onScan, busy, hasSPToken }) {
  const [selSrc, setSelSrc] = useState(null)
  const [selFile, setSelFile] = useState(null)
  const [pickerSrc, setPickerSrc] = useState(null)

  // Merge in OneDrive source card when user has an MS token
  const allSources = hasSPToken ? [...sources, SP_SOURCE] : sources
  const FUTURE = hasSPToken
    ? FUTURE_ALL.filter((s) => s.name !== 'SharePoint' && s.name !== 'OneDrive')
    : FUTURE_ALL

  const total = sources.reduce((a, s) => a + (s.files || 0), 0)

  const handleScan = (srcId) => {
    if (SIM) { onScan(srcId); return }
    const src = allSources.find((s) => s.id === srcId)
    if (src?.type === 'sharepoint') { onScan('sharepoint'); return }
    if (src?.type === 'google_drive') { setPickerSrc(src); return }
    onScan(srcId)
  }

  const handlePickerScan = (folder) => {
    setPickerSrc(null)
    onScan('drive', folder)
  }

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{allSources.length} sources</b> · {total.toLocaleString()} documents under continuous compliance monitoring
          <div className="muted" style={{ marginTop: 2 }}>the mova Agent discovers, classifies, and re-scans across every store</div>
        </div>
        <button disabled={busy} onClick={() => SIM ? onScan('all') : handleScan(allSources[0]?.id)}>{busy ? 'scanning…' : 'Scan all sources'}</button>
      </div>
      <div className="intgrid">
        {allSources.map((s) => (
          <div className="intcard clickable" key={s.id} onClick={() => setSelSrc(s)}>
            <button className="intcard-body" onClick={() => setSelSrc(s)} aria-label={`${s.name} — ${s.files != null ? s.files.toLocaleString() : 'connected'}`}>
              <div className="intlogo" aria-hidden="true">{LOGO[s.type] || LOGO.web}</div>
              <div className="intname">{s.name}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                {s.user ? `${s.user} · ` : ''}{s.files != null ? `${s.files.toLocaleString()} scannable files` : 'ready to scan'}
              </div>
              <span className="intstatus live"><span className="livedot" aria-hidden="true" />connected · read-only</span>
            </button>
            <button className="intbtn" disabled={busy} onClick={(e) => { e.stopPropagation(); handleScan(s.id) }}>
              {busy ? 'scanning…' : 'Run scan'}
            </button>
          </div>
        ))}
        {FUTURE.map((s) => (
          <div className="intcard off" key={s.name} aria-hidden="true">
            <div className="intlogo">{s.logo}</div>
            <div className="intname">{s.name}</div>
            <span className="intstatus">coming soon</span>
            <button className="intbtn ghost" disabled>Connect</button>
          </div>
        ))}
      </div>

      {pickerSrc && !busy && (
        <FolderPicker
          onScan={handlePickerScan}
          onClose={() => setPickerSrc(null)}
        />
      )}

      {selSrc && <SourceDrawer source={selSrc} files={files.filter((f) => f.source === selSrc.id)} onClose={() => setSelSrc(null)} onPickFile={setSelFile} />}
      {selFile && <FileDrawer file={selFile} onClose={() => setSelFile(null)} />}
    </>
  )
}
