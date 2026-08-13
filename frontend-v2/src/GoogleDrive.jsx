import React, { useState, useEffect, useRef, useCallback } from 'react'
import { googleUserInfo } from './googleIdentity.js'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
const SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'
const LS_SCORES = 'mova_drive_scores'

const GDOC_EXPORT = {
  'application/vnd.google-apps.document':     { ext: '.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
  'application/vnd.google-apps.spreadsheet':  { ext: '.xlsx', mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
  'application/vnd.google-apps.presentation': { ext: '.pptx', mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' },
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

// ── Shared helpers (also used by Upload.jsx) ───────────────────────────────────

export const loadScores = () => { try { return JSON.parse(localStorage.getItem(LS_SCORES) || '{}') } catch { return {} } }

export const saveDriveScore = (driveFileId, score, engine) => {
  try {
    const s = loadScores()
    s[driveFileId] = { score, engine, date: new Date().toISOString().slice(0, 10) }
    localStorage.setItem(LS_SCORES, JSON.stringify(s))
  } catch {}
}

// Every response is checked, and that is the whole point of this function's shape.
//
// It used to read `data.files` off an unchecked response and fall through to create on a 403,
// then read `f.id` off an unchecked create and return undefined. The copy that followed was
// issued with `parents: [undefined]` — which Drive rejects, unchecked, so the archive resolved
// having done nothing at all. Three unchecked responses in a row, and the failure of all three
// looked exactly like success.
async function findOrCreateFolder(token, name, parentId) {
  const q = "name='" + name.replace(/'/g, "\\'") + "' and mimeType='application/vnd.google-apps.folder' and '" + parentId + "' in parents and trashed=false"
  const r = await fetch('https://www.googleapis.com/drive/v3/files?q=' + encodeURIComponent(q) + '&fields=files(id)', {
    headers: { Authorization: 'Bearer ' + token },
  })
  if (!r.ok) throw new Error('could not look for the ' + name + ' folder (HTTP ' + r.status + ')')
  const data = await r.json()
  if (data.files && data.files.length > 0) return data.files[0].id
  const cr = await fetch('https://www.googleapis.com/drive/v3/files', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, mimeType: 'application/vnd.google-apps.folder', parents: [parentId] }),
  })
  if (!cr.ok) throw new Error('could not create the ' + name + ' folder (HTTP ' + cr.status + ')')
  const f = await cr.json()
  if (!f.id) throw new Error('Drive created the ' + name + ' folder but returned no id')
  return f.id
}

export async function uploadToDrive(token, driveFileId, blob, meta) {
  const boundary = 'mova_bdry_' + Date.now()
  const metaStr = JSON.stringify(meta)
  const header = '--' + boundary + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n' + metaStr + '\r\n--' + boundary + '\r\nContent-Type: ' + blob.type + '\r\n\r\n'
  const tail = '\r\n--' + boundary + '--'
  const body = new Blob([new TextEncoder().encode(header), blob, new TextEncoder().encode(tail)])
  const r = await fetch(
    'https://www.googleapis.com/upload/drive/v3/files/' + driveFileId + '?uploadType=multipart&fields=id,webViewLink',
    { method: 'PATCH', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'multipart/related; boundary=' + boundary }, body }
  )
  if (!r.ok) throw new Error('HTTP ' + r.status)
  return await r.json()
}

// Copy the original into _mova-originals/<date>/ before it is overwritten.
//
// FAIL-CLOSED: every failure throws, and the caller must not write if it does. This matches what
// SharePoint does server-side (scanner._sp_archive_original). The reasoning is the same on both:
// an archive that only sometimes happens is not a backup, and it fails invisibly at exactly the
// moment it matters — so the worst outcome has to be "your file was not remediated", which a
// user can see and retry, rather than "your file was replaced and the original is gone", which
// they cannot.
export async function archiveOriginal(token, driveFileId) {
  const today = new Date().toISOString().slice(0, 10)
  const rootId = await findOrCreateFolder(token, '_mova-originals', 'root')
  const dateId = await findOrCreateFolder(token, today, rootId)
  const r = await fetch('https://www.googleapis.com/drive/v3/files/' + driveFileId + '/copy', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ parents: [dateId] }),
  })
  // The response this function never looked at. A 403 (no write scope), a 507 (out of quota) or
  // a 404 (the file moved) all came back here as a resolved promise, so the archive reported
  // success having copied nothing, and the overwrite followed.
  if (!r.ok) throw new Error('archive failed (HTTP ' + r.status + ') — nothing was overwritten')
  return dateId
}

