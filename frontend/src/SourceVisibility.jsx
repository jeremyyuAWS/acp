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

// Uses the persisted scan boundary, not the currently connected account. A reviewer can switch
// accounts while reading an older run; the card must continue to name where that run came from.
export default function SourceVisibility({ source, scope }) {
  const name = sourceDisplayName(source, scope)
  const boundary = scopeLabel(scope)
  const libraries = scope?.kind === 'sharepoint' ? libraryCount(scope) : 0
  if (!name && !boundary) return null

  return (
    <div aria-label="Content source" className="muted"
         style={{ fontSize: 12.5, lineHeight: 1.5, margin: '-5px 0 12px' }}>
      <span>Content source · </span><strong style={{ color: 'var(--ink)' }}>{name}</strong>
      {boundary && <> · {boundary}</>}
      {libraries > 0 && <> · {libraries.toLocaleString()} document librar{libraries === 1 ? 'y' : 'ies'}</>}
    </div>
  )
}
