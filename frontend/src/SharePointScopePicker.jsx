import { useEffect, useMemo, useState } from 'react'
import { listSharePointSites, listSharePointDrives, listSpFolders } from './api.js'
import { CUSTOMER_SHAREPOINT_URL } from './sharepointDestination.js'
import FolderPicker from './FolderPicker.jsx'
import SitePicker from './SitePicker.jsx'

function location(value) {
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:') return null
    return { origin: url.origin.toLowerCase(), path: decodeURIComponent(url.pathname).replace(/\/+$/, '').toLowerCase() }
  } catch { return null }
}

// Match the actual destination, not a display name that another site can also use.
export function matchingLocation(items, destination) {
  const target = location(destination)
  if (!target) return null
  return items.filter(item => {
    const candidate = location(item.url)
    return candidate && candidate.origin === target.origin
      && (target.path === candidate.path || target.path.startsWith(`${candidate.path}/`))
  }).sort((a, b) => location(b.url).path.length - location(a.url).path.length)[0] || null
}

export default function SharePointScopePicker({ initial = [], initialExclude = [], onChange, ...props }) {
  const [browseSites, setBrowseSites] = useState(() => initial.some(item => !(typeof item === 'string' ? item : item.id).includes('/')))
  const [library, setLibrary] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (browseSites) return
    let live = true
    listSharePointSites().then(async response => {
      const site = matchingLocation(response?.sites || [], CUSTOMER_SHAREPOINT_URL)
      if (!site) throw new Error('The linked SharePoint site is not available to this sign-in. Browse other sites to choose an accessible location.')
      const responseDrives = await listSharePointDrives(site.id)
      const drive = matchingLocation(responseDrives?.drives || [], CUSTOMER_SHAREPOINT_URL)
      if (!drive) throw new Error('The linked Documents library could not be found. Browse other sites to choose a location.')
      if (live) setLibrary({ site, drive })
    }).catch(e => { if (live) setError(e.message || 'Unable to open the linked SharePoint library.') })
    return () => { live = false }
  }, [browseSites])
  const lister = useMemo(() => parent => listSpFolders(parent, library?.drive.id || '', library?.site.id || ''), [library])

  if (browseSites) return <SitePicker {...props} initial={initial} onChange={onChange} />
  return <div>
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.5, minWidth: 0, overflowWrap: 'anywhere' }}>{library ? `${library.site.name} → ${library.drive.name}` : 'Linked SharePoint library'}</span>
      <a href={CUSTOMER_SHAREPOINT_URL} target="_blank" rel="noopener noreferrer">Open SharePoint ↗</a>
      <button type="button" className="linklike" onClick={() => setBrowseSites(true)}>Browse other sites</button>
    </div>
    {error ? <p role="alert">{error}</p> : !library ? <p role="status">Opening the linked Documents library…</p>
      : <FolderPicker {...props} lister={lister} rootName={`${library.site.name} / ${library.drive.name}`}
        sourceName="SharePoint" initial={initial} initialExclude={initialExclude}
        requireSelection showRecursionNote={false} onChange={onChange} />}
  </div>
}
