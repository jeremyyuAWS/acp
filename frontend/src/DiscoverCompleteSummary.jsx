// Shown after a discovery scan completes — a flat snapshot of what was found, with a
// prominent CTA to continue to Assess. Replaces the estatebar description section so the
// top of the Discover tab always shows a clear "what happened / what next".

function fmtDuration(startedAt, discoveredAt) {
  if (!startedAt || !discoveredAt) return null
  const ms = Date.parse(discoveredAt) - Date.parse(startedAt)
  if (!isFinite(ms) || ms < 0) return null
  const totalSec = Math.round(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function n(count) { return Number(count).toLocaleString() }

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
  archiveCandidates,
  deleteCandidates,
  tagged,
  excInaccessible,
  excMetadataFailure,
  excDeleted,
  inventoryDelta,
  startedAt,
  discoveredAt,
  publishedAt,
  onAdvance,
  onReviewInventory,
  pendingActions = 0,
  needsAck = false,
}) {
  const elapsed = fmtDuration(startedAt, discoveredAt)
  const ctaDisabled = pendingActions > 0 || needsAck
  const hasLifecycleRules = lifecycleRulesCount != null && lifecycleRulesCount > 0

  // Lifecycle action breakdown pills (only shown when there are results)
  const lifecycleBreakdown = [
    archiveCandidates > 0 && `${n(archiveCandidates)} Archive Candidate${archiveCandidates === 1 ? '' : 's'}`,
    deleteCandidates > 0 && `${n(deleteCandidates)} Delete Candidate${deleteCandidates === 1 ? '' : 's'}`,
    tagged > 0 && `${n(tagged)} tagged`,
  ].filter(Boolean)

  // Exception counts
  const hasExcInaccessible = (excInaccessible ?? 0) > 0
  const hasExcMetadata = (excMetadataFailure ?? 0) > 0
  const hasExcDeleted = (excDeleted ?? 0) > 0
  const hasExceptions = hasExcInaccessible || hasExcMetadata || hasExcDeleted

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery complete"
             style={{ marginBottom: 16 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '16px 18px', background: 'var(--panel,#fff)',
                                                fontSize: 13.5, color: 'var(--ink)' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                      marginBottom: 14 }}>
          <span style={{ fontWeight: 650, fontSize: 14.5 }}>Discovery complete</span>
          {elapsed && (
            <span style={{ fontSize: 13, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
              {elapsed}
            </span>
          )}
        </div>

        {/* File counts */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 14 }}>
          <div>
            Inventoried {n(discoveredCount)} files
            {folderCount > 0 ? ` across ${n(folderCount)} folder${folderCount === 1 ? '' : 's'}` : ''}
          </div>
          <div>{n(assessableCount)} assessable</div>
          {(unsupportedCount ?? 0) > 0 && <div style={{ color: 'var(--muted)' }}>{n(unsupportedCount)} unsupported</div>}
          {(metadataOnlyCount ?? 0) > 0 && <div style={{ color: 'var(--muted)' }}>{n(metadataOnlyCount)} metadata-only</div>}
          {(eligibilityUnknownCount ?? 0) > 0 && <div style={{ color: 'var(--muted)' }}>{n(eligibilityUnknownCount)} eligibility unknown</div>}
          {(excludedCount ?? 0) > 0 && <div style={{ color: 'var(--muted)' }}>{n(excludedCount)} excluded</div>}
          {(lockedCount ?? 0) > 0 && <div style={{ color: 'var(--muted)' }}>{n(lockedCount)} could not be opened</div>}
          {hasExceptions && (
            <div style={{ color: 'var(--muted)', marginTop: 2 }}>
              {[
                hasExcInaccessible && `${n(excInaccessible)} inaccessible — skipped`,
                hasExcMetadata && `${n(excMetadataFailure)} unreadable`,
                hasExcDeleted && `${n(excDeleted)} deleted during scan`,
              ].filter(Boolean).join(' · ')}
            </div>
          )}
        </div>

        {/* Lifecycle + inventory */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 14 }}>
          {hasLifecycleRules ? (
            <>
              <div>
                {n(lifecycleRulesCount)} matched lifecycle rule{lifecycleRulesCount === 1 ? '' : 's'}
              </div>
              {lifecycleBreakdown.length > 0 && (
                <div style={{ color: 'var(--muted)' }}>{lifecycleBreakdown.join(' · ')}</div>
              )}
            </>
          ) : (
            <div style={{ color: 'var(--muted)' }}>No lifecycle rules enabled</div>
          )}
          {inventoryDelta && (inventoryDelta.new > 0 || inventoryDelta.updated > 0 || inventoryDelta.unchanged > 0) && (
            <div>
              {'Inventory: '}
              {[
                inventoryDelta.new > 0 && `${n(inventoryDelta.new)} added`,
                inventoryDelta.updated > 0 && `${n(inventoryDelta.updated)} changed`,
                inventoryDelta.unchanged > 0 && `${n(inventoryDelta.unchanged)} unchanged`,
              ].filter(Boolean).join(' · ')}
            </div>
          )}
          {publishedAt && (
            <div>
              Enumeration verified complete —{' '}
              {new Date(publishedAt).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
            </div>
          )}
        </div>

        {/* Disclaimer */}
        <p style={{ fontSize: 12.5, color: 'var(--muted)', margin: '0 0 14px', lineHeight: 1.5 }}>
          No documents were assessed or changed.
        </p>

        {/* CTA row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {onReviewInventory && (
            <button onClick={onReviewInventory}
                    style={{ fontSize: 13, fontWeight: 500, padding: '6px 14px',
                             background: 'transparent', color: 'var(--ink)',
                             border: '1px solid var(--line,#e4e8ec)', borderRadius: 8,
                             cursor: 'pointer', whiteSpace: 'nowrap' }}>
              Review inventory
            </button>
          )}
          <button onClick={onAdvance}
                  disabled={ctaDisabled}
                  style={{ fontSize: 14, fontWeight: 600, padding: '9px 18px',
                           background: ctaDisabled ? 'var(--muted-bg,#f1eff3)' : 'var(--ink)',
                           color: ctaDisabled ? 'var(--muted)' : 'var(--panel,#fff)',
                           border: 'none', borderRadius: 8,
                           cursor: ctaDisabled ? 'default' : 'pointer',
                           whiteSpace: 'nowrap' }}
                  title={pendingActions > 0
                    ? `${pendingActions} action${pendingActions === 1 ? '' : 's'} still pending`
                    : needsAck ? 'Approve discovery recommendations above to continue' : undefined}>
            Continue to Assessment →
          </button>
          {ctaDisabled && (
            <span className="muted" style={{ fontSize: 12, maxWidth: 240, lineHeight: 1.4 }}>
              {needsAck
                ? 'Approve the recommendations above to continue'
                : `${pendingActions} pending action${pendingActions === 1 ? '' : 's'} — review rows below`}
            </span>
          )}
        </div>
      </div>
    </section>
  )
}
