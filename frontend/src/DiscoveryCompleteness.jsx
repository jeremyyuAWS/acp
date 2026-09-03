import { COMPARISON_SCOPE, enumerationMethod, previousListing } from './discoveryCompleteness.js'

// "Is this the whole estate?" — the question Discovery exists to answer, asked out loud.
//
// The results screen says what was found. This says how much to trust that it is everything, which
// is a different question and the one every number downstream depends on.
//
// It renders NOTHING when it has nothing to say. A panel that appears on every run saying "this
// might be incomplete" is decoration: it is true of all software, warns nobody, and trains the
// reader to skip the box that will one day carry a real signal.

const fmt = (n) => Number(n || 0).toLocaleString()
const pct = (x) => `${Math.abs(Math.round(x * 100))}%`

const Row = ({ tone = 'muted', children }) => (
  <p style={{
    margin: '8px 0 0', fontSize: 13, lineHeight: 1.6,
    ...(tone === 'warn'
      ? { color: 'var(--warn-fg)', background: 'var(--warn-bg)', border: '1px solid #E8C98A',
          borderRadius: 8, padding: '10px 12px' }
      : { color: 'var(--muted)' }),
  }}>{children}</p>
)

/**
 * @param run       the current scan run — `source` and `scope.inventory` are what it reads.
 * @param scanList  prior scans (newest first), for the previous-listing comparison. Optional.
 * @param onRelist  optional; offers the re-list that resolves an index-lag doubt.
 */
export default function DiscoveryCompleteness({ run, scanList = null, onRelist = null }) {
  if (!run) return null

  // The SCOPE decides this, not the source alone: a SharePoint run narrowed to chosen folders
  // walks them directly and never touches the search index, so warning about index lag over
  // it would be a false alarm on a correct run.
  const method = enumerationMethod(run.source, run.scope || null)
  const prev = previousListing(run, scanList)

  // An immediately-consistent source with no prior run to compare has nothing to report. Saying
  // "everything looks fine" would be the reassurance this panel exists to avoid giving.
  if (!method && !prev) return null
  if (method && method.consistent && !prev) return null

  return (
    <section className="panel" aria-labelledby="disccomp-h">
      <h2 id="disccomp-h">IS THIS THE WHOLE ESTATE?</h2>

      {/* The listing cap and per-file read failures are stated on the results screen and in the
          reconciliation. This is the third way an inventory goes quietly partial — the source
          itself under-reporting — and nothing said it. */}

      {method && !method.consistent && (
        <Row tone="warn">
          <b>This source is listed through a search index.</b> {method.caveat}
          {method.resolve && <> {method.resolve}</>}
          {onRelist && (
            <> <button className="linklike" type="button" onClick={() => onRelist()}>
              List again
            </button></>
          )}
        </Row>
      )}

      {method && method.consistent && <Row>{method.caveat}</Row>}

      {prev && prev.dropped && (
        <Row tone="warn">
          <b>This run listed {fmt(prev.now)} files. The previous run of this source listed {fmt(prev.was)}</b>
          {prev.share != null && <> — {pct(prev.share)} fewer</>}.
          {' '}That is either a real deletion or an incomplete listing, and discovery cannot tell
          which: it only ever sees what the source hands it. Worth establishing which before you
          assess against this inventory.
        </Row>
      )}

      {prev && !prev.dropped && (
        <Row>
          Previous run of this source listed {fmt(prev.was)} files; this one listed {fmt(prev.now)}
          {prev.delta === 0 ? ' — unchanged' : prev.delta > 0 ? ` — ${fmt(prev.delta)} more` : ` — ${fmt(-prev.delta)} fewer`}.
        </Row>
      )}

      {prev && (
        <p className="muted" style={{ fontSize: 11.5, margin: '10px 0 0', lineHeight: 1.5 }}>
          {COMPARISON_SCOPE}
        </p>
      )}
    </section>
  )
}
