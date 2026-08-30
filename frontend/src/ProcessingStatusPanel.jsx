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

export default function ProcessingStatusPanel({ derived, onStartWorkers, onRerun, onViewMonitor }) {
  const { state, headline, detail, recommendedAction, severity, pickupUnavailable, live,
          facts, next, comingSoon, noWorkerAvailable } = derived || {}
  if (!state || state === 'idle') return null
  const c = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info

  return (
    <div role="status" aria-label="Processing status" style={{ margin: '8px 0', padding: '10px 14px',
         borderRadius: 8, fontSize: 13, background: c.bg, border: `1px solid ${c.border}`, color: c.ink }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <b>{headline}</b>
          {/* Same green live-indicator dot already used elsewhere (QueuePanel, Monitor's audit
              trail, DiscoverRunProgress's own freshness badge per #916) — reused, not reinvented,
              so "near real-time" reads as the same signal wherever it appears. Driven by the
              `live` flag a caller's derivation sets from its own freshness/SSE signal, not
              inferred from severity here — a caller with no such signal simply never sets it. */}
          {live && (
            <span title="Receiving live updates for this scan" role="status"
                  style={{ fontSize: 11, padding: '1px 7px', borderRadius: 4,
                           background: 'var(--green-bg,#f0f7e6)', color: 'var(--green,#3B6D11)',
                           border: '1px solid var(--green-line,#a8cf7a)',
                           display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span className="pulsedot" aria-hidden="true" /> live
            </span>
          )}
        </span>
        {onViewMonitor && (
          <button onClick={onViewMonitor} className="linklike" style={{ fontSize: 12, color: 'inherit' }}>
            View in Monitor →
          </button>
        )}
      </div>
      {detail && <div style={{ marginTop: 3, fontWeight: 400 }}>{detail}</div>}
      {/* Stakeholder review (2026-08-28): a queued scan needs more than one detail sentence — the
          PRD's own worked example is a small grid of independent facts (work ahead, worker pool,
          submitted/updated time), not prose. `facts` is an ordered [{label, value}] array a
          caller's derivation builds ONLY from fields it actually has — never padded with a
          placeholder for what it doesn't know, matching pickupUnavailable's own honesty rule
          below rather than working around it. */}
      {facts && facts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', marginTop: 8 }}>
          {facts.map((f) => (
            <div key={f.label} style={{ minWidth: 120 }}>
              <div className="muted" style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.02em' }}>{f.label}</div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{f.value}</div>
            </div>
          ))}
        </div>
      )}
      {next && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>Next: {next}</div>}
      {/* An honest "not built yet", not a fake value. `comingSoon` names a specific signal this
          card deliberately does not show a number for — distinct styling (dashed border) so it
          never reads as a live fact that merely hasn't loaded. This grows into a real fact the
          day a caller's derivation starts setting it instead — nothing about this line implies
          that day is imminent. */}
      {comingSoon && (
        <div className="muted" style={{ marginTop: 8, padding: '6px 10px', fontSize: 11.5,
             fontStyle: 'italic', border: '1px dashed currentColor', borderRadius: 6, opacity: 0.75 }}>
          {comingSoon}
        </div>
      )}
      {recommendedAction === 'start_workers' && onStartWorkers && (
        <button onClick={onStartWorkers} style={{ marginTop: 8, padding: '4px 12px', borderRadius: 5,
                 border: `1px solid ${c.ink}`, background: c.ink, color: '#fff', fontSize: 12,
                 fontWeight: 600, cursor: 'pointer' }}>
          Start workers
        </button>
      )}
      {recommendedAction === 'rerun' && onRerun && (
        <button onClick={onRerun} style={{ marginTop: 8, padding: '4px 12px', borderRadius: 5,
                 border: `1px solid ${c.ink}`, background: c.ink, color: '#fff', fontSize: 12,
                 fontWeight: 600, cursor: 'pointer' }}>
          Re-run
        </button>
      )}
      {recommendedAction === 'check_worker_service' && (
        <div style={{ marginTop: 4, fontSize: 12 }}>
          Check that the worker service is reachable and that documents are not repeatedly failing.
        </div>
      )}
      {/* Driven by the derivation, not a hardcoded state-name list here: a THIRD caller
          (Remediate) will have its own state vocabulary, and this component should not need to
          know it. Each deriveXState() sets this explicitly on the states where it applies. */}
      {/* Two genuinely different reasons pickup is unavailable, worth saying apart rather than
          folding into one caveat (stakeholder UX review, 2026-08-30): no capacity exists to pick
          the job up at all, versus capacity exists but there isn't yet enough recent-completion
          history to trust a range. A caller sets noWorkerAvailable explicitly (derived from the
          same signal that drives its own "no worker"/"waiting for a worker" branch) — absent that,
          this defaults to the history-gap wording, matching every current caller's actual case. */}
      {pickupUnavailable && (
        <div className="muted" style={{ marginTop: 4, fontSize: 11.5, fontStyle: 'italic' }}>
          {noWorkerAvailable
            ? 'Pickup estimate unavailable. No compatible worker is currently ready.'
            : 'Pickup estimate is still being calculated. ACP needs more recent history before it can provide a reliable range.'}
        </div>
      )}
    </div>
  )
}
