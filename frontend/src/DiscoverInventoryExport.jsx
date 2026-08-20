import { useMemo, useState } from 'react'
import { inventorySnapshot } from './discoverRunTime.js'
import { csvBlob, jsonBlob, saveBlob } from './inventoryExport.js'

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
    save(out.blob, out.filename)
    setSaved({ kind, filename: out.filename, rowCount: out.rowCount, omitted: out.omitted })
  }

  // Computed for the on-screen note without downloading anything, so the reader can see which
  // columns dropped out before they commit to a file.
  const preview = useMemo(
    () => (unread ? null : csvBlob(list, { scanId: scanId ?? run?.id ?? null, takenAt: snap.at })),
    [list, scanId, run, snap.at, unread],
  )

  return (
    <section className="discover-inventory-export" aria-label="Discovery inventory export">
      <h3 style={{ margin: '0 0 4px', fontSize: 16 }}>Inventory snapshot</h3>

      {/* ── When ─────────────────────────────────────────────────────────────── */}
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
          <span className="muted">{snap.note}</span>
        </p>
      )}
      <p className="muted" style={{ fontSize: 12, margin: '0 0 12px' }}>
        {snap.recorded
          ? `Every count on this screen is true as of that instant — ${snap.label}.`
          : 'Re-run discovery to get a dated snapshot.'}
      </p>

      {/* ── What comes out ───────────────────────────────────────────────────── */}
      {unread ? (
        <p className="muted" style={{ fontSize: 13 }}>
          The inventory could not be read, so there is nothing to export. This is not an empty
          estate — it means the per-file list did not come back.
        </p>
      ) : (
        <>
          <p style={{ fontSize: 13, margin: '0 0 8px' }}>
            {nf.format(preview.rowCount)} file{preview.rowCount === 1 ? '' : 's'} ·{' '}
            {preview.columns.length} column{preview.columns.length === 1 ? '' : 's'}
          </p>
          <p className="muted" style={{ fontSize: 12, margin: '0 0 10px' }}>
            Metadata only. Discovery lists and classifies from what the source reports; it never
            opens a file, so the export carries no findings, scores or conformance verdicts. A
            discovered file has no assessment — which is not the same as a clean one.
          </p>
          <p className="muted" style={{ fontSize: 12, margin: '0 0 10px' }}>
            In the CSV, <code>(not collected)</code> means discovery recorded no value; an empty
            cell means it recorded an empty one. The JSON uses <code>null</code> for the first.
          </p>
          {preview.omitted.length > 0 && (
            <p className="muted" style={{ fontSize: 12, margin: '0 0 10px' }}>
              Not shipped, because every row was empty:{' '}
              {preview.omitted.map((o) => o.header).join(', ')}.
            </p>
          )}

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" onClick={() => build('csv')} disabled={preview.rowCount === 0}>
              Export CSV
            </button>
            <button type="button" onClick={() => build('json')} disabled={preview.rowCount === 0}>
              Export JSON
            </button>
          </div>
          {preview.rowCount === 0 && (
            <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              This run inventoried no files, so there is nothing to export.
            </p>
          )}
          {saved && (
            <p className="muted" role="status" style={{ fontSize: 12, marginTop: 8 }}>
              Saved {saved.filename} — {nf.format(saved.rowCount)} row
              {saved.rowCount === 1 ? '' : 's'}.
            </p>
          )}
        </>
      )}
    </section>
  )
}
