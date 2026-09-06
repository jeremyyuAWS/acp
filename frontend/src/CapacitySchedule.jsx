import { useEffect, useState } from 'react'
import { getCapacitySchedule } from './api.js'
import CapacityScheduleEditor from './CapacityScheduleEditor.jsx'

/**
 * Settings → Scheduling, READ-ONLY (Phase 2 of docs/prd-capacity-scheduling.md).
 *
 * WHY THIS TAB EXISTS BEFORE ANYTHING CAN BE EDITED. The PRD's §5.3 capacity table does not fit
 * the production Postgres server at its own business-hours floors — 152 connections during a
 * revision overlap plus a 15-connection reserve, against a server that has 150. A phase that
 * shipped the editor first would let an administrator save that, and the failure would surface
 * as pool exhaustion during a deploy rather than as a refusal at the point of decision.
 *
 * So the first thing this panel renders is the schedule being refused by its own validation.
 *
 * WHAT IT MUST NOT IMPLY. Three states are easy to render wrongly and each has its own field:
 *   * `applied` — the schedule shown is PROPOSED. Nothing has put it into force, and a panel
 *     that looked the same either way would be the same quiet wrongness as a table of dashes
 *     reporting `configured: true`.
 *   * `drift_evaluated` — production differs from the proposal in every service and NONE of it
 *     is drift, because nothing has drifted from a schedule nobody applied. Showing those
 *     differences as drift would be true arithmetic and a false statement.
 *   * a scaler's `pinned` state — a queue rule on a tier whose floor equals its ceiling is
 *     neither healthy nor broken. It is inert, and AC 10 only had two words for it.
 *
 * NO CONTROLS, deliberately, and not only because the writes do not exist yet. Capacity controls
 * live in Settings → Worker Configuration (queuePanelCapacity.test.jsx holds that), and Live
 * Operations gets a read-only mode strip. Two writable capacity surfaces is the thing this
 * arrangement exists to avoid.
 */

const MODE_LABEL = { business_hours: 'Business hours', off_hours: 'Off hours' }
const SERVICES = [
  ['web', 'Web app'], ['discovery', 'Discovery'], ['assess', 'Assess'],
  ['remediate', 'Remediate'], ['gpu', 'GPU vision'],
]
// The four states GET /control/capacity-schedule can report for a queue scaler, and the words
// used for each. `pinned` reads as a warning rather than a failure on purpose: nothing is
// broken, the tier simply cannot act on the rule.
const SCALER = {
  healthy: { label: 'Healthy', tone: 'var(--success-fg)' },
  pinned: { label: 'Inert — tier pinned', tone: 'var(--warn-fg, #8a5a00)' },
  missing: { label: 'No queue rule', tone: 'var(--warn-fg, #8a5a00)' },
  unreadable: { label: 'Unreadable', tone: 'var(--muted)' },
  not_configured: { label: 'Azure not configured', tone: 'var(--muted)' },
}

function Findings({ findings }) {
  if (!findings?.length) return null
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
      {findings.map((f, i) => (
        <li key={`${f.code}-${i}`} style={{ marginBottom: 3 }}>
          <b style={{ color: f.blocking ? 'var(--danger-fg, #a3222b)' : 'var(--warn-fg, #8a5a00)' }}>
            {f.blocking ? 'Blocks saving' : 'Warning'}
          </b>{' — '}{f.detail}
        </li>
      ))}
    </ul>
  )
}

