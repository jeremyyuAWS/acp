// The Remediation Real-Time Operations Panel — regions A (run identity), B (phase rail) and
// C (outcome counters), rendered from ONE server-owned snapshot.
//
// It renders `snapshot` and nothing else. There is no local timer, no counter arithmetic, and no
// client-side completion: the panel that this replaces derived all three, which is how one paint
// came to show an "Applying fixes" headline over an idle queue, corrected copies already saved,
// and a provider label the run does not use. The state, the six counters and their reconciliation
// all arrive together with one revision (api/remediation_run.py), so the parts of this panel
// cannot disagree with each other even in principle.
//
// ACCESSIBILITY (PRD §12). Every state is carried by text, never by colour alone — the freshness
// badge, the phase rail and the counters each say their state in words, so a greyscale render and
// a screen reader get the same information. The live region is `polite` and announces the
// HEADLINE only: announcing each counter increment turns a 147-document run into 147
// interruptions. Nothing here moves focus.
import LiveCounter from './LiveCounter.jsx'
import { counterRows, secondaryRows, freshness, headline, partitionSums } from './remediationSnapshot.js'

const FRESHNESS_STYLE = {
  live: { bg: 'var(--green-bg,#f0f7e6)', ink: 'var(--success-fg)', line: 'var(--green-line,#a8cf7a)' },
  reconnecting: { bg: 'var(--warn-bg,#fdf6e3)', ink: '#7A5800', line: '#D4A017' },
  delayed: { bg: 'var(--warn-bg,#fdf6e3)', ink: '#7A5800', line: '#D4A017' },
  stalled: { bg: '#FBE9E7', ink: '#8A2A20', line: '#E7B4AC' },
  unknown: { bg: 'var(--surface,#f6f7f8)', ink: 'var(--ink)', line: 'var(--line,#e4e8ec)' },
}

const PHASE_STATUS_TEXT = {
  pending: 'Pending', active: 'In progress', completed: 'Completed',
  completed_with_exceptions: 'Completed with exceptions', failed: 'Failed', skipped: 'Skipped',
}

function FreshnessBadge({ state }) {
  const c = FRESHNESS_STYLE[state.level] || FRESHNESS_STYLE.unknown
  return (
    <span role="status" title={state.detail}
          style={{ fontSize: 11, padding: '1px 7px', borderRadius: 4, background: c.bg,
                   color: c.ink, border: `1px solid ${c.line}`, display: 'inline-flex',
                   alignItems: 'center', gap: 5 }}>
      {/* The dot is decoration. The word next to it is the signal — a badge whose only
          difference is its colour tells a greyscale or screen-reader user nothing. */}
      {state.level === 'live' && <span className="pulsedot" aria-hidden="true" />}
      {state.label}
      {state.ageS !== null && state.level !== 'live' && (
        <span style={{ opacity: 0.8 }}> · {state.ageS}s ago</span>
      )}
    </span>
  )
}

function PhaseRail({ phases }) {
  if (!phases || phases.length === 0) return null
  return (
    <ol aria-label="Remediation phases"
        style={{ listStyle: 'none', margin: '12px 0 0', padding: 0, display: 'grid', gap: 4 }}>
      {phases.map((phase) => (
        <li key={phase.key}
            style={{ display: 'grid', gridTemplateColumns: '18px minmax(0,1fr) auto',
                     gap: 8, alignItems: 'center', fontSize: 13 }}>
          <span aria-hidden="true" style={{ textAlign: 'center', fontWeight: 700,
                color: phase.status === 'failed' ? '#8A2A20'
                     : phase.status.startsWith('completed') ? 'var(--success-fg)' : 'var(--muted)' }}>
            {phase.status === 'active' ? <span className="pulsedot" />
              : phase.status === 'failed' ? '×'
              : phase.status.startsWith('completed') ? '✓' : '·'}
          </span>
          <span>
            {phase.label}
            {/* The status IN WORDS, next to the label — the icon above is aria-hidden, so this is
                the only thing a screen reader gets, and it must be enough on its own. */}
            <span className="muted" style={{ fontSize: 12 }}> — {PHASE_STATUS_TEXT[phase.status] || phase.status}</span>
          </span>
          {phase.detail && (
            <span className="muted" style={{ fontSize: 12, textAlign: 'right' }}>{phase.detail}</span>
          )}
        </li>
      ))}
    </ol>
  )
}

