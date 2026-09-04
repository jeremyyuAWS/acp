// "SharePoint site coverage" — per-SITE progress during a multi-site run, and the per-site
// outcome after it.
//
// WHY IT EXISTS. A thirty-site estate walk is otherwise a single silent bar: the aggregate file
// count ticks up and nothing says which site it is on, which have finished, or that site 7 was
// unreadable. Worse, the run's grand total cannot answer the question an operator actually has —
// a site that held nothing and a site that was never opened contribute the same zero to it. This
// is the surface that makes "no site was silently omitted" checkable rather than asserted.
//
// LIVE AND HISTORICAL FROM ONE SHAPE. `sites` is `progress.sites` while the scan runs (emitted
// per site as each resolves — api/handlers._listing_progress) and `scope.sites` afterwards
// (persisted on scan_runs.scope by scanner._list). They are the same rows, deliberately: a
// separate "final report" shape would be a second thing to keep true, and the one that drifted
// would be the one nobody was watching.
//
// Renders nothing for a run with no sites — OneDrive, a folder scan, Google Drive, a local
// corpus. Nothing to show is different from loading and must not look like it.
const STATUS = {
  complete: { text: 'Scanned', ink: 'var(--success-fg)', icon: '✓' },
  partial: { text: 'Partial', ink: '#7A5800', icon: '⚠' },
  blocked: { text: 'Could not read', ink: 'var(--error-fg-strong)', icon: '✗' },
  // Never opened — the cap, or the file budget spent before this site was reached. Distinct from
  // 'blocked' because the fix is different: a second scan or a higher limit, not a permission.
  skipped: { text: 'Not scanned', ink: '#7A5800', icon: '–' },
  scanning: { text: 'Scanning', ink: 'var(--ink)', icon: '' },
  queued: { text: 'Queued', ink: 'var(--muted-fg, #666)', icon: '' },
}

export default function SiteActivity({ sites }) {
  const list = Array.isArray(sites) ? sites.filter(Boolean) : []
  if (list.length === 0) return null

  const done = list.filter((s) => s.status === 'complete').length
  const unread = list.filter((s) => s.status === 'blocked' || s.status === 'skipped').length

  return (
    <div role="status" aria-label="SharePoint site coverage"
         style={{ margin: '8px 0', padding: '10px 14px', borderRadius: 8, fontSize: 12.5,
                  background: 'var(--surface)', border: '1px solid var(--line)' }}>
      <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.02em',
                    fontWeight: 600 }} className="muted">
        SharePoint site coverage
      </div>
      {/* The headline is "of how many", not "how many" — a count of finished sites with no
          denominator is the same missing-boundary failure the scope sentence exists to stop. */}
      <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
        {done} of {list.length} site{list.length === 1 ? '' : 's'} scanned
        {unread > 0 && ` · ${unread} not read`}
      </div>
      <ul style={{ margin: '6px 0 0', padding: 0, listStyle: 'none', display: 'flex',
                   flexDirection: 'column', gap: 4 }}>
        {list.map((s) => {
          const st = STATUS[s.status] || STATUS.queued
          const libs = Array.isArray(s.libraries) ? s.libraries : []
          return (
            <li key={s.id} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {s.status === 'scanning' && <span className="pulsedot" aria-hidden="true" />}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={s.id}>
                  {/* The id is a compound Graph string (host,guid,guid) and names nothing to a
                      reader — shown only as a title, never as the label. */}
                  {s.name || 'unnamed site'}
                </span>
                {/* Text, not colour or an icon alone: the icon is decorative and this is what a
                    screen reader announces. */}
                <span style={{ color: st.ink, fontSize: 10.5, flexShrink: 0 }}>
                  {st.icon && <span aria-hidden="true">{st.icon} </span>}{st.text}
                </span>
                {Number.isFinite(s.listed) && (
                  <span className="muted" style={{ fontSize: 10.5, flexShrink: 0 }}>
                    {s.listed.toLocaleString()} document{s.listed === 1 ? '' : 's'}
                  </span>
                )}
              </div>
              {/* WHICH LIBRARIES, because "every document library on the site" is a claim the
                  reader can only check against the list of them — and a site with four libraries
                  and one with none look identical from the site name alone. */}
              {libs.length > 0 && (
                <span className="muted" style={{ fontSize: 10.5, paddingLeft: 2 }}>
                  {libs.length} librar{libs.length === 1 ? 'y' : 'ies'}:{' '}
                  {libs.map((l, i) => {
                    const mode = l.mode === 'delta' ? 'incremental' : l.mode === 'full' ? 'full scan' : null
                    const changes = l.mode === 'delta'
                      ? [Number.isFinite(l.changed) && `${l.changed.toLocaleString()} changed`,
                         Number.isFinite(l.removed) && `${l.removed.toLocaleString()} removed`]
                        .filter(Boolean).join(' · ')
                      : null
                    return <span key={l.id || `${s.id}-${i}`}>
                      {i > 0 && ', '}{l.name || l.id}
                      {mode && <> ({mode}{changes ? ` · ${changes}` : ''})</>}
                    </span>
                  })}
                </span>
              )}
              {/* Verbatim. "Sites.Read.All" and "429" are different problems with different
                  owners, and flattening them to "unavailable" sends an operator to the wrong one. */}
              {s.error && (
                <span style={{ fontSize: 10.5, color: st.ink, paddingLeft: 2 }}>{s.error}</span>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
