import { useState, useEffect } from 'react'
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
export default function SitePicker({ onScan, onClose }) {
  const [q, setQ] = useState('')
  const [sites, setSites] = useState([])
  const [drives, setDrives] = useState({})       // site id -> libraries, loaded on expand
  const [open, setOpen] = useState(null)
  const [picked, setPicked] = useState([])       // site ids, in the order they were chosen
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  // The DEPLOYMENT's cap, not this file's idea of it. The server refuses a larger selection
  // (routes/scans.sharepoint_site_overflow) and the walk caps itself; a number hardcoded here
  // would disagree with either the moment an operator raised ACP_SP_MAX_SITES — blocking a
  // selection the server would accept, or waving through one it will refuse after the operator
  // has finished choosing. 30 is the fallback only until /config answers.
  const [maxSites, setMaxSites] = useState(30)

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

  return (
    <div className="setoverlay" role="dialog" aria-modal="true" aria-label="Choose SharePoint sites">
      <div className="setpanel" style={{ maxWidth: 620 }}>
        <h3 style={{ marginTop: 0 }}>Scan SharePoint sites</h3>
        <p className="muted" style={{ fontSize: 12.5 }}>
          Select one or more sites — every document library on each is scanned. Expand one to see
          what that includes before you commit to it.
        </p>

        <input
          type="search" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Filter sites…" aria-label="Filter sites by name"
          style={{ width: '100%', padding: '6px 10px', marginBottom: 10 }} />

        {loading && <p className="muted" style={{ fontSize: 13 }}>Loading sites…</p>}

        {/* Verbatim, not flattened. The route distinguishes a missing SCOPE from a transport
            failure and names the consent that would fix it; collapsing that to "could not load"
            would send an operator looking in the wrong place. */}
        {err && <p role="alert" style={{ fontSize: 12.5, color: 'var(--error-fg-strong)' }}>⚠ {err}</p>}

        {!loading && !err && sites.length === 0 && (
          <p className="muted" style={{ fontSize: 13 }}>
            {q ? `No site matches “${q}”.` : 'No sites visible to this sign-in.'}
          </p>
        )}

        <div style={{ maxHeight: 320, overflowY: 'auto' }}>
          {sites.map((s) => (
            <div key={s.id} style={{ borderBottom: '1px solid var(--line)', padding: '6px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input
                    type="checkbox" checked={picked.includes(s.id)}
                    /* Disabled only for sites NOT already chosen: an at-cap selection must stay
                       editable, or the operator can neither add nor swap and has to start over. */
                    disabled={atCap && !picked.includes(s.id)}
                    onChange={() => toggle(s.id)}
                    aria-label={`Select ${s.name}`} />
                  <span>{s.name}</span>
                </label>
                <button className="linklike" onClick={() => expand(s)} aria-expanded={open === s.id}
                        aria-label={`Show libraries on ${s.name}`}>
                  {open === s.id ? '▾ libraries' : '▸ libraries'}
                </button>
                {s.url && <a className="muted" style={{ fontSize: 11.5 }} href={s.url}
                             target="_blank" rel="noopener noreferrer">open ↗</a>}
              </div>
              {open === s.id && (
                <div className="muted" style={{ fontSize: 12, padding: '4px 0 2px 18px' }}>
                  {!drives[s.id] && 'Loading libraries…'}
                  {drives[s.id]?.error && `⚠ ${drives[s.id].error}`}
                  {Array.isArray(drives[s.id]) && drives[s.id].length === 0 && (
                    // Said plainly: this is the site that scans to zero, and knowing that BEFORE
                    // the scan is the difference between a decision and a support ticket.
                    <span>No document libraries — scanning this site would return nothing.</span>
                  )}
                  {Array.isArray(drives[s.id]) && drives[s.id].length > 0 && (
                    <span>{drives[s.id].length} librar{drives[s.id].length === 1 ? 'y' : 'ies'}: {drives[s.id].map((d) => d.name).join(', ')}</span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* The cap, stated where the choice is made rather than as a 400 after it. The server is
            still the authority — this only stops the operator finishing a selection it will
            refuse. */}
        {atCap && (
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            {maxSites} sites is the most one scan covers. Run the rest as a second scan.
          </p>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
          <button className="primary small" disabled={picked.length === 0}
                  onClick={() => onScan(picked)}>
            {picked.length > 1 ? `Scan ${picked.length} sites` : 'Scan selected site'}
          </button>
          <button className="ghost small" onClick={onClose}>Cancel</button>
          <span className="muted" style={{ fontSize: 12 }}>
            {picked.length} of {maxSites} selected
          </span>
        </div>
      </div>
    </div>
  )
}
