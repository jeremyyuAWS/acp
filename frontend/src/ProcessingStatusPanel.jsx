// PRD "Processing details" panel — Phase 1 slice. One headline + one detail line, matching the
// PRD's own worked example ("Waiting for a worker / 18 jobs are ahead of this scan..."). Purely
// presentational: `derived` is the output of processingState.js, computed by the caller from
// signals it already tracks.
//
// Named ProcessingStatusPanel, not ProcessingDetails: that name was already taken by the
// pre-existing per-file results table (the "View processing details (N landed…)" expandable
// list — see ProcessingDetails.jsx/processingDetails.js, #642/#655) — a genuinely different
// feature this file nearly clobbered by mistake before the collision was caught and reverted.
//
// Deliberately does NOT attempt a pickup-time estimate (PRD §9): no processing-time history is
// tracked yet to base a confidence-scored range on, and a fabricated one would be exactly the
// false certainty the PRD's own principle warns against ("show evidence, not false certainty").
// Says so explicitly instead of silently omitting the topic.
const SEVERITY_COLORS = {
  blocked: { bg: '#FBE9E7', border: '#E7B4AC', ink: '#8A2A20' },
  warning: { bg: '#FAEEDA', border: '#D4A017', ink: '#7A5800' },
  waiting: { bg: '#EEF4FB', border: '#B7D3EE', ink: '#1B4C7A' },
  active: { bg: '#E7F0DC', border: '#C9E0B0', ink: '#3B6D11' },
  info: { bg: 'var(--surface)', border: 'var(--line)', ink: 'var(--ink)' },
}

export default function ProcessingStatusPanel({ derived, onStartWorkers, onViewMonitor }) {
  const { state, headline, detail, recommendedAction, severity } = derived || {}
  if (!state || state === 'idle') return null
  const c = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info

  return (
    <div role="status" aria-label="Processing status" style={{ margin: '8px 0', padding: '10px 14px',
         borderRadius: 8, fontSize: 13, background: c.bg, border: `1px solid ${c.border}`, color: c.ink }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
        <b>{headline}</b>
        {onViewMonitor && (
          <button onClick={onViewMonitor} className="linklike" style={{ fontSize: 12, color: 'inherit' }}>
            View in Monitor →
          </button>
        )}
      </div>
      {detail && <div style={{ marginTop: 3, fontWeight: 400 }}>{detail}</div>}
      {recommendedAction === 'start_workers' && onStartWorkers && (
        <button onClick={onStartWorkers} style={{ marginTop: 8, padding: '4px 12px', borderRadius: 5,
                 border: `1px solid ${c.ink}`, background: c.ink, color: '#fff', fontSize: 12,
                 fontWeight: 600, cursor: 'pointer' }}>
          Start workers
        </button>
      )}
      {recommendedAction === 'check_worker_service' && (
        <div style={{ marginTop: 4, fontSize: 12 }}>
          Check that the worker service is reachable and that documents are not repeatedly failing.
        </div>
      )}
      {(state === 'waiting' || state === 'no_capacity') && (
        <div className="muted" style={{ marginTop: 4, fontSize: 11.5, fontStyle: 'italic' }}>
          Pickup time not available — not enough completed-job history is tracked yet to estimate one.
        </div>
      )}
    </div>
  )
}
