import React, { useState, useEffect, useRef, useCallback } from 'react'
import { loadScores, saveDriveScore, uploadToDrive } from './GoogleDrive.jsx'
import { uploadToSharePoint } from './api.js'
import { SP_SCOPES, CAN_WRITE_BACK } from './sharepointScopes.js'

const CLIENT_ID = import.meta.env.VITE_AZURE_CLIENT_ID || ''
const TENANT   = import.meta.env.VITE_AZURE_TENANT_ID  || 'common'
const SCOPES   = SP_SCOPES   // read-only; see sharepointScopes.js
const GRAPH    = 'https://graph.microsoft.com/v1.0'

const SUPPORTED_EXT = ['.pdf', '.docx', '.pptx', '.xlsx', '.html', '.htm']
const EXT_ICON  = { '.pdf': '📄', '.docx': '📝', '.pptx': '📊', '.xlsx': '📗', '.html': '🌐', '.htm': '🌐' }
const EXT_LABEL = { '.pdf': 'PDF', '.docx': 'Word', '.pptx': 'PPT', '.xlsx': 'Excel', '.html': 'HTML', '.htm': 'HTML' }

function extOf(name) {
  const m = (name || '').match(/(\.[^.]+)$/)
  return m ? m[1].toLowerCase() : ''
}
function fmtDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
function fmtSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// ── Per-item write-back button ─────────────────────────────────────────────────

// The write goes through the SERVER (/sharepoint/upload with item_id), not straight to Graph
// from here.
//
// What moves server-side: the archive-before-overwrite and its fail-closed behaviour
// (scanner._sp_archive_original), the >4 MiB resumable session this path never had — a simple
// PUT past 4 MiB is a 413 that says nothing about chunking — and Graph's permission errors
// translated into the consent that would fix them instead of "Reconnect SharePoint".
//
// And record_remediation, WHEN there is a scan to record against. Being precise about that: the
// route calls it only if a scanId is passed, and the one caller here is the ad-hoc upload panel,
// where files are assessed individually and belong to no scan run. So this does not by itself
// close the record gap for ad-hoc saves — nothing to record them against would be invented, and
// inventing one would be worse than the gap. It closes it for any caller that HAS a scan, which
// is what the remediation flow will pass when this button is reused there.
export function SpUploadButton({ itemId, driveId, blob, score, engine, scanId, file }) {
  const [phase, setPhase] = useState('idle') // idle|confirm|saving|done|error
  const [errMsg, setErrMsg] = useState('')
  // Read-only build: no write scope was requested, so writing back would 403 at Graph. Hide the
  // affordance rather than offer a button that cannot succeed. Gated on the scopes themselves, so
  // it tracks CAN_WRITE_BACK automatically if write is ever re-enabled. After the hooks above so
  // the call order stays constant (rules of hooks); CAN_WRITE_BACK is a module constant regardless.
  if (!CAN_WRITE_BACK) return null

  const doSave = async () => {
    setPhase('saving')
    try {
      // item_id present → the server archives the original, then replaces it in place.
      await uploadToSharePoint({ scanId, file, driveId, itemId, blob, score })
      setPhase('done')
    } catch (e) {
      setPhase('error')
      // The server distinguishes a missing scope (403, naming the consent) from a transport
      // failure, and says which. Flattening that to "Reconnect SharePoint" sent people to
      // re-authenticate when the fix was a tenant-admin grant they could not make themselves.
      setErrMsg(e?.message || 'Upload failed')
    }
  }

  if (phase === 'idle') return (
    <button className="ghost small" onClick={() => setPhase('confirm')} style={{ flexShrink: 0, fontSize: 12, padding: '2px 8px' }}>
      ↑ SharePoint
    </button>
  )
  if (phase === 'confirm') return (
    <span style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0, fontSize: 12 }}>
      <span style={{ color: 'var(--muted)' }}>Replace in SharePoint? Original is copied to _mova-originals first.</span>
      <button className="ghost small" style={{ fontSize: 11, padding: '1px 6px' }} onClick={doSave}>Yes</button>
      <button className="ghost small" style={{ fontSize: 11, padding: '1px 6px' }} onClick={() => setPhase('idle')}>No</button>
    </span>
  )
  if (phase === 'saving') return <span style={{ fontSize: 12, color: 'var(--muted)', flexShrink: 0 }}><span className="spinner" style={{ marginRight: 4 }} />Saving…</span>
  if (phase === 'done')   return <span style={{ fontSize: 12, color: 'var(--success-fg)', flexShrink: 0 }}>✓ Saved to SharePoint</span>
  return <span style={{ fontSize: 12, color: 'var(--warn-fg)', flexShrink: 0 }}>✕ {errMsg}</span>
}

// ── Main SharePoint component ─────────────────────────────────────────────────

