import './site-picker.css'
import { useState, useEffect, useRef } from 'react'
import { listSharePointSites, listSharePointDrives, getConfig } from './api.js'

// Choose the SharePoint site(s) to scan. The counterpart of FolderPicker, and deliberately the
// same shape: a modal over the scan controls that ends in onScan(siteIds).
//
// WHY SEVERAL. An estate assessment covers a department, not a team site — "is our SharePoint
// accessible?" is a question about thirty locations, and this used to answer it one site at a
// time. Worse, the backend accepted a multi-site request and silently walked the FIRST site
// (scanner._sp_locations kept one bare root and dropped the rest), so the honest one-at-a-time
// UI was the only thing standing between an operator and a scan that reported a thirtieth of
// their estate as the total.
//
// `onScan` receives an ARRAY, always — one selected site is `[id]`, not `id`. A caller that has
// to branch on the shape of its argument is a caller that will get the single case right and the
// multi case wrong, which is the direction that under-reports an estate.
//
// WHY IT LISTS DRIVES AT ALL. Picking a site commits the scan to every document library on it
// (_sp_list iterates drives, #156), so the library list is shown as EVIDENCE, not as a second
// choice. A team site with four libraries and one with none look identical from the site name
// alone, and the second is the case where a scan returns nothing and the operator has no way to
// tell whether that is the site or the product.
//
// The 403 path matters more than the happy one. Sites.Read.All is tenant-admin consent in most
// tenants, so "no sites" is far more often a missing grant than an empty tenant — the route
// already translates that into a message naming the permission, and this surfaces it verbatim
// rather than flattening it to "could not load".
export default function SitePicker({ onScan, onClose, onChange, initial = [], layout = 'modal' }) {
  const [q, setQ] = useState('')
  const [sites, setSites] = useState([])
  const [drives, setDrives] = useState({})       // site id -> libraries, loaded on expand
  const [open, setOpen] = useState(null)
  const [picked, setPicked] = useState(() => initial.map((site) => typeof site === 'string' ? site : site.id))
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  // The DEPLOYMENT's cap, not this file's idea of it. The server refuses a larger selection
  // (routes/scans.sharepoint_site_overflow) and the walk caps itself; a number hardcoded here
  // would disagree with either the moment an operator raised ACP_SP_MAX_SITES — blocking a
  // selection the server would accept, or waving through one it will refuse after the operator
  // has finished choosing. 30 is the fallback only until /config answers.
  const [maxSites, setMaxSites] = useState(30)
  const inline = layout === 'inline'
  const changeRef = useRef(onChange)
  changeRef.current = onChange

  useEffect(() => {
    let live = true
    getConfig()
      .then((c) => { if (live && Number(c?.sharepoint_max_sites) > 0) setMaxSites(Number(c.sharepoint_max_sites)) })
      .catch(() => { /* keep the fallback — a missing /config must not block the picker */ })
    return () => { live = false }
  }, [])

  useEffect(() => {
    let live = true
    setLoading(true); setErr('')
    listSharePointSites(q)
      .then((d) => { if (live) setSites(d?.sites || []) })
      .catch((e) => { if (live) setErr(e?.message || 'could not list sites') })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [q])

  const expand = (site) => {
    if (open === site.id) { setOpen(null); return }
    setOpen(site.id)
    if (drives[site.id]) return                  // already loaded — don't re-fetch on every toggle
    listSharePointDrives(site.id)
      .then((d) => setDrives((m) => ({ ...m, [site.id]: d?.drives || [] })))
      .catch((e) => setDrives((m) => ({ ...m, [site.id]: { error: e?.message || 'unavailable' } })))
  }

  // Selection survives a filter change: typing into the search box narrows the LIST, not the
  // choice. An operator building a thirty-site estate scan searches "finance", ticks two,
  // searches "hr", ticks two more — clearing on every keystroke would make that impossible and
  // would look like the picker losing their work.
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const atCap = picked.length >= maxSites
  const knownSites = useRef(new Map())
  for (const site of initial) {
    const item = typeof site === 'string' ? { id: site, name: site } : site
    knownSites.current.set(item.id, item)
  }
  for (const site of sites) knownSites.current.set(site.id, { id: site.id, name: site.name })

  useEffect(() => {
    if (!inline || typeof changeRef.current !== 'function') return
    const known = new Map([
      ...knownSites.current.entries(),
      ...initial.map((site) => [typeof site === 'string' ? site : site.id,
        typeof site === 'string' ? { id: site, name: site } : site]),
      ...sites.map((site) => [site.id, { id: site.id, name: site.name }]),
    ])
    changeRef.current(picked.map((id) => known.get(id) || { id, name: id }))
  }, [inline, picked, sites])

  const content = (
    <div className={`sp-picker ${inline ? 'sp-picker--inline' : 'setpanel'}`}>
      {!inline && <h3>Scan SharePoint sites</h3>}
      <div className="sp-picker__columns">
        <div className="sp-picker__browser">
          <div className="sp-picker__toolbar"><strong>SharePoint sites</strong></div>
          <input className="sp-picker__filter" type="search" value={q}
            onChange={(e) => setQ(e.target.value)} placeholder="Filter SharePoint sites"
            aria-label="Filter sites by name" />
          <div className="sp-picker__list" aria-label="SharePoint sites" aria-busy={loading}>
            {loading && <p className="sp-picker__message muted" role="status">Loading sites…</p>}
            {err && <p className="sp-picker__message" role="alert">⚠ {err}</p>}
            {!loading && !err && sites.length === 0 && <p className="sp-picker__message muted">
              {q ? `No site matches “${q}”.` : 'No sites visible to this sign-in.'}
            </p>}
            {!loading && !err && sites.map((s) => (
              <div className="sp-picker__site" key={s.id}>
                <div className={`sp-picker__row${picked.includes(s.id) ? ' is-selected' : ''}`}>
                  <input type="checkbox" checked={picked.includes(s.id)}
                    disabled={atCap && !picked.includes(s.id)} onChange={() => toggle(s.id)}
                    aria-label={`Select ${s.name}`} />
                  <button type="button" className="sp-picker__expand" onClick={() => expand(s)}
                    aria-expanded={open === s.id} aria-label={`Show libraries on ${s.name}`}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                      strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
                      <path d="M3 7h18v14H3zM7 7V3h10v4M7 11h2m6 0h2m-10 4h2m6 0h2" />
                    </svg>
                    <span className="sp-picker__name">{s.name}</span>
                    <span className="sp-picker__hint">Libraries</span>
                    <span aria-hidden="true">{open === s.id ? '⌄' : '›'}</span>
                  </button>
                  {s.url && <a className="sp-picker__external" href={s.url} target="_blank"
                    rel="noopener noreferrer" aria-label={`Open ${s.name} in SharePoint (new tab)`}>↗</a>}
                </div>
                {open === s.id && <div className="sp-picker__libraries muted">
                  {!drives[s.id] && <span role="status">Loading libraries…</span>}
                  {drives[s.id]?.error && <span role="alert">⚠ {drives[s.id].error}</span>}
                  {Array.isArray(drives[s.id]) && (drives[s.id].length === 0
                    ? <span>No document libraries — scanning this site would return nothing.</span>
                    : <span>{drives[s.id].length} librar{drives[s.id].length === 1 ? 'y' : 'ies'}: {drives[s.id].map((d) => d.name).join(', ')}</span>)}
                </div>}
              </div>
            ))}
          </div>
        </div>
        <div className="sp-picker__scope" role="region" aria-label="Current scope">
          <div className="sp-picker__scope-heading"><span>CURRENT SCOPE</span>
            {picked.length > 0 && <button type="button" className="linklike" onClick={() => setPicked([])}>Clear all</button>}
          </div>
          {picked.length === 0 ? <strong className="sp-picker__empty">Select at least one SharePoint site</strong>
            : <><div className="sp-picker__chips">{picked.map((id) => {
              const name = knownSites.current.get(id)?.name || id
              return <span className="sp-picker__chip" key={id}>{name}
                <button type="button" className="linklike" aria-label={`Remove ${name}`} onClick={() => toggle(id)}>✕</button>
              </span>
            })}</div><p className="muted sp-picker__count">{picked.length} SharePoint site{picked.length === 1 ? '' : 's'} selected</p></>}
          <p className="sp-picker__note">Scans every document library on the selected sites, including all folders and subfolders.</p>
          {atCap && <p className="muted sp-picker__count">{maxSites} sites is the most one scan covers. Run the rest as a second scan.</p>}
        </div>
      </div>
      {!inline && <div className="sp-picker__actions">
        <button className="primary small" disabled={picked.length === 0} onClick={() => onScan(picked)}>
          {picked.length > 1 ? `Scan ${picked.length} sites` : 'Scan selected site'}
        </button>
        <button className="ghost small" onClick={onClose}>Cancel</button>
        <span className="muted">{picked.length} of {maxSites} selected</span>
      </div>}
    </div>
  )
  return inline ? content : (
    <div className="setoverlay" role="dialog" aria-modal="true" aria-label="Choose SharePoint sites">
      {content}
    </div>
  )
}
