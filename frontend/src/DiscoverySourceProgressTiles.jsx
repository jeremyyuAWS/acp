import LiveCounter from './LiveCounter.jsx'
import './discovery-source-progress-tiles.css'

const count = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
const finished = phase => ['lifecycle', 'analysing', 'scoring', 'finalizing', 'done'].includes(phase)

export default function DiscoverySourceProgressTiles({ source, scope, progress, freshness }) {
  if (source !== 'sharepoint' && scope?.kind !== 'sharepoint') return null
  const files = count(progress?.files_found), folders = count(progress?.folders_visited) ?? count(progress?.folders_found)
  const savedNew = count(progress?.save_new), savedUpdated = count(progress?.save_updated)
  const saved = savedNew === null && savedUpdated === null ? null : (savedNew ?? 0) + (savedUpdated ?? 0)
  const attention = ['exc_inaccessible_file', 'exc_metadata_failure', 'exc_deleted_during_scan'].reduce((sum, key) => sum + (count(progress?.[key]) ?? 0), 0)
  const sites = Array.isArray(progress?.sites) ? progress.sites.filter(Boolean) : []
  const libraries = sites.flatMap(site => Array.isArray(site.libraries) ? site.libraries.filter(Boolean) : [])
  const activeSite = sites.find(site => site.status === 'scanning')
  const activeLibrary = activeSite?.active_library
  const throttles = libraries.reduce((sum, library) => sum + (count(library.throttled) ?? 0), 0)
  const modes = new Set(libraries.map(library => library.mode).filter(Boolean))
  const mode = modes.size > 1 ? 'Mixed enumeration' : modes.has('delta') ? 'Incremental enumeration'
    : modes.has('search') ? 'Search-index enumeration' : modes.has('full') ? 'Full enumeration' : null
  const isFinished = finished(progress?.phase)
  const signal = freshness ?? progress?.freshness
  const live = signal === 'live' && ['discovering', 'reading', 'tagging', 'saving'].includes(progress?.phase)
  const updateLabel = signal === 'live' ? 'Live discovery updates connected' : signal === 'reconnecting' ? 'Live updates reconnecting'
    : signal === 'checkpoint' ? 'Showing latest checkpoint' : signal === 'stale' ? 'Live data is stale' : 'Update status unavailable'
  const tiles = [
    ['Documents Found', files, 'Documents recorded in this inventory'],
    ['Folders Visited', folders, 'Includes selected roots and visited subfolders'],
    ['Inventory Saved', saved, 'New and updated inventory records'],
    ...(attention ? [['Needs Attention', attention, 'Skipped or unreadable items']] : []),
  ]
  return <section className="discovery-source-progress" aria-label="Source discovery progress">
    <header><strong>{isFinished ? 'Source Inventory Collected' : 'Reading Source Inventory'}</strong><span className="muted">{updateLabel}</span></header>
    <dl className="discovery-source-progress__tiles">
      {tiles.map(([label, value, detail]) => <div key={label} className={`discovery-source-progress__tile${live ? ' is-live' : ''}${label === 'Needs Attention' ? ' needs-attention' : ''}`}>
        <dt>{label}</dt><dd>{value === null ? <span className="discovery-source-progress__unknown">Not Reported Yet</span> : <LiveCounter value={value}/>}</dd><small>{detail}</small>
        {live && <span className="discovery-source-progress__signal" aria-hidden="true"/>}
      </div>)}
    </dl>
    {activeLibrary && !isFinished && <p>Reading <strong>{activeSite.name || 'SharePoint'}</strong> / {activeLibrary.name || activeLibrary.id}</p>}
    {sites.length > 0 && <details><summary>Site and library coverage</summary><p>{sites.filter(site => site.status === 'complete').length} of {sites.length} sites read{libraries.length > 0 && <> · {libraries.filter(library => library.status === 'complete').length} of {libraries.length} libraries complete</>}</p>
      {mode && <p>{mode}</p>}{throttles > 0 && <p>{throttles.toLocaleString()} Graph retr{throttles === 1 ? 'y' : 'ies'}</p>}
      {sites.some(site => ['partial', 'blocked', 'skipped'].includes(site.status)) && <p>{sites.filter(site => ['partial', 'blocked', 'skipped'].includes(site.status)).length} sites need attention</p>}
    </details>}
  </section>
}
