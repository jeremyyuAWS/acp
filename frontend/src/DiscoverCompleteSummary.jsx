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

function n(count) { return Number(count).toLocaleString() }

function CheckRow({ label, kpi }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                  gap: 16, padding: '3px 0' }}>
      <span style={{ fontSize: 13.5, color: 'var(--ink)' }}>
        <span style={{ color: 'var(--green,#1a7f45)', marginRight: 6, fontSize: 12 }}>✓</span>
        {label}
      </span>
      {kpi != null && (
        <span style={{ fontSize: 12.5, color: 'var(--muted)', whiteSpace: 'nowrap',
                       fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
          {kpi}
        </span>
      )}
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
  sources,
  lifecycleRulesCount,
  lifecycleFilesMatched,
  archiveCandidates,
  deleteCandidates,
  tagged,
  saveNew,
  saveUpdated,
  saveUnchanged,
  excInaccessible,
  excMetadataFailure,
  excDeleted,
  inventoryDelta,
  startedAt,
  discoveredAt,
  onAdvance,
  onReviewInventory,
  pendingActions = 0,
  needsAck = false,
}) {
  const elapsed = fmtDuration(startedAt, discoveredAt)

  // Eligibility breakdown
  const notAssessable = (metadataOnlyCount ?? 0) + (unsupportedCount ?? 0)
    + (eligibilityUnknownCount ?? 0) + (excludedCount ?? 0)
  const hasEligibilityBreakdown = notAssessable > 0

  // Metadata quality
  const needsMetadataReview = excMetadataFailure ?? 0
  const metadataComplete = Math.max(0, discoveredCount - needsMetadataReview)

  // Lifecycle
  const hasLifecycleRules = lifecycleRulesCount != null && lifecycleRulesCount > 0
  const filesMatched = lifecycleFilesMatched ?? 0

  // Inventory save totals
  const savedTotal = saveNew != null
    ? (saveNew ?? 0) + (saveUpdated ?? 0) + (saveUnchanged ?? 0)
    : null

  // Source and scope
  const sourceCount = sources ? sources.length : null
  const sourceName = sources && sources.length === 1 ? sources[0].name : null

  // Exceptions
  const hasExceptions = ((excInaccessible ?? 0) + (needsMetadataReview) + (excDeleted ?? 0)) > 0

  // Details section: show if any secondary detail is present
  const hasDetails = hasEligibilityBreakdown || hasExceptions || inventoryDelta || sourceCount

  const ctaDisabled = pendingActions > 0 || needsAck

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery complete"
             style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <span style={{ fontSize: 14.5, fontWeight: 650 }}>
            <span style={{ color: 'var(--green,#1a7f45)', marginRight: 6 }}>✓</span>
            Discovery complete
          </span>
          {elapsed && (
            <span className="muted" style={{ fontSize: 12.5, marginLeft: 'auto',
                                             fontVariantNumeric: 'tabular-nums' }}>{elapsed}</span>
          )}
        </div>

        {/* Five-row checklist */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1, marginBottom: 10 }}>

          {/* 1 — Coverage */}
          <CheckRow
            label={`Inventoried ${n(discoveredCount)} files`}
            kpi={[
              folderCount > 0 && `${n(folderCount)} folder${folderCount === 1 ? '' : 's'}`,
              sourceCount && `${n(sourceCount)} source${sourceCount === 1 ? '' : 's'}`,
            ].filter(Boolean).join(' · ') || null}
          />

          {/* 2 — Eligibility */}
          <CheckRow
            label="Classified document eligibility"
            kpi={`${n(assessableCount)} assessable · ${n(notAssessable)} not assessable`}
          />

          {/* 3 — Metadata quality */}
          <CheckRow
            label="Read document metadata"
            kpi={needsMetadataReview > 0
              ? `${n(metadataComplete)} complete · ${n(needsMetadataReview)} need review`
              : `${n(discoveredCount)} complete`}
          />

          {/* 4 — Lifecycle */}
          <CheckRow
            label={hasLifecycleRules
              ? `Applied ${n(lifecycleRulesCount)} lifecycle rule${lifecycleRulesCount === 1 ? '' : 's'}`
              : 'No lifecycle rules enabled'}
            kpi={hasLifecycleRules ? `${n(discoveredCount)} files evaluated` : null}
          />

          {/* 5 — Inventory saved */}
          {savedTotal != null && (
            <CheckRow
              label="Saved inventory"
              kpi={`${n(savedTotal)} record${savedTotal === 1 ? '' : 's'}`}
            />
          )}
        </div>

        {/* Lifecycle results sub-section */}
        {hasLifecycleRules && (filesMatched > 0 || archiveCandidates > 0 || deleteCandidates > 0 || tagged > 0) && (
          <div style={{ fontSize: 12.5, color: 'var(--muted)', paddingLeft: 18,
                        marginBottom: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {filesMatched > 0 && (
              <div>
                {n(filesMatched)} file{filesMatched === 1 ? '' : 's'} matched one or more rules
              </div>
            )}
            {(archiveCandidates > 0 || deleteCandidates > 0 || tagged > 0) && (
              <div>
                {[
                  archiveCandidates > 0 && `${n(archiveCandidates)} Archive Candidate${archiveCandidates === 1 ? '' : 's'}`,
                  deleteCandidates > 0 && `${n(deleteCandidates)} Delete Candidate${deleteCandidates === 1 ? '' : 's'}`,
                  tagged > 0 && `${n(tagged)} tagged`,
                ].filter(Boolean).join(' · ')}
              </div>
            )}
          </div>
        )}

        {/* Disclaimer */}
        <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 10px', lineHeight: 1.5 }}>
          No documents were assessed, moved, or changed.
        </p>

        {/* Expandable details */}
        {hasDetails && (
          <details style={{ marginBottom: 10 }}>
            <summary style={{ fontSize: 12.5, color: 'var(--ink)', cursor: 'pointer',
                              userSelect: 'none', listStyle: 'none', display: 'inline-flex',
                              alignItems: 'center', gap: 4 }}>
              View details
            </summary>
            <div style={{ paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 10,
                          fontSize: 12.5, color: 'var(--muted)' }}>

              {/* Eligibility breakdown */}
              {hasEligibilityBreakdown && (
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: 3 }}>
                    Assessment eligibility
                  </div>
                  {(metadataOnlyCount ?? 0) > 0 && (
                    <div>{n(metadataOnlyCount)} metadata-only</div>
                  )}
                  {(unsupportedCount ?? 0) > 0 && (
                    <div>{n(unsupportedCount)} unsupported format</div>
                  )}
                  {(eligibilityUnknownCount ?? 0) > 0 && (
                    <div>{n(eligibilityUnknownCount)} eligibility unknown</div>
                  )}
                  {(excludedCount ?? 0) > 0 && (
                    <div>{n(excludedCount)} excluded by policy</div>
                  )}
                  {(lockedCount ?? 0) > 0 && (
                    <div>{n(lockedCount)} could not be opened</div>
                  )}
                </div>
              )}

              {/* Exceptions */}
              {hasExceptions ? (
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: 3 }}>
                    Exceptions
                  </div>
                  {(excInaccessible ?? 0) > 0 && (
                    <div>{n(excInaccessible)} inaccessible — skipped</div>
                  )}
                  {(excMetadataFailure ?? 0) > 0 && (
                    <div>{n(excMetadataFailure)} unreadable — skipped</div>
                  )}
                  {(excDeleted ?? 0) > 0 && (
                    <div>{n(excDeleted)} deleted during scan</div>
                  )}
                </div>
              ) : (
                <div>No exceptions</div>
              )}

              {/* Inventory delta */}
              {inventoryDelta && (inventoryDelta.new > 0 || inventoryDelta.updated > 0 || inventoryDelta.unchanged > 0) && (
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: 3 }}>
                    Changes since previous Discovery
                  </div>
                  <div>
                    {[
                      inventoryDelta.new > 0 && `${n(inventoryDelta.new)} added`,
                      inventoryDelta.updated > 0 && `${n(inventoryDelta.updated)} changed`,
                      inventoryDelta.unchanged > 0 && `${n(inventoryDelta.unchanged)} unchanged`,
                    ].filter(Boolean).join(' · ')}
                  </div>
                </div>
              )}

              {/* Source info */}
              {sourceName && (
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: 3 }}>Source</div>
                  <div>{sourceName}</div>
                </div>
              )}
            </div>
          </details>
        )}

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
