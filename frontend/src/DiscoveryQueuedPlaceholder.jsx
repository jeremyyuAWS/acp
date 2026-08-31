// The "queued placeholder" from the stakeholder screenshot review: while a NEW scan is queued
// (or tracked pre-listing), the results table below still shows scope/files from the PREVIOUS
// scan — App.jsx only replaces `scan` once the new run settles — with nothing saying so. That
// read as "this is a fresh, empty scan" when it is really "here is what the last one found",
// which is the same silent-stale-number shape this whole session's Discover work keeps closing.
//
// Purely presentational. `previousCount`/`previousAt` are the CURRENT `discoveredCount`/`runAt`
// props at the moment this renders — while queued they ARE the previous run's real numbers,
// since nothing has replaced them yet. `onShowPrevious`, when given, reveals that same data
// (already loaded, not a new fetch) rather than hiding it outright — "previous" is still real
// information, just not this run's.
export default function DiscoveryQueuedPlaceholder({ previousCount, previousAt, onShowPrevious }) {
  const hasPrevious = previousCount != null && previousCount > 0
  return (
    <div role="status" style={{ margin: '12px 0', padding: '18px 16px', borderRadius: 8,
         border: '1px dashed var(--line)', background: 'var(--surface)', textAlign: 'center' }}>
      <div style={{ fontSize: 13, color: 'var(--ink)' }}>
        Discovery results will appear here when this scan finishes. Live progress is shown above.
      </div>
      {hasPrevious && (
        <div style={{ marginTop: 10, fontSize: 12.5 }} className="muted">
          Previous inventory: {previousCount.toLocaleString()} file{previousCount === 1 ? '' : 's'}
          {previousAt?.recorded && <> from {previousAt.absolute}</>}
          {onShowPrevious && (
            <> — <button className="linklike" type="button" onClick={onShowPrevious}>
              View previous run
            </button></>
          )}
        </div>
      )}
    </div>
  )
}
