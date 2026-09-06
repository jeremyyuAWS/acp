import { progressBar, etaGate, runHeadline, shouldShowCard } from './remediationRunCard.js'
import { freshness } from './remediationSnapshot.js'
import LiveCounter from './LiveCounter.jsx'
import ActivityPulse from './ActivityPulse.jsx'

// The persistent remediation run card — visible on EVERY tab while a run is live.
//
// It answers one question a user has while they are somewhere else in the app: is my remediation
// still working, and does it need me? Everything richer (the inbox, the guided fix, the audit
// trail) belongs on the Remediate tab; this is the part that must not disappear when they leave.
//
// ACCESSIBILITY. Every band in the bar is also a legend entry with its label and count, so the
// bar is readable in greyscale, by a screen reader, and by a protanope — the fills are ordered so
// no two confusable hues touch (see remediationRunCard.SEGMENTS). The live region announces the
// STATE only, never the counters: a 147-document run would otherwise interrupt once per document.

const FRESHNESS_WORDS = {
  live: 'Live', reconnecting: 'Reconnecting', delayed: 'Stale',
  unknown: 'Unavailable', stalled: 'Stalled',
}

function ProgressBar({ bar }) {
  if (!bar) return null
  return (
    <div>
      {/* The track. `waiting` is its unfilled tail rather than a fifth fill — that is what those
          documents are, and it is what let the palette pass its adjacent-pair checks. */}
      <div role="img"
           aria-label={`${bar.total} documents: ` +
             bar.segments.map((s) => `${s.value} ${s.label.toLowerCase()}`).join(', ') +
             (bar.waiting ? `, ${bar.waiting} waiting` : '')}
           style={{ display: 'flex', gap: 2, height: 10, borderRadius: 5, overflow: 'hidden',
                    background: 'var(--line)' }}>
        {bar.segments.map((s) => (
          <div key={s.key} style={{ width: `${s.pct}%`, background: s.fill }} />
        ))}
      </div>
      {/* Legend — always present, because there is more than one band and identity must never
          rest on colour alone. The count beside each swatch is also the direct label, so no
          separate number sits on the bar itself. */}
      <ul style={{ listStyle: 'none', display: 'flex', flexWrap: 'wrap', gap: '4px 14px',
                   margin: '7px 0 0', padding: 0, fontSize: 12 }}>
        {bar.segments.map((s) => (
          <li key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span aria-hidden="true" style={{ width: 9, height: 9, borderRadius: 2,
                                              background: s.fill, flex: '0 0 auto' }} />
            <span style={{ color: 'var(--ink)' }}>
              <b style={{ fontVariantNumeric: 'tabular-nums' }}>{s.value.toLocaleString()}</b> {s.label.toLowerCase()}
            </span>
          </li>
        ))}
        {bar.waiting > 0 && (
          <li style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span aria-hidden="true" style={{ width: 9, height: 9, borderRadius: 2,
                                              background: 'var(--line)', border: '1px solid var(--muted)',
                                              flex: '0 0 auto' }} />
            <span className="muted">
              <b style={{ fontVariantNumeric: 'tabular-nums' }}>{bar.waiting.toLocaleString()}</b> waiting
            </span>
          </li>
        )}
      </ul>
    </div>
  )
}

/**
 * @param snapshot    GET /scans/{id}/remediation/snapshot, or null.
 * @param receivedAt  epoch ms when it arrived.
 * @param connected   true only while an SSE stream is open. This card polls, so it passes false
 *                    and reports "Reconnecting" rather than claiming Live — see useRemediationRun.
 * @param throughput  useThroughput's output, or null. Gated again on completed documents.
 * @param onOpen      optional; omit and no "Open details" control renders.
 */