function Counters({ snapshot, suspect }) {
  const rows = counterRows(snapshot)
  if (!rows) return null
  const total = snapshot.total_documents
  const sums = partitionSums(snapshot)
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                    gap: 10, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 12.5, fontWeight: 650 }}>Documents in this run</h3>
        <span className="muted" style={{ fontSize: 12 }}>
          {typeof total === 'number' ? `${total.toLocaleString()} in scope` : 'Scope unknown'}
        </span>
      </div>
      <dl style={{ margin: '6px 0 0', display: 'grid', gap: '4px 18px',
                   gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))' }}>
        {rows.map((row) => (
          <div key={row.key}>
            <dt className="muted" style={{ fontSize: 10.5, textTransform: 'uppercase',
                                           letterSpacing: '0.02em' }}
                title={row.definition}>{row.label}</dt>
            {/* "—", never 0, for a counter the snapshot did not carry. A telemetry gap that
                renders as an empty queue is indistinguishable from a healthy one. */}
            <dd data-testid={`rem-count-${row.key}`}
                style={{ margin: 0, fontSize: 15, fontWeight: 650,
                         fontVariantNumeric: 'tabular-nums',
                         opacity: suspect ? 0.55 : 1 }}>
              {/* LiveCounter counts up and flashes "+N" — the same component Discovery's run
                  progress uses, not a second implementation of the idea. It never animates on a
                  DECREASE, which matters here: `waiting` and `processing` fall as work drains,
                  and a green "+N" on a shrinking queue would read as progress in the wrong
                  direction. An unknown counter keeps the em dash and never enters the animation
                  at all — "—" must not count up from zero. */}
              {row.value === null ? '—' : <LiveCounter value={row.value} />}
            </dd>
          </div>
        ))}
      </dl>
      {sums === false && (
        <p style={{ margin: '6px 0 0', fontSize: 12, color: '#8A2A20' }}>
          These counters do not add up to the documents in scope. ACP is reconciling them.
        </p>
      )}
    </div>
  )
}

function Secondary({ snapshot }) {
  const rows = secondaryRows(snapshot)
  if (rows.length === 0) return null
  return (
    <dl style={{ margin: '12px 0 0', display: 'flex', flexWrap: 'wrap', gap: '4px 20px' }}>
      {rows.map((row) => (
        <div key={row.key} style={{ minWidth: 120 }}>
          <dt className="muted" style={{ fontSize: 10.5, textTransform: 'uppercase',
                                         letterSpacing: '0.02em' }}>{row.label}</dt>
          <dd style={{ margin: 0, fontSize: 13.5, fontWeight: 600,
                       fontVariantNumeric: 'tabular-nums' }}><LiveCounter value={row.value} /></dd>
        </div>
      ))}
    </dl>
  )
}

