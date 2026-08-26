// Shown after a discovery scan completes — an immutable snapshot of what was found, with a
// prominent CTA to continue to Assess. Replaces the per-run progress card (DiscoverRunProgress
// returns null once busy=false) and anchors the top of the Discover tab to a clear "what next".

function fmtDuration(startedAt, discoveredAt) {
  if (!startedAt || !discoveredAt) return null
  const ms = Date.parse(discoveredAt) - Date.parse(startedAt)
  if (!isFinite(ms) || ms < 0) return null
  const totalSec = Math.round(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function StatRow({ count, label, muted = false, highlight = false }) {
  const color = highlight ? 'var(--green,#1a7f45)' : muted ? 'var(--muted)' : 'var(--ink)'
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
      <span style={{ fontSize: 18, fontWeight: 650, fontVariantNumeric: 'tabular-nums',
                     color, minWidth: 36, textAlign: 'right' }}>
        {count.toLocaleString()}
      </span>
      <span style={{ fontSize: 13.5, color }}>
        {label}
      </span>
    </div>
  )
}

export default function DiscoverCompleteSummary({
  discoveredCount,
  assessableCount,
  metadataOnlyCount,
  unsupportedCount,
  eligibilityUnknownCount = 0,
  lockedCount,
  excludedCount,
  folderCount,
  lifecycleRulesCount,
  inventoryDelta,
  startedAt,
  discoveredAt,
  onAdvance,
  onReviewInventory,
  pendingActions = 0,
  needsAck = false,
}) {
  const elapsed = fmtDuration(startedAt, discoveredAt)

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery complete"
             style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                      gap: 16, flexWrap: 'wrap' }}>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {/* Header row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 14.5, fontWeight: 650 }}>
                <span style={{ color: 'var(--green,#1a7f45)', marginRight: 6 }}>✓</span>
                Discovery complete
              </span>
              {elapsed && (
                <span className="muted" style={{ fontSize: 12.5 }}>{elapsed}</span>
              )}
            </div>

            {/* Discovered total */}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 2 }}>
              <span style={{ fontSize: 18, fontWeight: 650, fontVariantNumeric: 'tabular-nums',
                             color: 'var(--ink)', minWidth: 36, textAlign: 'right' }}>
                {discoveredCount.toLocaleString()}
              </span>
              <span style={{ fontSize: 13.5, color: 'var(--ink)' }}>
                files discovered{folderCount > 0 ? ` across ${folderCount.toLocaleString()} folder${folderCount === 1 ? '' : 's'}` : ''}
              </span>
            </div>

            {/* Status breakdown */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, paddingLeft: 44, marginBottom: 4 }}>
              <StatRow count={assessableCount} label="assessable" highlight />
              {unsupportedCount > 0 && (
                <StatRow count={unsupportedCount} label="unsupported" muted />
              )}
              {metadataOnlyCount > 0 && (
                <StatRow count={metadataOnlyCount} label="metadata-only" muted />
              )}
              {eligibilityUnknownCount > 0 && (
                <StatRow count={eligibilityUnknownCount} label="eligibility unknown" muted />
              )}
              {lockedCount > 0 && (
                <StatRow count={lockedCount} label="could not be opened (password-protected)" muted />
              )}
              {excludedCount > 0 && (
                <StatRow count={excludedCount} label="excluded by policy" muted />
              )}
            </div>

            {/* Lifecycle rules */}
            {lifecycleRulesCount != null && lifecycleRulesCount > 0 && (
              <div className="muted" style={{ fontSize: 12.5, paddingLeft: 44 }}>
                {lifecycleRulesCount.toLocaleString()} lifecycle rule{lifecycleRulesCount === 1 ? '' : 's'} matched
              </div>
            )}

            {/* Inventory delta */}
            {inventoryDelta && (inventoryDelta.new > 0 || inventoryDelta.updated > 0 || inventoryDelta.unchanged > 0) && (
              <div style={{ fontSize: 12.5, color: 'var(--muted)', paddingLeft: 44, marginTop: 2 }}>
                Inventory:&ensp;
                {inventoryDelta.new > 0 && (
                  <span style={{ color: 'var(--green,#1a7f45)', fontWeight: 600 }}>
                    {inventoryDelta.new.toLocaleString()} new
                  </span>
                )}
                {inventoryDelta.new > 0 && inventoryDelta.updated > 0 && ' · '}
                {inventoryDelta.updated > 0 && (
                  <span style={{ fontWeight: 600 }}>
                    {inventoryDelta.updated.toLocaleString()} updated
                  </span>
                )}
                {(inventoryDelta.new > 0 || inventoryDelta.updated > 0) && inventoryDelta.unchanged > 0 && ' · '}
                {inventoryDelta.unchanged > 0 && (
                  <span>{inventoryDelta.unchanged.toLocaleString()} unchanged</span>
                )}
              </div>
            )}
          </div>

          {/* CTA column */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
                        gap: 8, flexShrink: 0 }}>
            <button onClick={onAdvance}
                    disabled={pendingActions > 0 || needsAck}
                    style={{ fontSize: 14, fontWeight: 600, padding: '9px 18px',
                             background: pendingActions > 0 || needsAck ? 'var(--muted-bg,#f1eff3)' : 'var(--ink)',
                             color: pendingActions > 0 || needsAck ? 'var(--muted)' : 'var(--panel,#fff)',
                             border: 'none', borderRadius: 8, cursor: pendingActions > 0 || needsAck ? 'default' : 'pointer',
                             whiteSpace: 'nowrap' }}
                    title={pendingActions > 0
                      ? `${pendingActions} action${pendingActions === 1 ? '' : 's'} still pending`
                      : needsAck ? 'Approve discovery recommendations above to continue' : undefined}>
              Continue to Assessment →
            </button>
            {onReviewInventory && (
              <button onClick={onReviewInventory}
                      style={{ fontSize: 13, fontWeight: 500, padding: '6px 14px',
                               background: 'transparent', color: 'var(--ink)',
                               border: '1px solid var(--line,#e4e8ec)', borderRadius: 8,
                               cursor: 'pointer', whiteSpace: 'nowrap' }}>
                Review inventory
              </button>
            )}
            {(pendingActions > 0 || needsAck) && (
              <span className="muted" style={{ fontSize: 12, textAlign: 'right', maxWidth: 220 }}>
                {needsAck
                  ? 'Approve the recommendations above to continue'
                  : `${pendingActions} pending action${pendingActions === 1 ? '' : 's'} — review rows below`}
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
