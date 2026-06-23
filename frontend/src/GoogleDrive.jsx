import React, { useState, useEffect, useRef, useCallback } from 'react'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
const SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'

// Google Workspace native types that need server-side export to a binary format
const GDOC_EXPORT = {
  'application/vnd.google-apps.document': {
    ext: '.docx',
    mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  },
  'application/vnd.google-apps.spreadsheet': {
    ext: '.xlsx',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  },
  'application/vnd.google-apps.presentation': {
    ext: '.pptx',
    mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  },
}

const NATIVE_MIMES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/html',
]

const ALL_MIMES = [...NATIVE_MIMES, ...Object.keys(GDOC_EXPORT)]
const DRIVE_Q_BASE = '(' + ALL_MIMES.map(m => "mimeType='" + m + "'").join(' or ') + ') and trashed=false'

const FILE_ICON = {
  'application/pdf': '📄',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '📝',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': '📊',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '📗',
  'text/html': '🌐',
  'application/vnd.google-apps.document': '📝',
  'application/vnd.google-apps.spreadsheet': '📗',
  'application/vnd.google-apps.presentation': '📊',
}

const FILE_LABEL = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPT',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
  'text/html': 'HTML',
  'application/vnd.google-apps.document': 'Google Doc',
  'application/vnd.google-apps.spreadsheet': 'Google Sheet',
  'application/vnd.google-apps.presentation': 'Google Slide',
}

function fmtDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}


// Exported so batch queue rows can offer "Save back to Drive" after remediation.
export function DriveUploadButton({ driveFileId, blob }) {
  const [status, setStatus] = React.useState('idle')
  const save = async () => {
    const token = sessionStorage.getItem('gd_token')
    if (!token) { setStatus('no-token'); return }
    setStatus('saving')
    try {
      const r = await fetch(
        'https://www.googleapis.com/upload/drive/v3/files/' + driveFileId + '?uploadType=media',
        { method: 'PATCH', headers: { Authorization: 'Bearer ' + token, 'Content-Type': blob.type }, body: blob }
      )
      if (r.status === 401 || r.status === 403) { setStatus('no-token'); return }
      if (!r.ok) throw new Error('HTTP ' + r.status)
      setStatus('done')
    } catch { setStatus('error') }
  }
  if (status === 'done') return React.createElement('span', { style: { color: '#3B6D11', fontSize: 12, flexShrink: 0 } }, '✓ Saved to Drive')
  if (status === 'error') return React.createElement('span', { style: { color: '#854F0B', fontSize: 12, flexShrink: 0 } }, '✕ Upload failed')
  if (status === 'no-token') return React.createElement('span', { style: { color: '#854F0B', fontSize: 12, flexShrink: 0 } }, 'Reconnect Drive to save')
  return React.createElement('button', {
    className: 'ghost small',
    onClick: save,
    disabled: status === 'saving',
    style: { flexShrink: 0, fontSize: 12, padding: '2px 8px' }
  }, status === 'saving' ? '↑ Saving…' : '↑ Drive')
}

