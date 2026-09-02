import { useMemo, useState } from 'react'
import { inventorySnapshot } from './discoverRunTime.js'
import { csvBlob, jsonBlob, saveBlob, toCsv } from './inventoryExport.js'

// The Discover results block that dates the inventory and lets an operator take it out of ACP.
//
// Two jobs, together because they are the same claim: THIS list, as of THAT instant. A download
// with no snapshot time is a compliance artifact nobody can date, and a snapshot time on screen
// that the download does not carry is a fact that evaporates the moment the file is filed.
//
// STANDALONE ON PURPOSE. Discover.jsx, Overview.jsx and the rest of the Discover surface are
// claimed by open PRs (#539/#540/#541/#546/#549/#550/#551/#552), so this renders nowhere yet — a
// follow-up mounts it once they land. Every behaviour below is therefore pinned by a DOM test
// rather than by a screenshot; vite serves the shared checkout, not this worktree, so a browser
// check here would exercise code that does not contain this file (CLAUDE.md).

const nf = new Intl.NumberFormat('en-US')

const CHIP = {
  fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
  color: 'var(--warn-fg, #9a6a12)', background: 'var(--warn-bg, #f6ecd6)',
}

export default function DiscoverInventoryExport({
  scanId = null,
  run = null,
  inventory = null,
  rows = null,
  now = undefined,
  // Seams. Tests inject a recorder instead of driving a real download, and `clock` stamps
  // `exported_at` — which is when the FILE was written, never the snapshot instant.
  save = saveBlob,
  clock = () => new Date().toISOString(),
  compact = false,
  showActions = true,
}) {
  const [saved, setSaved] = useState(null)
  const list = rows || (inventory && Array.isArray(inventory.rows) ? inventory.rows : null)

  const snap = useMemo(
    () => inventorySnapshot({ run, inventory, rows: list, ...(now === undefined ? {} : { now }) }),
    [run, inventory, list, now],
  )

  // A read that failed is not an empty estate. discoveryInventory.loadDiscoveryInventory returns
  // null for a partial or failed read precisely so this distinction survives, and a 403 rendered
  // as "0 files, export away" would produce an authoritative-looking empty CSV.
  const unread = list === null

  const build = (kind) => {
    const opts = { scanId: scanId ?? run?.id ?? null, takenAt: snap.at,
      takenAtSource: snap.source, exportedAt: clock() }
    const out = kind === 'json' ? jsonBlob(list, opts) : csvBlob(list, opts)
    // Only claim it was saved if the save reported that it was. `saveBlob` returns false when
    // there is no DOM to hand the blob to, and "Saved acp-inventory-….csv" over a download that
    // never happened is the same class of untruth the rest of this module exists to avoid.
    if (save(out.blob, out.filename) === false) return
    setSaved({ kind, filename: out.filename, rowCount: out.rowCount, omitted: out.omitted })
  }

  // Computed for the on-screen note without downloading anything, so the reader can see which
  // columns dropped out before they commit to a file. `toCsv`, not `csvBlob` — a preview that
  // allocated a Blob on every render would be building a file nobody asked for.
  const preview = useMemo(
    () => (unread ? null : toCsv(list, { scanId: scanId ?? run?.id ?? null, takenAt: snap.at })),
    [list, scanId, run, snap.at, unread],
  )

  const canExport = !unread && preview && preview.rowCount > 0

  const actions = !unread && preview && showActions ? (
    <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
      <button type="button" onClick={() => build('csv')} disabled={!canExport}>
        Export CSV
      </button>
      <button type="button" onClick={() => build('json')} disabled={!canExport}>
        Export JSON
      </button>
    </div>
  ) : null

  if (compact) {
    if (!actions) return null
    return (
      <div role="toolbar" aria-label="Inventory export actions" style={{ position: 'sticky', top: 8,
                       zIndex: 40, display: 'flex', justifyContent: 'flex-end', margin: '8px 0 10px',
                       padding: '7px 8px', background: 'var(--bg)',
                       border: '1px solid var(--line)', borderRadius: 12,
                       boxShadow: '0 4px 14px rgba(40, 30, 48, 0.08)' }}>
        {actions}
        <span className="sronly" role="status">{saved ? `Saved ${saved.filename}` : ''}</span>
      </div>
    )
  }

  return (
    <section className="discover-inventory-export" aria-label="Discovery inventory export">
      {/* Header row: title left, export buttons right */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: 12, flexWrap: 'wrap', marginBottom: 6 }}>
        <h3 style={{ margin: 0, fontSize: 16 }}>Inventory snapshot</h3>
        {!unread && preview && (
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            <button type="button" onClick={() => build('csv')} disabled={!canExport}>
              Export CSV
            </button>
            <button type="button" onClick={() => build('json')} disabled={!canExport}>
              Export JSON
            </button>
          </div>
        )}
      </div>

      {/* Snapshot time */}
      {snap.recorded ? (
        <p style={{ margin: '0 0 2px', fontSize: 13.5 }}>
          Inventory taken{' '}
          <strong>
            <time dateTime={snap.at}>{snap.absolute}</time>
          </strong>{' '}
          <span className="muted">({snap.relative})</span>{' '}
          {snap.stale && <span style={CHIP}>SNAPSHOT MAY BE STALE</span>}
        </p>
      ) : (
        <p style={{ margin: '0 0 2px', fontSize: 13.5 }}>
          <strong>Discovery completion time not recorded for this run.</strong>{' '}
          <span className="muted">{snap.note ?? 'Re-run discovery to get a dated snapshot.'}</span>
        </p>
      )}
      {snap.recorded && (
        <p className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
          {snap.label}.
        </p>
      )}

      {unread ? (
        <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
          The inventory could not be read, so there is nothing to export. This is not an empty
          estate — it means the per-file list did not come back.
        </p>
      ) : (
        <>
          <p style={{ fontSize: 13, margin: '4px 0 0' }}>
            {nf.format(preview.rowCount)} file{preview.rowCount === 1 ? '' : 's'} ·{' '}
            {preview.columns.length} column{preview.columns.length === 1 ? '' : 's'}
          </p>
          <p className="muted" style={{ fontSize: 12, margin: '4px 0 8px' }}>
            Metadata only — no findings, scores or conformance verdicts. In the CSV,{' '}
            <code>(not collected)</code> means discovery recorded no value; an empty cell means it
            recorded an empty one. The JSON uses <code>null</code> for the first.
          </p>
          {preview.omitted.length > 0 && (
            <p className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
              Not shipped, because every row was empty:{' '}
              {preview.omitted.map((o) => o.header).join(', ')}.
            </p>
          )}
          {preview.rowCount === 0 && (
            <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              This run inventoried no files, so there is nothing to export.
            </p>
          )}
          {/* Mounted empty so a screen reader observes it before the download fires. */}
          <p className="muted" role="status" style={{ fontSize: 12, marginTop: 6 }}>
            {saved
              ? `Saved ${saved.filename} — ${nf.format(saved.rowCount)} row${saved.rowCount === 1 ? '' : 's'}.`
              : ''}
          </p>
        </>
      )}
    </section>
  )
}