export default function SharePoint({ onFiles }) {
  const msalRef   = useRef(null)
  const [ready, setReady]     = useState(false)
  const [token, setToken]     = useState(() => sessionStorage.getItem('sp_token') || null)
  const [account, setAccount] = useState(() => { try { return JSON.parse(sessionStorage.getItem('sp_account') || 'null') } catch { return null } })
  const [files,  setFiles]    = useState([])
  const [nextLink, setNextLink] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,  setError]    = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [downloading, setDownloading] = useState(false)
  const [dlProgress, setDlProgress]   = useState(null)
  const [search, setSearch]   = useState('')
  const [open, setOpen]       = useState(false)
  const [folderId, setFolderId] = useState(null)  // null = root
  const [folderName, setFolderName] = useState('OneDrive')
  const [folders, setFolders] = useState([])

  // Initialise MSAL once the CDN script is loaded
  useEffect(() => {
    if (!CLIENT_ID) return
    const init = async () => {
      if (!window.msal) { setTimeout(init, 300); return }
      try {
        const cfg = {
          auth: { clientId: CLIENT_ID, authority: `https://login.microsoftonline.com/${TENANT}`, redirectUri: window.location.origin },
          cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
        }
        const instance = new window.msal.PublicClientApplication(cfg)
        await instance.initialize()
        msalRef.current = instance
        // Restore active account from cache
        const accounts = instance.getAllAccounts()
        if (accounts.length > 0 && token) {
          instance.setActiveAccount(accounts[0])
          setAccount(accounts[0])
        }
        setReady(true)
      } catch (e) { setError('MSAL init failed: ' + e.message) }
    }
    init()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const acquireToken = useCallback(async () => {
    const msal = msalRef.current
    if (!msal) return null
    const req = { scopes: SCOPES }
    try {
      // Try silent first (uses cached token)
      const result = await msal.acquireTokenSilent({ ...req, account: msal.getActiveAccount() || undefined })
      return result.accessToken
    } catch {
      // Fall back to popup
      const result = await msal.acquireTokenPopup(req)
      return result.accessToken
    }
  }, [])

  const fetchFiles = useCallback(async (tok, nextLinkUrl, searchTerm, parentId) => {
    setLoading(true); setError(null)
    try {
      let url
      if (nextLinkUrl) {
        url = nextLinkUrl
      } else {
        const base = parentId
          ? `${GRAPH}/me/drive/items/${parentId}/children`
          : `${GRAPH}/me/drive/root/children`
        const params = new URLSearchParams({
          $select: 'id,name,file,folder,lastModifiedDateTime,size,parentReference',
          $top: '50',
          $orderby: 'lastModifiedDateTime desc',
        })
        if (searchTerm?.trim()) {
          url = `${GRAPH}/me/drive/root/search(q='${encodeURIComponent(searchTerm.trim())}')&${params}`
        } else {
          url = `${base}?${params}`
        }
      }
      const r = await fetch(url, { headers: { Authorization: 'Bearer ' + tok } })
      if (r.status === 401) { setToken(null); sessionStorage.removeItem('sp_token'); return }
      const data = await r.json()
      if (data.error) { setError(data.error.message); return }
      const items = (data.value || []).filter((it) => {
        if (it.folder) return false  // skip folders in file list
        const ext = extOf(it.name)
        return SUPPORTED_EXT.includes(ext)
      })
      const folderItems = (data.value || []).filter((it) => it.folder)
      setFolders(folderItems)
      setFiles((prev) => nextLinkUrl ? [...prev, ...items] : items)
      setNextLink(data['@odata.nextLink'] || null)
    } catch (e) { setError('Could not load OneDrive files: ' + e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (token) fetchFiles(token, null, '', folderId)
  }, [token, fetchFiles, folderId])

  const connect = async () => {
    if (!CLIENT_ID) { setError('Add VITE_AZURE_CLIENT_ID to frontend/.env and restart.'); return }
    if (!ready) { setError('MSAL still loading — retry in a moment.'); return }
    setError(null)
    try {
      const msal = msalRef.current
      const result = await msal.loginPopup({ scopes: SCOPES })
      msal.setActiveAccount(result.account)
      const tok = result.accessToken
      setToken(tok); setAccount(result.account)
      sessionStorage.setItem('sp_token', tok)
      sessionStorage.setItem('sp_account', JSON.stringify(result.account))
      setOpen(true); fetchFiles(tok, null, '', null)
    } catch (e) {
      if (!e.message?.includes('user_cancelled')) setError(e.message || 'Login failed')
    }
  }

  const refresh = async () => {
    try {
      const tok = await acquireToken()
      if (tok) { setToken(tok); sessionStorage.setItem('sp_token', tok); fetchFiles(tok, null, search, folderId) }
    } catch (e) { setError(e.message) }
  }

  const disconnect = () => {
    msalRef.current?.logoutPopup().catch(() => {})
    setToken(null); setAccount(null); setFiles([]); setFolders([])
    sessionStorage.removeItem('sp_token'); sessionStorage.removeItem('sp_account')
    setOpen(false)
  }

  const toggle    = (id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll = () => setSelected((s) => s.size === files.length && files.length > 0 ? new Set() : new Set(files.map((f) => f.id)))

  const downloadAndScan = async () => {
    const toScan = files.filter((f) => selected.has(f.id))
    if (!toScan.length) return
    setDownloading(true)
    const fileObjects = []
    for (let i = 0; i < toScan.length; i++) {
      const it = toScan[i]
      setDlProgress(`Downloading ${i + 1} / ${toScan.length}: ${it.name}`)
      try {
        // Refresh token silently before download in case it expired
        const tok = (await acquireToken()) || token
        const r = await fetch(`${GRAPH}/me/drive/items/${it.id}/content`, {
          headers: { Authorization: 'Bearer ' + tok },
        })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const blob = await r.blob()
        const fileObj = new File([blob], it.name, { type: blob.type || 'application/octet-stream' })
        fileObj._spItemId = it.id
        fileObj._spDriveId = it.parentReference?.driveId || null
        fileObj._spName = it.name
        fileObjects.push(fileObj)
      } catch (e) { console.error('SharePoint download failed:', it.name, e) }
    }
    setDownloading(false); setDlProgress(null)
    if (fileObjects.length) { onFiles(fileObjects); setSelected(new Set()); setOpen(false) }
  }

  const scores = loadScores()

  const scoreBadge = (id) => {
    const s = scores[id]
    if (!s) return null
    const bg = s.score >= 90 ? 'var(--success-bg)' : s.score >= 50 ? 'var(--warn-bg)' : 'var(--info-bg)'
    const fg = s.score >= 90 ? 'var(--success-fg)' : s.score >= 50 ? 'var(--warn-fg)' : 'var(--info-fg)'
    const icon = s.score >= 90 ? '🟢' : s.score >= 50 ? '🟡' : '🔴'
    return React.createElement('span', { style: { fontSize: 10, padding: '1px 5px', borderRadius: 3, background: bg, color: fg, flexShrink: 0, whiteSpace: 'nowrap' } }, `${icon} ${s.score}`)
  }

  // ── NOT CONNECTED ─────────────────────────────────────────────────────────────
  if (!token) {
    return (
      <div style={{ marginTop: 12 }}>
        <button className="ghost small" onClick={connect} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <svg width="14" height="14" viewBox="0 0 21 21" aria-hidden="true">
            <rect x="1"  y="1"  width="9" height="9" fill="#f25022"/>
            <rect x="11" y="1"  width="9" height="9" fill="#7fba00"/>
            <rect x="1"  y="11" width="9" height="9" fill="#00a4ef"/>
            <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
          </svg>
          Connect SharePoint / OneDrive
        </button>
        {!CLIENT_ID && <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 6, marginBottom: 0 }}>Add <code>VITE_AZURE_CLIENT_ID</code> to <code>frontend/.env</code> to enable.</p>}
        {error && <p style={{ color: 'var(--warn-fg)', fontSize: 12, marginTop: 6, marginBottom: 0 }}>{error}</p>}
      </div>
    )
  }

  // ── CONNECTED ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ marginTop: 12 }}>
      {/* Account bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: open ? 8 : 0 }}>
        <svg width="14" height="14" viewBox="0 0 21 21" aria-hidden="true" style={{ flexShrink: 0 }}>
          <rect x="1"  y="1"  width="9" height="9" fill="#f25022"/>
          <rect x="11" y="1"  width="9" height="9" fill="#7fba00"/>
          <rect x="1"  y="11" width="9" height="9" fill="#00a4ef"/>
          <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
        </svg>
        <span style={{ fontSize: 13 }}>
          {account?.name || 'Microsoft Account'}
          {account?.username && <span className="muted" style={{ marginLeft: 4 }}>({account.username})</span>}
        </span>
        <button className="ghost small" onClick={() => setOpen((o) => !o)} style={{ marginLeft: 'auto' }}>
          {open ? 'Hide ▲' : 'Browse files ▼'}
        </button>
        <button className="ghost small" onClick={refresh} style={{ color: 'var(--muted)' }} title="Refresh token & reload files">↺</button>
        <button className="ghost small" onClick={disconnect} style={{ color: 'var(--muted)' }}>Disconnect</button>
      </div>

      {open && (
        <div style={{ border: '1px solid var(--line)', borderRadius: 8, overflow: 'hidden' }}>

          {/* Breadcrumb + search row */}
          <div style={{ padding: '7px 10px', borderBottom: '1px solid var(--line)', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {folderId && (
              <button className="ghost small" style={{ fontSize: 12 }} onClick={() => { setFolderId(null); setFolderName('OneDrive'); setFiles([]) }}>
                ← {folderName}
              </button>
            )}
            <input
              type="search" placeholder="Search OneDrive…" value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchFiles(token, null, search, folderId)}
              style={{ flex: 1, fontSize: 13, padding: '3px 8px', border: '1px solid var(--line)', borderRadius: 4, background: 'var(--bg, #fff)', minWidth: 120 }}
            />
            <button className="ghost small" onClick={() => fetchFiles(token, null, search, folderId)}>Search</button>
            {search && <button className="ghost small" onClick={() => { setSearch(''); fetchFiles(token, null, '', folderId) }}>✕</button>}
          </div>

          {/* Column headers */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', borderBottom: '1px solid var(--line)', background: 'var(--bg-subtle, #F8F7F5)', fontSize: 11, color: 'var(--muted)' }}>
            <input type="checkbox" style={{ width: 13, height: 13 }} checked={selected.size > 0 && selected.size === files.length} onChange={toggleAll} aria-label="Select all" />
            <span style={{ flex: 1 }}>Name</span>
            <span style={{ width: 40 }}>Score</span>
            <span style={{ width: 55 }}>Type</span>
            <span style={{ width: 55 }}>Size</span>
            <span style={{ width: 90, textAlign: 'right' }}>Modified</span>
          </div>

          {/* Folder rows */}
          {folders.length > 0 && (
            <div style={{ borderBottom: '1px solid var(--line)', background: 'var(--bg-subtle, #F8F7F5)' }}>
              {folders.slice(0, 5).map((f) => (
                <div key={f.id} onClick={() => { setFolderId(f.id); setFolderName(f.name); setFiles([]); setNextLink(null) }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>
                  <span style={{ width: 13 }} />
                  <span>📁</span>
                  <span style={{ flex: 1 }}>{f.name}</span>
                  <span style={{ fontSize: 11 }}>→</span>
                </div>
              ))}
            </div>
          )}

          {/* File rows */}
          <div style={{ maxHeight: 260, overflowY: 'auto' }}>
            {loading && files.length === 0 && <div style={{ padding: 16, textAlign: 'center', fontSize: 13 }}><span className="spinner" /> Loading OneDrive files…</div>}
            {!loading && files.length === 0 && <div style={{ padding: 16, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>No supported files found in this location.</div>}
            {files.map((f) => {
              const ext = extOf(f.name)
              return (
                <div key={f.id} onClick={() => toggle(f.id)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--line)', cursor: 'pointer', fontSize: 13, background: selected.has(f.id) ? '#F0F4FF' : undefined }}>
                  <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} onClick={(e) => e.stopPropagation()} style={{ width: 13, height: 13, flexShrink: 0 }} aria-label={'Select ' + f.name} />
                  <span style={{ fontSize: 14, flexShrink: 0 }}>{EXT_ICON[ext] || '📄'}</span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.name}>{f.name}</span>
                  <span style={{ width: 40, flexShrink: 0 }}>{scoreBadge(f.id)}</span>
                  <span style={{ width: 55, flexShrink: 0, fontSize: 11, color: 'var(--muted)' }}>{EXT_LABEL[ext] || 'File'}</span>
                  <span style={{ width: 55, flexShrink: 0, fontSize: 11, color: 'var(--muted)' }}>{fmtSize(f.size)}</span>
                  <span style={{ width: 90, flexShrink: 0, textAlign: 'right', fontSize: 11, color: 'var(--muted)' }}>{fmtDate(f.lastModifiedDateTime)}</span>
                </div>
              )
            })}
            {nextLink && !loading && <button className="ghost small" style={{ width: '100%', borderRadius: 0, padding: '8px 0', fontSize: 12 }} onClick={() => fetchFiles(token, nextLink, '', folderId)}>Load more…</button>}
            {loading && files.length > 0 && <div style={{ padding: 6, textAlign: 'center', fontSize: 12 }}><span className="spinner" /></div>}
          </div>

          {/* Action bar */}
          <div style={{ padding: '7px 10px', borderTop: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', background: 'var(--bg-subtle, #F8F7F5)' }}>
            {dlProgress && <span style={{ fontSize: 12, color: 'var(--muted)' }}><span className="spinner" /> {dlProgress}</span>}
            <button disabled={!selected.size || downloading} onClick={downloadAndScan} style={{ marginLeft: 'auto' }}>
              {downloading ? 'Downloading…' : `⚡ Scan ${selected.size || 0} selected`}
            </button>
          </div>
        </div>
      )}

      {error && <p style={{ color: 'var(--warn-fg)', fontSize: 12, marginTop: 6, marginBottom: 0 }}>{error}</p>}
    </div>
  )
}