export default function GoogleDrive({ onFiles }) {
  const tokenClient = useRef(null)
  const [token, setToken] = useState(() => sessionStorage.getItem('gd_token') || null)
  const [user, setUser] = useState(() => { try { return JSON.parse(sessionStorage.getItem('gd_user') || 'null') } catch { return null } })
  const [files, setFiles] = useState([])
  const [nextPage, setNextPage] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [downloading, setDownloading] = useState(false)
  const [dlProgress, setDlProgress] = useState(null)
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)

  const fetchFiles = useCallback(async (tok, pageToken, searchTerm) => {
    setLoading(true)
    setError(null)
    try {
      let q = DRIVE_Q_BASE
      const term = (searchTerm || '').trim()
      if (term) q = "name contains '" + term.replace(/'/g, "\\'") + "' and " + q
      const params = new URLSearchParams({
        q,
        fields: 'nextPageToken,files(id,name,mimeType,size,modifiedTime,owners)',
        pageSize: '50',
        orderBy: 'modifiedTime desc',
      })
      if (pageToken) params.set('pageToken', pageToken)
      const r = await fetch('https://www.googleapis.com/drive/v3/files?' + params, {
        headers: { Authorization: 'Bearer ' + tok },
      })
      if (r.status === 401) {
        setToken(null); sessionStorage.removeItem('gd_token'); return
      }
      const data = await r.json()
      if (data.error) { setError(data.error.message); return }
      setFiles(prev => pageToken ? [...prev, ...(data.files || [])] : (data.files || []))
      setNextPage(data.nextPageToken || null)
    } catch {
      setError('Could not load Drive files. Check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  // Auto-load on connect
  useEffect(() => {
    if (token) fetchFiles(token, null, '')
  }, [token, fetchFiles])

  // Wire GIS token client once the script loads
  useEffect(() => {
    if (!CLIENT_ID || !window.google?.accounts?.oauth2 || tokenClient.current) return
    tokenClient.current = window.google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: SCOPES,
      callback: async (resp) => {
        if (resp.error) { setError(resp.error_description || resp.error); return }
        const tok = resp.access_token
        setToken(tok)
        sessionStorage.setItem('gd_token', tok)
        try {
          const ur = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
            headers: { Authorization: 'Bearer ' + tok },
          })
          const u = await ur.json()
          setUser(u)
          sessionStorage.setItem('gd_user', JSON.stringify(u))
        } catch {}
        setOpen(true)
        fetchFiles(tok, null, '')
      },
    })
  })

  const connect = () => {
    if (!CLIENT_ID) {
      setError('Add VITE_GOOGLE_CLIENT_ID=<your-client-id> to frontend/.env, then restart the dev server.')
      return
    }
    if (!window.google?.accounts?.oauth2) {
      setError('Google Identity Services is still loading — try again in a moment.')
      return
    }
    setError(null)
    tokenClient.current?.requestAccessToken()
  }

  const disconnect = () => {
    if (token) window.google?.accounts?.oauth2?.revoke(token)
    setToken(null); setUser(null); setFiles([]); setSelected(new Set())
    sessionStorage.removeItem('gd_token'); sessionStorage.removeItem('gd_user')
    setOpen(false)
  }

  const toggle = (id) => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const toggleAll = () => setSelected(s => s.size === files.length && files.length > 0 ? new Set() : new Set(files.map(f => f.id)))

  const downloadAndScan = async () => {
    const toScan = files.filter(f => selected.has(f.id))
    if (!toScan.length) return
    setDownloading(true)
    const fileObjects = []
    for (let i = 0; i < toScan.length; i++) {
      const f = toScan[i]
      setDlProgress('Downloading ' + (i + 1) + ' / ' + toScan.length + ': ' + f.name)
      try {
        const exp = GDOC_EXPORT[f.mimeType]
        const url = exp
          ? 'https://www.googleapis.com/drive/v3/files/' + f.id + '/export?mimeType=' + encodeURIComponent(exp.mime)
          : 'https://www.googleapis.com/drive/v3/files/' + f.id + '?alt=media'
        const name = exp ? (f.name.endsWith(exp.ext) ? f.name : f.name + exp.ext) : f.name
        const r = await fetch(url, { headers: { Authorization: 'Bearer ' + token } })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const blob = await r.blob()
        const fileObj = new File([blob], name, { type: exp ? exp.mime : (blob.type || f.mimeType) })
        fileObj._driveId = f.id
        fileObj._driveName = f.name
        fileObjects.push(fileObj)
      } catch (e) {
        console.error('Drive download failed:', f.name, e)
      }
    }
    setDownloading(false); setDlProgress(null)
    if (fileObjects.length) { onFiles(fileObjects); setSelected(new Set()); setOpen(false) }
  }

  // ── NOT CONNECTED ──────────────────────────────────────────────────────────
  if (!token) {
    return (
      <div style={{ marginTop: 12 }}>
        <button className="ghost small" onClick={connect} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <img src="https://www.gstatic.com/images/branding/googleg/1x/googleg_standard_color_16dp.png" alt="" width={14} height={14} />
          Connect Google Drive
        </button>
        {error && <p style={{ color: '#854F0B', fontSize: 12, marginTop: 6, marginBottom: 0 }}>{error}</p>}
      </div>
    )
  }

  // ── CONNECTED ──────────────────────────────────────────────────────────────
  return (
    <div style={{ marginTop: 12 }}>
      {/* Account bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: open ? 8 : 0 }}>
        <img src="https://www.gstatic.com/images/branding/googleg/1x/googleg_standard_color_16dp.png" alt="" width={14} height={14} />
        <span style={{ fontSize: 13 }}>
          {user?.name || 'Google Drive'}
          {user?.email && <span className="muted" style={{ marginLeft: 4 }}>({user.email})</span>}
        </span>
        <button className="ghost small" onClick={() => setOpen(o => !o)} style={{ marginLeft: 'auto' }}>
          {open ? 'Hide ▲' : 'Browse files ▼'}
        </button>
        <button className="ghost small" onClick={disconnect} style={{ color: 'var(--muted)' }}>Disconnect</button>
      </div>

      {open && (
        <div style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' }}>
          {/* Search */}
          <div style={{ padding: '7px 10px', borderBottom: '1px solid var(--line)', display: 'flex', gap: 6 }}>
            <input
              type="search"
              placeholder="Search files in Drive…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && fetchFiles(token, null, search)}
              style={{ flex: 1, fontSize: 13, padding: '3px 8px', border: '1px solid var(--line)', borderRadius: 4, background: 'var(--bg, #fff)' }}
            />
            <button className="ghost small" onClick={() => fetchFiles(token, null, search)}>Search</button>
            {search && <button className="ghost small" onClick={() => { setSearch(''); fetchFiles(token, null, '') }}>✕</button>}
          </div>

          {/* Column headers */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', borderBottom: '1px solid var(--line)', background: 'var(--bg-subtle, #F8F7F5)', fontSize: 11, color: 'var(--muted)' }}>
            <input type="checkbox" style={{ width: 13, height: 13 }} checked={selected.size > 0 && selected.size === files.length} onChange={toggleAll} aria-label="Select all" />
            <span style={{ flex: 1 }}>Name</span>
            <span style={{ width: 85 }}>Type</span>
            <span style={{ width: 90, textAlign: 'right' }}>Modified</span>
          </div>

          {/* File rows */}
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {loading && files.length === 0 && (
              <div style={{ padding: 16, textAlign: 'center', fontSize: 13 }}><span className="spinner" /> Loading Drive files…</div>
            )}
            {!loading && files.length === 0 && (
              <div style={{ padding: 16, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>No supported files found.</div>
            )}
            {files.map(f => (
              <div
                key={f.id}
                onClick={() => toggle(f.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '6px 10px', borderBottom: '1px solid var(--line)',
                  cursor: 'pointer', fontSize: 13,
                  background: selected.has(f.id) ? '#F0F4FF' : undefined,
                }}
              >
                <input
                  type="checkbox"
                  checked={selected.has(f.id)}
                  onChange={() => toggle(f.id)}
                  onClick={e => e.stopPropagation()}
                  style={{ width: 13, height: 13, flexShrink: 0 }}
                  aria-label={'Select ' + f.name}
                />
                <span style={{ fontSize: 14, flexShrink: 0 }}>{FILE_ICON[f.mimeType] || '📄'}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.name}>{f.name}</span>
                <span style={{ width: 85, flexShrink: 0, fontSize: 11, color: 'var(--muted)' }}>{FILE_LABEL[f.mimeType] || 'File'}</span>
                <span style={{ width: 90, flexShrink: 0, textAlign: 'right', color: 'var(--muted)', fontSize: 11 }}>{fmtDate(f.modifiedTime)}</span>
              </div>
            ))}
            {nextPage && !loading && (
              <button className="ghost small" style={{ width: '100%', borderRadius: 0, padding: '8px 0', fontSize: 12 }} onClick={() => fetchFiles(token, nextPage, search)}>
                Load more…
              </button>
            )}
            {loading && files.length > 0 && (
              <div style={{ padding: 6, textAlign: 'center', fontSize: 12 }}><span className="spinner" /></div>
            )}
          </div>

          {/* Action bar */}
          <div style={{ padding: '7px 10px', borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-subtle, #F8F7F5)' }}>
            <span className="muted" style={{ fontSize: 12 }}>
              {selected.size > 0 ? selected.size + ' file' + (selected.size !== 1 ? 's' : '') + ' selected' : 'Select files to scan'}
            </span>
            {dlProgress && <span style={{ fontSize: 12, flex: 1, color: 'var(--muted)' }}><span className="spinner" /> {dlProgress}</span>}
            <button
              disabled={!selected.size || downloading}
              onClick={downloadAndScan}
              style={{ marginLeft: 'auto' }}
            >
              {downloading ? 'Downloading…' : '⚡ Scan ' + (selected.size || 0) + ' selected'}
            </button>
          </div>
        </div>
      )}

      {error && <p style={{ color: '#854F0B', fontSize: 12, marginTop: 6, marginBottom: 0 }}>{error}</p>}
    </div>
  )
}