function buildMeta(score, engine) {
  return {
    description: 'Remediated for WCAG 2.1 AA by mova.io · ' + new Date().toISOString().slice(0, 10) + (score != null ? ' · Score: ' + score + '/100' : ''),
    appProperties: { mova_score: score != null ? String(score) : '', mova_standard: 'WCAG 2.1 AA', mova_engine: engine || 'mova', mova_date: new Date().toISOString().slice(0, 10) },
  }
}

// ── DriveUploadButton ──────────────────────────────────────────────────────────

export function DriveUploadButton({ driveFileId, blob, score, engine }) {
  const [phase, setPhase] = useState('idle') // idle|confirm|archiving|saving|done|error
  const [viewUrl, setViewUrl] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  const doSave = async () => {
    const token = sessionStorage.getItem('gd_token')
    if (!token) { setPhase('error'); setErrMsg('Reconnect Drive'); return }
    // ALWAYS, and no longer behind the `mova_drive_archive` preference.
    //
    // The archive was opt-in and off by default — an unset key reads as false — so the shipped
    // behaviour for anyone who had not found a checkbox was a destructive in-place overwrite
    // with no backup at all. An opt-out backup on a write that cannot be undone is the same
    // defect wearing a preference, and nobody who left the box unticked was choosing "and
    // discard the original" — the confirmation never said that was the alternative.
    setPhase('archiving')
    try {
      await archiveOriginal(token, driveFileId)
    } catch (e) {
      // Abort. This is the line that used to be `catch { /* archive best-effort */ }`, and the
      // overwrite ran regardless.
      setPhase('error')
      setErrMsg(e.message || 'Could not back up the original — nothing was changed')
      return
    }
    setPhase('saving')
    try {
      const data = await uploadToDrive(token, driveFileId, blob, buildMeta(score, engine))
      setViewUrl(data.webViewLink || ('https://drive.google.com/file/d/' + driveFileId + '/view'))
      setPhase('done')
    } catch (e) { setPhase('error'); setErrMsg(e.message || 'Upload failed') }
  }

  if (phase === 'idle') return (
    <button className="ghost small" onClick={() => setPhase('confirm')} style={{ flexShrink: 0, fontSize: 12, padding: '2px 8px' }}>
      ↑ Drive
    </button>
  )
  if (phase === 'confirm') return (
    <span style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0, fontSize: 12 }}>
      {/* Says what the confirmation buys. "Replace in Drive?" alone asked for consent to a
          destructive write while saying nothing about whether anything was kept — and for the
          default configuration, nothing was. */}
      <span style={{ color: 'var(--muted)' }}>Replace in Drive? Original is copied to _mova-originals first.</span>
      <button className="ghost small" style={{ fontSize: 11, padding: '1px 6px' }} onClick={doSave}>Yes</button>
      <button className="ghost small" style={{ fontSize: 11, padding: '1px 6px' }} onClick={() => setPhase('idle')}>No</button>
    </span>
  )
  if (phase === 'archiving') return <span style={{ fontSize: 12, color: 'var(--muted)', flexShrink: 0 }}><span className="spinner" style={{ marginRight: 4 }} />Archiving…</span>
  if (phase === 'saving')    return <span style={{ fontSize: 12, color: 'var(--muted)', flexShrink: 0 }}><span className="spinner" style={{ marginRight: 4 }} />Saving…</span>
  if (phase === 'done') return (
    <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0, fontSize: 12 }}>
      <span style={{ color: '#3B6D11' }}>✓ Saved</span>
      {viewUrl && <a href={viewUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--accent, #1F5FA8)', fontSize: 11 }}>Open ↗</a>}
    </span>
  )
  return <span style={{ color: '#854F0B', fontSize: 12, flexShrink: 0 }}>✕ {errMsg}</span>
}