export default function CapacitySchedule({ me = null } = {}) {
  const [snap, setSnap] = useState(null)
  const [failed, setFailed] = useState(false)
  const [reloads, setReloads] = useState(0)
  // `me?.is_admin` is the exact value the backend's _require_admin checks, so the SPA and the API
  // cannot disagree about who sees the editor. It is not the gate — every write endpoint runs
  // that check itself — but a view-only user seeing controls that 403 is its own kind of wrong
  // (WorkerReplicaControl.jsx records what that cost when it happened for real).
  const isAdmin = !!me?.is_admin

  useEffect(() => {
    let on = true
    getCapacitySchedule()
      .then((d) => { if (on) { setSnap(d); setFailed(false) } })
      .catch(() => { if (on) setFailed(true) })
    return () => { on = false }
  }, [reloads])

  if (failed) {
    return <div className="panel" style={{ padding: 12, fontSize: 13 }}>
      <b>The capacity schedule could not be read.</b>
      <div className="muted" style={{ marginTop: 4 }}>
        The schedule is a durable intention, so this is a reporting failure rather than a change
        in capacity — nothing has been altered. Live replica counts remain in
        Monitor → Workers &amp; Queue.
      </div>
    </div>
  }
  if (!snap) return <div className="muted" style={{ padding: 12, fontSize: 13 }}>Loading the capacity schedule…</div>

  const validation = snap.validation
  const blocked = !!validation?.blocked
  const capacity = validation?.capacity

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* §5.1's status summary. The first line says which schedule this IS, because every other
          number on the page is meaningless if it is read as the live one. */}
      <div className="panel" style={{ padding: 12 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 14 }}>
            {snap.applied ? MODE_LABEL[snap.effective_mode] || snap.effective_mode
              : 'Proposed schedule — not in force'}
          </b>
          <span className="chip" style={{ fontSize: 11 }}>{snap.timezone}</span>
          {!snap.enabled && <span className="chip" style={{ fontSize: 11 }}>Disabled</span>}
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>
          {snap.applied
            ? <>Next transition {snap.next_transition_at
                ? <>to {MODE_LABEL[snap.next_transition_to] || snap.next_transition_to} at{' '}
                    <b>{new Date(snap.next_transition_at).toLocaleString()}</b></>
                : 'not scheduled'}.</>
            : <>Nothing has applied this schedule. Warm capacity is whatever
                Settings → Worker Configuration and the queue scalers are currently set to; this
                tab shows what ACP would intend, and whether that intention is safe to apply.</>}
        </div>
        {snap.enabled && snap.start && (
          <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
            Business hours {snap.start}–{snap.end}, {snap.days.join(' ')} · times are local to{' '}
            {snap.timezone} and follow daylight saving without being rewritten.
          </div>
        )}
      </div>

      {/* Validation, second and prominent: this is the answer the phase exists to produce. */}
      {validation && (
        <div className="panel" style={{ padding: 12,
          borderLeft: `4px solid ${blocked ? 'var(--danger-fg, #a3222b)' : 'var(--success-fg)'}` }}
          role="status" aria-label="Schedule validation">
          <b style={{ fontSize: 13 }}>
            {blocked ? 'This schedule cannot be applied' : 'This schedule fits the fleet'}
          </b>
          {capacity && (
            <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>
              During a revision overlap the fleet wants <b>{capacity.deploy_connections}</b>{' '}
              database connections, plus <b>{capacity.reserve}</b> held in reserve, against a
              server with <b>{capacity.server_max_connections}</b>.{' '}
              {capacity.connection_headroom < 0
                ? <>That is <b>{Math.abs(capacity.connection_headroom)} over</b>.</>
                : <>That leaves <b>{capacity.connection_headroom}</b> spare.</>}
              {' '}Checked against the worst mode the schedule can enter, not the current one —
              a rollout can land in any of them, and the overlap is driven by the warm floors.
            </div>
          )}
          <Findings findings={validation.findings} />
        </div>
      )}

      {/* The editor, for administrators only. It re-reads through `onSaved` rather than patching
          state locally: warm capacity is real money and a real restart, and an optimistic floor
          that silently reverts is indistinguishable from one that saved. */}
      {isAdmin && <CapacityScheduleEditor snap={snap} onSaved={() => setReloads((n) => n + 1)} />}

      {/* §5.3's table, with the observed column beside it so the two are read together. */}
      <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="muted" style={{ fontSize: 11, padding: '9px 12px 5px' }}>SERVICE CAPACITY</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderTop: '1px solid var(--line)' }}>
              <th style={{ padding: '6px 12px', fontWeight: 600 }}>Service</th>
              <th style={{ padding: '6px 12px', fontWeight: 600, textAlign: 'right' }}>Business hours</th>
              <th style={{ padding: '6px 12px', fontWeight: 600, textAlign: 'right' }}>Off hours</th>
              <th style={{ padding: '6px 12px', fontWeight: 600, textAlign: 'right' }}>Maximum</th>
              <th style={{ padding: '6px 12px', fontWeight: 600, textAlign: 'right' }}>Azure runs now</th>
            </tr>
          </thead>
          <tbody>
            {SERVICES.filter(([key]) => snap.maximums?.[key] !== undefined).map(([key, label]) => {
              const app = { web: 'acp-app', discovery: 'acp-discovery', assess: 'acp-assess',
                            remediate: 'acp-remediate', gpu: 'acp-ollama' }[key]
              const seen = snap.observed?.[app]
              return (
                <tr key={key} style={{ borderTop: '1px solid var(--line)' }}>
                  <td style={{ padding: '6px 12px' }}>{label}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right' }}>{snap.business_hours[key]}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right' }}>{snap.off_hours[key]}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right' }}>{snap.maximums[key]}</td>
                  {/* A reading Azure did not return stays a dash. Never a fabricated 0 — the
                      difference between "no replicas" and "we could not ask" is the whole
                      point of the column. */}
                  <td style={{ padding: '6px 12px', textAlign: 'right' }} className="muted">
                    {seen && seen.min_replicas != null
                      ? `${seen.min_replicas}–${seen.max_replicas}`
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Scaler health. `pinned` is the state AC 10 did not have a word for. */}
      <div className="panel" style={{ padding: 12 }}>
        <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>QUEUE SCALERS</div>
        <div style={{ display: 'grid', gap: 5 }}>
          {Object.entries(snap.scalers || {}).map(([service, health]) => {
            const shown = SCALER[health.state] || { label: health.state, tone: 'var(--muted)' }
            return (
              <div key={service} style={{ fontSize: 12 }}>
                <b>{({ discovery: 'Discovery', assess: 'Assess', remediate: 'Remediate' })[service] || service}</b>
                {' · '}<span style={{ color: shown.tone }}>{shown.label}</span>
                {health.detail && <div className="muted" style={{ fontSize: 11 }}>{health.detail}</div>}
              </div>
            )
          })}
          {!Object.keys(snap.scalers || {}).length && (
            <span className="muted" style={{ fontSize: 12 }}>No queue scaler information.</span>
          )}
        </div>
      </div>

      {/* Drift, and the reason it is not being evaluated. Saying "not evaluated" is the point:
          an empty drift list next to an obviously different Azure would otherwise read as
          agreement. */}
      <div className="panel" style={{ padding: 12, fontSize: 12 }}>
        <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>CONFIGURATION DRIFT</div>
        {!snap.drift_evaluated && (
          <span className="muted">
            Not evaluated: drift measures an <i>applied</i> schedule against Azure, and this
            schedule has not been applied. Comparing a proposal to production would report every
            service as drifted while nothing had drifted at all.
          </span>
        )}
        {snap.drift_evaluated && !snap.drift.length && <span>Azure matches the schedule.</span>}
        {snap.drift_evaluated && !!snap.drift.length && (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {snap.drift.map((d, i) => (
              <li key={i}><b>{d.app}</b> {d.field}: schedule says {d.desired}, Azure reports {d.observed}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="muted" style={{ fontSize: 11 }}>
        Live replica counts, queue depth and scale events are in Monitor → Workers &amp; Queue.
        Immediate warm capacity is adjusted in Settings → Worker Configuration; this tab sets when
        ACP should hold more of it.{!isAdmin && ' You have view-only access, so the schedule is shown but cannot be changed.'}
      </div>
    </div>
  )
}
