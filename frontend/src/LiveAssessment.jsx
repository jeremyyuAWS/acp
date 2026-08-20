import { normalizeLive } from './liveAssessment.js'

// Live Assessment running screen — the command-center panel shown while a scan assesses. Presentational:
// it takes the merged /scans/{sid}/live snapshot and renders it via normalizeLive (the tested pure model).
// The KPIs + funnel come from the snapshot backend; the worker/lane strip from live_queue. A missing queue
// block renders as "coming online" (pending), never a fabricated zero — the same honesty the normalizer
// enforces. Layout is scoped inline so this ships without touching the shared stylesheet.

const CARD = {
  border: '1px solid var(--line, #e4e8ec)', borderRadius: 10, padding: '10px 14px',
  minWidth: 120, background: 'var(--panel, #fff)',
}
const KIND_COLOR = { ok: '#2F7D51', warn: '#9a5312', bad: '#b3261e', muted: '#5b6774' }

function Kpi({ label, value, pending, accent, provisional }) {
  // A provisional count grows during the run — the "so far" qualifier (in the label and the
  // accessible name) stops a mid-run number from reading as the final total (ADR 0016 / PRD §4.3).
  return (
    <div style={CARD} role="group" aria-label={provisional ? `${label}, so far` : label}>
      <div style={{ fontSize: 12, color: 'var(--muted,#5b6774)', letterSpacing: '.02em' }}>
        {label}{provisional && <span style={{ color: 'var(--faint,#8a95a1)', fontWeight: 600 }}> · so far</span>}
      </div>
      <div style={{ fontSize: 24, fontWeight: 800, color: accent || 'var(--ink,#111820)',
                    fontVariantNumeric: 'tabular-nums' }}>
        {pending ? <span aria-label="still computing" title="still computing">—</span> : value}
      </div>
    </div>
  )
}

export default function LiveAssessment({ snapshot, throughput }) {
  const m = normalizeLive(snapshot)
  if (!m.available) return null

  const q = m.queue
  return (
    <section className="live-assessment" role="region" aria-label="Live assessment"
      style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        {/* Announce PHASE transitions to screen readers (preparing → assessing → finalizing → complete).
            aria-live sits on the phase only, not the KPI counts — phases change rarely and meaningfully,
            so this informs without the every-2s spam a live region over the numbers would produce. */}
        <h3 style={{ margin: 0, fontSize: 16 }} aria-live="polite">{m.phaseLabel || 'Assessing'}</h3>
        {m.active && <span aria-hidden style={{ width: 8, height: 8, borderRadius: '50%',
          background: '#2F7D51', display: 'inline-block' }} />}
        {m.totals.discovered > 0 && (
          <span style={{ fontSize: 13, color: 'var(--muted,#5b6774)' }}>
            {m.totals.discovered} discovered · {m.totals.eligible} assessable
          </span>
        )}
        {/* Rolling throughput + calibrated ETA range (PRD §4.2/4.3). While calibrating we say
            "estimating…" rather than a swinging single number; the ETA is a RANGE reflecting real
            recent-speed variability, and it never appears on a stalled run. */}
        {m.active && throughput && (throughput.ratePerMin != null || throughput.calibrating) && (
          <span style={{ fontSize: 13, color: 'var(--faint,#8a95a1)' }}>
            {throughput.ratePerMin != null ? `${throughput.ratePerMin}/min` : ''}
            {throughput.etaText
              ? `${throughput.ratePerMin != null ? ' · ' : ''}${throughput.etaText}`
              : (throughput.calibrating ? `${throughput.ratePerMin != null ? ' · ' : ''}estimating…` : '')}
          </span>
        )}
      </header>

      {/* KPI cards — completed / processing / need-attention / unable-to-assess */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {m.kpiCards.map((c) => (
          <Kpi key={c.key} label={c.label} value={c.value} pending={c.pending} provisional={c.provisional}
            accent={c.key === 'need_attention' ? KIND_COLOR.warn
              : c.key === 'unable_to_assess' ? KIND_COLOR.bad : null} />
        ))}
      </div>

      {/* Worker / lane activity — from live_queue. Pending when the block isn't present yet. */}
      <div className="live-queue" role="group" aria-label="Worker activity"
        style={{ border: '1px solid var(--line,#e4e8ec)', borderRadius: 10, padding: '10px 14px' }}>
        {!q ? (
          <div style={{ fontSize: 13, color: 'var(--muted,#5b6774)' }}>Worker activity coming online…</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', gap: 18, fontSize: 13, flexWrap: 'wrap',
                          fontVariantNumeric: 'tabular-nums' }}>
              <span><b>{q.inFlight}</b> in&nbsp;flight</span>
              <span><b>{q.queued}</b> queued</span>
              <span>
                <b>{q.workers.busy}</b>{q.workers.max != null ? ` / ${q.workers.max}` : ''} workers busy
              </span>
              {q.stale && <span style={{ color: KIND_COLOR.warn }}>⏸ paused</span>}
            </div>
            <div style={{ fontSize: 13, color: q.stale ? KIND_COLOR.warn : 'var(--muted,#5b6774)' }}
              aria-live="polite">
              {q.laneLabel}
            </div>
          </div>
        )}
      </div>

      {m.warnings.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: 'var(--muted,#5b6774)' }}>
          {m.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
    </section>
  )
}
