import { scopeLabel } from './scanScope.js'

export function sourceDisplayName(source, scope) {
  if (scope?.kind === 'sharepoint') {
    const hasSites = !!scope.site || (Array.isArray(scope.sites) && scope.sites.length > 0)
    return hasSites ? 'SharePoint' : 'OneDrive'
  }
  if (scope?.kind === 'drive' || scope?.kind === 'folder' || source === 'drive') return 'Google Drive'
  if (scope?.kind === 'local' || source === 'local') return 'Local corpus'
  if (source === 'sharepoint') return 'SharePoint / OneDrive'
  return source || null
}

export function libraryCount(scope) {
  if (!Array.isArray(scope?.sites)) return 0
  return scope.sites.reduce((count, site) =>
    count + (Array.isArray(site?.libraries) ? site.libraries.length : 0), 0)
}

export function librariesBySite(scope) {
  if (!Array.isArray(scope?.sites)) return []
  return scope.sites.map((site) => ({
    site: site?.name || 'Unnamed site',
    libraries: (Array.isArray(site?.libraries) ? site.libraries : [])
      .map((library) => library?.name || library?.id).filter(Boolean),
  })).filter((row) => row.libraries.length > 0)
}

// Uses the persisted scan boundary, not the currently connected account. A reviewer can switch
// accounts while reading an older run; the card must continue to name where that run came from.
export default function SourceVisibility({ source, scope }) {
  const name = sourceDisplayName(source, scope)
  const boundary = scopeLabel(scope)
  const libraries = scope?.kind === 'sharepoint' ? libraryCount(scope) : 0
  const libraryRows = librariesBySite(scope)
  if (!name && !boundary) return null

  return (
    <div aria-label="Content source" className="muted"
         style={{ fontSize: 12.5, lineHeight: 1.5, margin: '-5px 0 12px' }}>
      <span>Content source · </span><strong style={{ color: 'var(--ink)' }}>{name}</strong>
      {boundary && <> · {boundary}</>}
      {libraries > 0 && (
        <details style={{ display: 'inline-block', marginLeft: 5 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
            <span aria-hidden="true">· </span>{libraries.toLocaleString()} document librar{libraries === 1 ? 'y' : 'ies'}
          </summary>
          <ul style={{ margin: '5px 0 0 18px', padding: 0 }}>
            {libraryRows.map((row) => (
              <li key={row.site}><strong style={{ color: 'var(--ink)' }}>{row.site}:</strong>{' '}
                {row.libraries.join(', ')}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