// What is being worked RIGHT NOW — the panel's only per-document surface.
//
// A LIST, NEVER A "CURRENT FILE". Remediation fans out across worker slots, so naming one
// document implies a serial pipeline that does not exist; the snapshot models `active_attempts`
// as a list for exactly that reason. Three rows plus a count is the cap: enough to see the work
// moving, bounded so a 20-slot run does not push the counters off the screen.
//
// WHAT IT DELIBERATELY DOES NOT CLAIM. `elapsed_s` is measured from the CLAIM, not from the
// current phase, and `progress_at` is bumped by the lease heartbeat as well as by real phase
// changes (store.touch_job). So this says "in flight for" and "last signal", which is what those
// numbers are. Calling the second one "last progress" would let a worker that is merely alive
// read as one that is getting somewhere — the exact distinction a stalled run turns on.
function ago(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  return m < 60 ? `${m}m ${Math.round(seconds % 60)}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

function Workstream({ attempts, generatedAt }) {
  const rows = Array.isArray(attempts) ? attempts : []
  if (rows.length === 0) return null
  const shown = rows.slice(0, 3)
  const more = rows.length - shown.length
  const now = generatedAt ? Date.parse(generatedAt) : null
  return (
    <div style={{ marginTop: 14 }}>
      <h3 style={{ margin: '0 0 6px', fontSize: 12.5, fontWeight: 650 }}>
        In flight now
        <span className="muted" style={{ fontWeight: 400 }}> · {rows.length} document{rows.length === 1 ? '' : 's'}</span>
      </h3>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6 }}>
        {shown.map((a) => {
          const signal = now && a.progress_at ? (now - Date.parse(a.progress_at)) / 1000 : null
          return (
            <li key={`${a.file}-${a.started_at || ''}`}
                style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 10,
                         alignItems: 'baseline', fontSize: 12.5, padding: '6px 10px',
                         border: '1px solid var(--line)', borderRadius: 8 }}>
              <span style={{ minWidth: 0 }}>
                <span className="pulsedot" aria-hidden="true" />{' '}
                <span className="fname" style={{ overflowWrap: 'anywhere' }}>{a.file}</span>
                {/* The per-document phase string the worker itself wrote (handlers._phase), so
                    this is what THAT document is doing, not a run-level headline reused. */}
                {a.phase && <span className="muted"> — {a.phase}</span>}
                {/* Attempt number only while retrying: "attempt 1" on every row is noise. */}
                {typeof a.attempt === 'number' && a.attempt > 1 && (
                  <span className="muted"> · attempt {a.attempt}</span>
                )}
              </span>
              <span className="muted" style={{ fontSize: 11.5, whiteSpace: 'nowrap' }}>
                {ago(a.elapsed_s) && <>in flight {ago(a.elapsed_s)}</>}
                {ago(signal) && <> · last signal {ago(signal)} ago</>}
              </span>
            </li>
          )
        })}
      </ul>
      {more > 0 && (
        <p className="muted" style={{ margin: '6px 0 0', fontSize: 12 }}>
          and {more} more document{more === 1 ? '' : 's'} in flight
        </p>
      )}
    </div>
  )
}

const EVENT_ICON = { success: '✓', attention: '!', error: '×', neutral: '·' }

function ActivityFeed({ events }) {
  const rows = Array.isArray(events) ? events : []
  if (rows.length === 0) return null
  return (
    <details open className="rem-activity-feed">
      <summary>Live activity <span className="muted">· latest {rows.length}</span></summary>
      {/* Deliberately NOT aria-live. The panel's single polite region announces material run
          state; narrating every fix and delivery would interrupt once per document. */}
      <ol aria-label="Recent remediation activity">
        {rows.map((row) => (
          <li key={row.key} className={`rem-activity-feed__row rem-activity-feed__row--${row.tone}`}>
            <span className="rem-activity-feed__icon" aria-hidden="true">
              {EVENT_ICON[row.tone] || EVENT_ICON.neutral}
            </span>
            <span>{row.line}</span>
            {row.occurredAt && (
              <time dateTime={row.occurredAt}>
                {new Date(row.occurredAt).toLocaleTimeString([], {
                  hour: '2-digit', minute: '2-digit', second: '2-digit',
                })}
              </time>
            )}
          </li>
        ))}
      </ol>
    </details>
  )
}

/**
 * @param snapshot    GET /scans/{id}/remediation/snapshot, or null before the first one arrives.
 * @param connected   true while the SSE stream is open. The transport's own answer — see
 *                    remediationSnapshot.freshness for why this must not be inferred from data age.
 * @param receivedAt  epoch ms when `snapshot` arrived in the browser.
 * @param onViewMonitor  optional; omit and no Monitor link renders.
 */
export default function RemediationOpsPanel({ snapshot = null, connected = false,
                                              receivedAt = null, onViewMonitor = null,
                                              events = [] }) {
  // No snapshot and no run is not an empty panel to fill with zeroes — it is nothing to show.
  if (!snapshot || snapshot.state === 'draft') return null

  const fresh = freshness({ snapshot, connected, receivedAt })
  const line = headline(snapshot)
  const integrity = snapshot.integrity || {}
  const suspect = integrity.ok === false
  const source = snapshot.source || {}

  return (
    <section className="panel" aria-label="Remediation run status" style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                    gap: 14, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 240, flex: '1 1 auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 14 }}>{line}</strong>
            <FreshnessBadge state={fresh} />
          </div>
          {/* Region A's source line. It comes from the RUN RECORD, never from the signed-in
              account or a default connector, and it names one provider — a SharePoint run is
              never labelled OneDrive (PRD §17.1). */}
          {source.breadcrumb && (
            <p className="muted" style={{ margin: '4px 0 0', fontSize: 12 }}>
              Source: {source.breadcrumb}
            </p>
          )}
          <p className="muted" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
            {fresh.detail}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: '0 0 auto' }}>
          {snapshot.run_id && (
            <span className="muted" style={{ fontSize: 11.5, fontFamily: 'monospace' }}
                  title="Run ID">{snapshot.run_id}</span>
          )}
          {onViewMonitor && (
            <button type="button" className="linklike" style={{ fontSize: 12 }}
                    onClick={onViewMonitor}>View in Monitor →</button>
          )}
        </div>
      </div>

      {/* PRD §9's reconciliation treatment: name the affected metric, keep the last confirmed
          values visible, and do not silently adopt one subsystem's number as the answer. */}
      {suspect && (
        <div role="status" style={{ marginTop: 10, padding: '8px 12px', borderRadius: 8,
             background: '#FBE9E7', border: '1px solid #E7B4AC', color: '#8A2A20', fontSize: 12.5 }}>
          <b>Status temporarily inconsistent.</b>{' '}
          {(integrity.affected || []).length > 0
            ? `ACP cannot currently reconcile: ${integrity.affected.join(', ')}. `
            : ''}
          The values below are the last ACP confirmed.
        </div>
      )}

      <PhaseRail phases={snapshot.phases} />
      <Workstream attempts={snapshot.active_attempts} generatedAt={snapshot.generated_at} />
      <ActivityFeed events={events} />
      <Counters snapshot={snapshot} suspect={suspect} />
      <Secondary snapshot={snapshot} />

      {/* One polite live region, carrying the HEADLINE only. Counter increments are deliberately
          not announced (PRD §12) — a 147-document run would otherwise interrupt a screen-reader
          user once per document. */}
      <p aria-live="polite" className="sr-only" data-testid="rem-ops-announce">{line}</p>
    </section>
  )
}
