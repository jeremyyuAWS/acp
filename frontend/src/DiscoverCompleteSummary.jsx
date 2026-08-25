// Shown after a discovery scan completes — an immutable snapshot of what was found, with a
// prominent CTA to continue to Assess. Replaces the per-run progress card (DiscoverRunProgress
// returns null once busy=false) and anchors the top of the Discover tab to a clear "what next".

function StatRow({ count, label, muted = false }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
      <span style={{ fontSize: 18, fontWeight: 650, fontVariantNumeric: 'tabular-nums',
                     color: muted ? 'var(--muted)' : 'var(--ink)', minWidth: 36,
                     textAlign: 'right' }}>
        {count.toLocaleString()}
      </span>
      <span style={{ fontSize: 13.5, color: muted ? 'var(--muted)' : 'var(--ink)' }}>
        {label}
      </span>
    </div>
  )
}

export default function DiscoverCompleteSummary({
  discoveredCount,
  assessableCount,
  nonAssessableCount,
  lockedCount,
  lifecycleRulesCount,
  onAdvance,
  pendingActions = 0,
  needsAck = false,
}) {
  const excluded = discoveredCount - assessableCount - nonAssessableCount - lockedCount

  return (
    <section className="discover-run-progress" role="region" aria-label="Discovery complete"
             style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
      <div className="assess-run-card" style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 12,
                                                padding: '14px 16px', background: 'var(--panel,#fff)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                      gap: 16, flexWrap: 'wrap' }}>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: 14.5, fontWeight: 650, marginBottom: 4 }}>
              <span style={{ color: 'var(--green,#1a7f45)', marginRight: 6 }}>✓</span>
              Discovery complete
            </div>

            <StatRow count={assessableCount} label="eligible for assessment" />
            {nonAssessableCount > 0 && (
              <StatRow count={nonAssessableCount}
                       label="non-assessable (images, video, unsupported formats)" muted />
            )}
            {lockedCount > 0 && (
              <StatRow count={lockedCount} label="could not be opened (password-protected)" muted />
            )}
            {excluded > 0 && (
              <StatRow count={excluded} label="excluded by policy" muted />
            )}
            {lifecycleRulesCount !== null && lifecycleRulesCount > 0 && (
              <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
                {lifecycleRulesCount} lifecycle rule{lifecycleRulesCount === 1 ? '' : 's'} applied
              </div>
            )}
          </div>

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
