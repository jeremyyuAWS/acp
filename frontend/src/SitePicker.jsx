import { useState, useEffect } from 'react'
import { listSharePointSites, listSharePointDrives } from './api.js'

// Choose a SharePoint site to scan. The counterpart of FolderPicker, and deliberately the same
// shape: a modal over the scan controls that ends in onScan(siteId).
//
// WHY IT LISTS DRIVES AT ALL. Picking a site is the whole decision — the scan reads every
// document library on it (_sp_list iterates drives, #156) — so the library list is shown as
// EVIDENCE, not as a second choice. A team site with four libraries and one with none look
// identical from the site name alone, and the second is the case where a scan returns nothing
// and the operator has no way to tell whether that is the site or the product.
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
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

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

  return (
    <div className="setoverlay" role="dialog" aria-modal="true" aria-label="Choose a SharePoint site">
      <div className="setpanel" style={{ maxWidth: 620 }}>
        <h3 style={{ marginTop: 0 }}>Scan a SharePoint site</h3>
        <p className="muted" style={{ fontSize: 12.5 }}>
          Every document library on the site is scanned. Expand one to see what that includes
          before you commit to it.
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
                <button className="linklike" onClick={() => expand(s)} aria-expanded={open === s.id}>
                  {open === s.id ? '▾' : '▸'} {s.name}
                </button>
                <button className="ghost small" onClick={() => onScan(s.id)}>Scan this site</button>
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

        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button className="ghost small" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  )
}