export default function RemediationRunCard({ snapshot = null, receivedAt = null,
                                             connected = false, throughput = null,
                                             events = [], onOpen = null }) {
  if (!shouldShowCard(snapshot)) return null

  const head = runHeadline(snapshot)
  const bar = progressBar(snapshot)
  const fresh = freshness({ snapshot, connected, receivedAt })
  const eta = etaGate(snapshot, throughput)
  const fixes = snapshot.fixes || {}
  const delivery = snapshot.delivery || {}
  const source = snapshot.source || {}
  const documents = snapshot.documents || {}
  const processed = typeof snapshot.total_documents === 'number'
    && ['processing', 'waiting'].every((key) => typeof documents[key] === 'number')
    ? snapshot.total_documents - documents.processing - documents.waiting
    : null

  return (
    <section className="panel" aria-label="Remediation run" data-testid="rem-run-card"
             style={{ margin: '10px 0 0', padding: '12px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                    gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 220 }}>
          <strong style={{ fontSize: 14 }}>{head.label}</strong>
          {head.doing && <span className="muted" style={{ fontSize: 12.5 }}> · {head.doing}</span>}
          {source.breadcrumb && (
            <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{source.breadcrumb}</div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
          {/* The last sixty seconds of durable events, beside the freshness words rather than
              under the bar. Both answer "is this still moving?" — freshness from the transport,
              the pulse from what the run recorded — and reading them together is what tells a
              connected-but-idle run apart from a busy one. It renders nothing when no events
              landed, so a quiet run does not carry an empty widget across every tab. */}
          <ActivityPulse events={events} generatedAt={snapshot.generated_at} compact />
          {/* Freshness in WORDS, next to the dot — the dot alone would be colour-only. */}
          <span className="muted" title={fresh.detail}>
            {FRESHNESS_WORDS[fresh.level] || fresh.level}
            {fresh.ageS !== null && <> · updated {fresh.ageS}s ago</>}
          </span>
          {onOpen && (
            <button type="button" className="linklike" style={{ fontSize: 12 }} onClick={onOpen}>
              Open details →
            </button>
          )}
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        {processed != null && (
          <p style={{ margin: '0 0 7px', fontSize: 12.5, fontWeight: 650 }}>
            <LiveCounter value={processed} /> of {snapshot.total_documents.toLocaleString()} documents processed
          </p>
        )}
        <ProgressBar bar={bar} />
      </div>

      {/* Secondary facts, each naming its unit. `Corrected copies` and `Documents verified` are
          deliberately separate numbers: a corrected copy that was stored but not delivered, or
          delivered but not verified, is exactly the case these must not merge. */}
      <dl style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 20px', margin: '10px 0 0' }}>
        {[
          ['Fixes applied', fixes.applied, true],
          ['Fixes verified', fixes.verified, true],
          ['Documents verified', fixes.documents_verified, true],
          ['Corrected copies delivered', delivery.delivered, true],
          ['Awaiting Release', delivery.awaiting_release, false],
          ['Pending delivery', delivery.pending, false],
        ].filter(([, v]) => typeof v === 'number').map(([label, value, positive]) => (
          <div key={label}>
            <dt className="muted" style={{ fontSize: 10.5, textTransform: 'uppercase',
                                           letterSpacing: '0.02em' }}>{label}</dt>
            <dd style={{ margin: 0, fontSize: 13.5, fontWeight: 650,
                         fontVariantNumeric: 'tabular-nums' }}>{positive
                ? <LiveCounter value={value} /> : value.toLocaleString()}</dd>
          </div>
        ))}
      </dl>

      <p className="muted" style={{ margin: '8px 0 0', fontSize: 12 }}>
        {eta.show
          ? <>Estimated {eta.text} · <span style={{ fontStyle: 'italic' }}>{eta.basis}</span></>
          : eta.note}
        {typeof throughput?.ratePerMin === 'number' && throughput.ratePerMin > 0 && !throughput.calibrating && (
          <> · {throughput.ratePerMin} documents/min · last 5 min</>
        )}
      </p>

      {/* One polite live region carrying the STATE, not the counters. */}
      <p aria-live="polite" className="sr-only" data-testid="rem-run-card-announce">
        {head.label}{head.doing ? ` — ${head.doing}` : ''}
      </p>
    </section>
  )
}