// ── GoogleDrive main component ─────────────────────────────────────────────────

export default function GoogleDrive({ onFiles }) {
  const tokenClient = useRef(null)
  const refreshCallbackRef = useRef(null)   // { resolve, reject } for in-flight silent refresh
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
  const [folders, setFolders] = useState([])
  const [selectedFolder, setSelectedFolder] = useState('')

  // Returns a new access token via silent GIS refresh, falling back to a popup.
  // Resolves with the new token or rejects after 30 s.
  const refreshToken = useCallback(() => new Promise((resolve, reject) => {
    if (!tokenClient.current) { reject(new Error('GIS not ready')); return }
    refreshCallbackRef.current = { resolve, reject }
    const timer = setTimeout(() => {
      if (refreshCallbackRef.current?.resolve === resolve) {
        refreshCallbackRef.current = null
        reject(new Error('Token refresh timed out'))
      }
    }, 30000)
    // prompt:'' = silent if Google session still valid, popup otherwise
    tokenClient.current.requestAccessToken({ prompt: '' })
    // clear the safety timer once resolved
    const orig = { resolve, reject }
    refreshCallbackRef.current = {
      resolve: (tok) => { clearTimeout(timer); orig.resolve(tok) },
      reject:  (err) => { clearTimeout(timer); orig.reject(err) },
    }
  }), [])

  const fetchFiles = useCallback(async (tok, pageToken, searchTerm, folderId) => {
    setLoading(true); setError(null)
    const doFetch = async (t) => {
      let q = DRIVE_Q_BASE
      const term = (searchTerm || '').trim()
      if (term) q = "name contains '" + term.replace(/'/g, "\\'") + "' and " + q
      if (folderId) q += " and '" + folderId + "' in parents"
      const params = new URLSearchParams({ q, fields: 'nextPageToken,files(id,name,mimeType,size,modifiedTime,owners)', pageSize: '50', orderBy: 'modifiedTime desc' })
      if (pageToken) params.set('pageToken', pageToken)
      return fetch('https://www.googleapis.com/drive/v3/files?' + params, { headers: { Authorization: 'Bearer ' + t } })
    }
    try {
      let r = await doFetch(tok)
      if (r.status === 401) {
        // Token expired — attempt silent refresh then retry once
        try {
          const newTok = await refreshToken()
          r = await doFetch(newTok)
        } catch {
          setToken(null); sessionStorage.removeItem('gd_token'); return
        }
      }
      const data = await r.json()
      if (data.error) { setError(data.error.message); return }
      setFiles(prev => pageToken ? [...prev, ...(data.files || [])] : (data.files || []))
      setNextPage(data.nextPageToken || null)
    } catch { setError('Could not load Drive files.') }
    finally { setLoading(false) }
  }, [refreshToken])

  const fetchFolders = useCallback(async (tok) => {
    try {
      const q = "mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
      const r = await fetch('https://www.googleapis.com/drive/v3/files?q=' + encodeURIComponent(q) + '&fields=files(id,name)&pageSize=50&orderBy=name', { headers: { Authorization: 'Bearer ' + tok } })
      const data = await r.json()
      if (data.files) setFolders(data.files)
    } catch {}
  }, [])

  useEffect(() => {
    if (token) { fetchFiles(token, null, '', selectedFolder); fetchFolders(token) }
  }, [token, fetchFiles, fetchFolders, selectedFolder])

  useEffect(() => {
    if (!CLIENT_ID || !window.google?.accounts?.oauth2 || tokenClient.current) return
    tokenClient.current = window.google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID, scope: SCOPES,
      callback: async (resp) => {
        if (resp.error) {
          const pending = refreshCallbackRef.current
          refreshCallbackRef.current = null
          if (pending) { pending.reject(new Error(resp.error_description || resp.error)); return }
          setError(resp.error_description || resp.error); return
        }
        const tok = resp.access_token
        setToken(tok); sessionStorage.setItem('gd_token', tok)
        // Resolve any in-flight refresh promise (silent re-auth path)
        const pending = refreshCallbackRef.current
        refreshCallbackRef.current = null
        if (pending) { pending.resolve(tok); return }
        // Normal connect path
        try {
          // Cached under 'gd_user' and read back on reload, so storing Google's error body here
          // persisted a bogus identity across sessions. Now nothing is stored unless it is real.
          const u = await googleUserInfo(tok)
          setUser(u); sessionStorage.setItem('gd_user', JSON.stringify(u))
        } catch { /* leave the previous user; the Drive token itself is still usable */ }
        setOpen(true); fetchFiles(tok, null, '', ''); fetchFolders(tok)
      },
    })
  })

  const connect = () => {
    if (!CLIENT_ID) { setError('Add VITE_GOOGLE_CLIENT_ID to frontend/.env and restart.'); return }
    if (!window.google?.accounts?.oauth2) { setError('Google Identity Services loading — retry in a moment.'); return }
    setError(null); tokenClient.current?.requestAccessToken()
  }

  const disconnect = () => {
    if (token) window.google?.accounts?.oauth2?.revoke(token)
    setToken(null); setUser(null); setFiles([]); setFolders([]); setSelected(new Set())
    sessionStorage.removeItem('gd_token'); sessionStorage.removeItem('gd_user'); setOpen(false)
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
        const doGet = (t) => fetch(url, { headers: { Authorization: 'Bearer ' + t } })
        let r = await doGet(token)
        if (r.status === 401) {
          const newTok = await refreshToken()
          r = await doGet(newTok)
        }
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const blob = await r.blob()
        const fileObj = new File([blob], name, { type: exp ? exp.mime : (blob.type || f.mimeType) })
        fileObj._driveId = f.id
        fileObj._driveName = f.name
        fileObjects.push(fileObj)
      } catch (e) { console.error('Drive download failed:', f.name, e) }
    }
    setDownloading(false); setDlProgress(null)
    if (fileObjects.length) { onFiles(fileObjects); setSelected(new Set()); setOpen(false) }
  }

  const scores = loadScores()

  const scoreBadge = (id) => {
    const s = scores[id]
    if (!s) return null
    const bg = s.score >= 90 ? '#E7F0DC' : s.score >= 50 ? '#FAEEDA' : '#E2EDFB'
    const fg = s.score >= 90 ? '#3B6D11' : s.score >= 50 ? '#854F0B' : '#1F5FA8'
    const icon = s.score >= 90 ? '🟢' : s.score >= 50 ? '🟡' : '🔴'
    return React.createElement('span', { style: { fontSize: 10, padding: '1px 5px', borderRadius: 3, background: bg, color: fg, flexShrink: 0, whiteSpace: 'nowrap' } }, icon + ' ' + s.score)
  }

  // ── NOT CONNECTED ────────────────────────────────────────────────────────────
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

  // ── CONNECTED ────────────────────────────────────────────────────────────────
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

          {/* Folder picker + search row */}
          <div style={{ padding: '7px 10px', borderBottom: '1px solid var(--line)', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {folders.length > 0 && (
              <select
                value={selectedFolder}
                onChange={e => { setSelectedFolder(e.target.value); setFiles([]); setNextPage(null) }}
                style={{ fontSize: 12, padding: '3px 6px', border: '1px solid var(--line)', borderRadius: 4, background: 'var(--bg, #fff)', maxWidth: 160 }}
              >
                <option value="">All files</option>
                {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            )}
            <input
              type="search" placeholder="Search files…" value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && fetchFiles(token, null, search, selectedFolder)}
              style={{ flex: 1, fontSize: 13, padding: '3px 8px', border: '1px solid var(--line)', borderRadius: 4, background: 'var(--bg, #fff)', minWidth: 120 }}
            />
            <button className="ghost small" onClick={() => fetchFiles(token, null, search, selectedFolder)}>Search</button>
            {search && <button className="ghost small" onClick={() => { setSearch(''); fetchFiles(token, null, '', selectedFolder) }}>✕</button>}
          </div>

          {/* Column headers */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', borderBottom: '1px solid var(--line)', background: 'var(--bg-subtle, #F8F7F5)', fontSize: 11, color: 'var(--muted)' }}>
            <input type="checkbox" style={{ width: 13, height: 13 }} checked={selected.size > 0 && selected.size === files.length} onChange={toggleAll} aria-label="Select all" />
            <span style={{ flex: 1 }}>Name</span>
            <span style={{ width: 40 }}>Score</span>
            <span style={{ width: 85 }}>Type</span>
            <span style={{ width: 90, textAlign: 'right' }}>Modified</span>
          </div>

          {/* File rows */}
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {loading && files.length === 0 && <div style={{ padding: 16, textAlign: 'center', fontSize: 13 }}><span className="spinner" /> Loading Drive files…</div>}
            {!loading && files.length === 0 && <div style={{ padding: 16, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>No supported files found.</div>}
            {files.map(f => (
              <div key={f.id} onClick={() => toggle(f.id)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--line)', cursor: 'pointer', fontSize: 13, background: selected.has(f.id) ? '#F0F4FF' : undefined }}>
                <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} onClick={e => e.stopPropagation()} style={{ width: 13, height: 13, flexShrink: 0 }} aria-label={'Select ' + f.name} />
                <span style={{ fontSize: 14, flexShrink: 0 }}>{FILE_ICON[f.mimeType] || '📄'}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.name}>{f.name}</span>
                <span style={{ width: 40, flexShrink: 0 }}>{scoreBadge(f.id)}</span>
                <span style={{ width: 85, flexShrink: 0, fontSize: 11, color: 'var(--muted)' }}>{FILE_LABEL[f.mimeType] || 'File'}</span>
                <span style={{ width: 90, flexShrink: 0, textAlign: 'right', color: 'var(--muted)', fontSize: 11 }}>{fmtDate(f.modifiedTime)}</span>
              </div>
            ))}
            {nextPage && !loading && <button className="ghost small" style={{ width: '100%', borderRadius: 0, padding: '8px 0', fontSize: 12 }} onClick={() => fetchFiles(token, nextPage, search, selectedFolder)}>Load more…</button>}
            {loading && files.length > 0 && <div style={{ padding: 6, textAlign: 'center', fontSize: 12 }}><span className="spinner" /></div>}
          </div>

          {/* Action bar */}
          <div style={{ padding: '7px 10px', borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', background: 'var(--bg-subtle, #F8F7F5)' }}>
            {dlProgress && <span style={{ fontSize: 12, color: 'var(--muted)' }}><span className="spinner" /> {dlProgress}</span>}
            <button disabled={!selected.size || downloading} onClick={downloadAndScan} style={{ marginLeft: 'auto' }}>
              {downloading ? 'Downloading…' : '⚡ Scan ' + (selected.size || 0) + ' selected'}
            </button>
          </div>
        </div>
      )}

      {error && <p style={{ color: '#854F0B', fontSize: 12, marginTop: 6, marginBottom: 0 }}>{error}</p>}
    </div>
  )
}
