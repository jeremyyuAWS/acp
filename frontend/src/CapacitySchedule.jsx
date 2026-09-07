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
// AC 14's four causes, plus the two honest non-answers. `below_floor` reads as a warning
// because it is one: nothing asked for fewer replicas than the schedule's floor.
const ATTRIBUTION = {
  scheduled: { label: 'Scheduled floor', tone: 'var(--success-fg)' },
  queue: { label: 'Queue-driven', tone: 'var(--ink)' },
  manual_override: { label: 'Manual override', tone: 'var(--warn-fg, #8a5a00)' },
  deployment: { label: 'Deployment in progress', tone: 'var(--ink)' },
  below_floor: { label: 'Below the scheduled floor', tone: 'var(--warn-fg, #8a5a00)' },
  unknown: { label: 'Not known', tone: 'var(--muted)' },
}

const SCALER = {
  healthy: { label: 'Healthy', tone: 'var(--success-fg)' },
  pinned: { label: 'Inert — tier pinned', tone: 'var(--warn-fg, #8a5a00)' },
  missing: { label: 'No queue rule', tone: 'var(--warn-fg, #8a5a00)' },
  unreadable: { label: 'Unreadable', tone: 'var(--muted)' },
  not_configured: { label: 'Azure not configured', tone: 'var(--muted)' },
}

const RECONCILIATION = {
  applying: { label: 'Updating Azure capacity…', pending: true },
  leader_busy: { label: 'Another app instance is completing this update…', pending: true },
  backoff: { label: 'The last update failed; an automatic retry is scheduled.', problem: true },
  partial: { label: 'Some services did not update. ACP will retry automatically.', problem: true },
  failed: { label: 'Azure did not confirm the capacity update. ACP will retry automatically.', problem: true },
  stale: { label: 'The schedule changed during the update. ACP is reconciling the latest version.', problem: true },
  applied: { label: 'Azure capacity matches the active scheduling policy.' },
  ineligible: { label: 'Save and apply the current schedule before reconciling capacity.', problem: true },
  disabled: { label: 'Azure capacity application is unavailable.', problem: true },
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
  const [fastRefreshUntil, setFastRefreshUntil] = useState(0)
  const [workspace, setWorkspace] = useState(null)
  const [confirmation, setConfirmation] = useState(null)
  // `me?.is_admin` is the exact value the backend's _require_admin checks, so the SPA and the API
  // cannot disagree about who sees the editor. It is not the gate — every write endpoint runs
  // that check itself — but a view-only user seeing controls that 403 is its own kind of wrong
  // (WorkerReplicaControl.jsx records what that cost when it happened for real).
  const isAdmin = !!me?.is_admin

  useEffect(() => {
    let on = true
    setSnap(null)
    setFailed(false)
    getCapacitySchedule()
      .then((d) => { if (on) { setSnap(d); setFailed(false) } })
      .catch(() => { if (on) setFailed(true) })
    return () => { on = false }
  }, [reloads])

  // Keep status fresh while Settings is open. After a mutation, briefly follow the reconciler at
  // its own cadence so the administrator sees confirmation without closing and reopening.
  useEffect(() => {
    const fast = Date.now() < fastRefreshUntil
    const delay = fast ? 2000 : 30000
    const timer = window.setTimeout(() => setReloads((n) => n + 1), delay)
    return () => window.clearTimeout(timer)
  }, [reloads, fastRefreshUntil])

  if (failed) {
    return <div className="panel" style={{ padding: 12, fontSize: 13 }}>
      <b>The capacity schedule could not be read.</b>
      <div className="muted" style={{ marginTop: 4 }}>
        The schedule is a durable intention, so this is a reporting failure rather than a change
        in capacity — nothing has been altered. Live replica counts remain in
        Monitor → Workers &amp; Queue.
      </div>
      <button type="button" className="secondary" style={{ marginTop: 10 }}
        onClick={() => setReloads((n) => n + 1)}>
        Try again
      </button>
    </div>
  }
  if (!snap) return <div className="muted" style={{ padding: 12, fontSize: 13 }}>Loading the capacity schedule…</div>

  const validation = snap.validation
  const blocked = !!validation?.blocked
  const capacity = validation?.capacity
  const hasDrift = !!snap.drift_evaluated && !!snap.drift?.length
  const overrideAvailable = !!snap.applied && !!snap.application_configured
  const reconciliation = snap.reconciliation || {}
  const reconciliationView = RECONCILIATION[reconciliation.state]
  const applicationState = hasDrift
    ? 'Drift detected'
    : snap.applied ? 'Applied' : 'Saved changes not applied'
  const dayNames = (snap.days || []).map((day) => ({
    mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday',
    fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
  })[day] || day)
  const weekdaySummary = dayNames.length === 5 && (snap.days || []).join(',') === 'mon,tue,wed,thu,fri'
    ? 'Monday–Friday' : dayNames.join(', ')
  const formatTime = (value) => {
    const [hour, minute] = String(value || '').split(':').map(Number)
    if (!Number.isFinite(hour)) return value
    return new Date(2000, 0, 1, hour, minute || 0).toLocaleTimeString([], {
      hour: 'numeric', minute: '2-digit',
    })
  }
  const localTime = (() => {
    try {
      return new Intl.DateTimeFormat([], { timeZone: snap.timezone, hour: 'numeric', minute: '2-digit' }).format(new Date())
    } catch { return null }
  })()
  const viewerTimezone = (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' }
  })()
  const viewerTimestamp = (value) => value
    ? `${new Date(value).toLocaleString()} (${viewerTimezone})`
    : null
  const appliedPolicyMatches = reconciliation.desired_key
    && reconciliation.applied_key === reconciliation.desired_key
  const desiredAuthority = reconciliation.authority === 'manual_override' || snap.override
    ? 'Temporary override' : reconciliation.authority === 'holiday_exception'
    ? 'Holiday exception' : 'Saved weekly schedule'

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* §5.1's status summary. The first line says which schedule this IS, because every other
          number on the page is meaningless if it is read as the live one. */}
      <section className="panel" style={{ padding: 16 }} aria-labelledby="capacity-schedule-status">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>ACTIVE NOW</div>
            <h2 id="capacity-schedule-status" style={{ fontSize: 18, margin: 0 }}>
              {snap.override ? 'Temporary override' : !snap.enabled ? 'Scheduling disabled'
                : MODE_LABEL[snap.effective_mode] || snap.effective_mode}
            </h2>
            {!snap.applied && <div style={{ fontSize: 12, marginTop: 3 }}>Proposed schedule — not in force</div>}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 7 }}>
              <span className="chip" style={{ fontSize: 11 }}>{applicationState}</span>
              <span className="chip" style={{ fontSize: 11 }}>{snap.timezone}</span>
              {localTime && <span className="muted" style={{ fontSize: 12 }}>{localTime} local time</span>}
              {!isAdmin && <span className="chip" style={{ fontSize: 11 }}>View only</span>}
            </div>
          </div>
          {isAdmin && (
            <div aria-label="Schedule actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button type="button" onClick={() => setWorkspace('schedule')}>Edit schedule</button>
              <button type="button" className="secondary" disabled={!overrideAvailable}
                title={!overrideAvailable ? 'Apply the schedule and enable Azure capacity application first' : undefined}
                onClick={() => setWorkspace('override')}>
                Temporary override
              </button>
            </div>
          )}
        </div>
        {isAdmin && !overrideAvailable && (
          <div role="note" className="muted" style={{ fontSize: 12, marginTop: 5 }}>
            Temporary overrides are unavailable until this schedule is applied and Azure capacity application is enabled.
          </div>
        )}
        {reconciliationView && (
          <div role="status" aria-live="polite" style={{ fontSize: 12, marginTop: 5 }}>
            <b>{reconciliationView.label}</b>
            {reconciliation.completed_at ? <> Last checked {viewerTimestamp(reconciliation.completed_at)}.</> : null}
            {reconciliation.failures ? <> {reconciliation.failures} failed attempt{reconciliation.failures === 1 ? '' : 's'}.</> : null}
            {(reconciliationView.problem || reconciliationView.pending) && (
              <button type="button" className="linklike" onClick={() => setReloads((n) => n + 1)}>
                Refresh status
              </button>
            )}
          </div>
        )}
        {confirmation && (
          <div role="status" aria-live="polite" data-testid="schedule-confirmation"
            style={{ marginTop: 8, padding: 9, borderLeft: '4px solid var(--success-fg)', fontSize: 12 }}>
            <b>{confirmation}</b> This confirmation remains here while Scheduling is open.
            <button type="button" className="linklike" onClick={() => setConfirmation(null)}>Dismiss</button>
          </div>
        )}
        <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>
          {!isAdmin ? 'You can review this policy. A platform administrator must make changes. '
            : null}
          {snap.override
            ? <>Set by <b>{snap.override.actor}</b> for “{snap.override.reason}”; expires{' '}
                <b>{viewerTimestamp(snap.override.expires_at)}</b>, then schedule version{' '}
                {snap.override.resumes_schedule_version} resumes.</>
            : snap.applied
            ? <>Next transition {snap.next_transition_at
                ? <>to {MODE_LABEL[snap.next_transition_to] || snap.next_transition_to} at{' '}
                    <b>{viewerTimestamp(snap.next_transition_at)}</b></>
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
      </section>

      {!snap.enabled ? (
        <div className="panel" style={{ padding: 12, fontSize: 12 }}>
          <b>No weekly transitions are scheduled.</b>{' '}Worker Configuration and queue demand
          currently determine warm capacity.
        </div>
      ) : (
        <div className="panel" style={{ padding: 12, fontSize: 13 }}>
          <b>{weekdaySummary}, {formatTime(snap.start)}–{formatTime(snap.end)} ({snap.timezone}).</b>{' '}
          <span className="muted">Off-hours capacity applies at all other times.</span>
        </div>
      )}

      {snap.override && (
        <section className="panel" aria-labelledby="temporary-floor-heading"
          style={{ padding: 12, borderLeft: '4px solid var(--warn-fg, #8a5a00)' }}>
          <div id="temporary-floor-heading" className="muted" style={{ fontSize: 11 }}>TEMPORARY OVERRIDE FLOORS · ACTIVE</div>
          <p style={{ margin: '5px 0 9px', fontSize: 12 }}>
            These floors temporarily replace the weekly schedule below; they do not edit its draft values.
          </p>
          <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 8, margin: 0 }}>
            {SERVICES.filter(([key]) => snap.effective_floors?.[key] !== undefined).map(([key, label]) => (
              <div key={key}><dt className="muted" style={{ fontSize: 11 }}>{label}</dt><dd style={{ margin: 0, fontWeight: 600 }}>{snap.effective_floors[key]} warm</dd></div>
            ))}
          </dl>
        </section>
      )}

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
      {isAdmin && workspace && (
        <CapacityScheduleEditor snap={snap} initialView={workspace}
          onClose={() => setWorkspace(null)}
          onSaved={(message = 'Scheduling change saved.') => { setConfirmation(message); setWorkspace(null); setFastRefreshUntil(Date.now() + 60000); setReloads((n) => n + 1) }} />
      )}

      {/* §5.3's table, with the observed column beside it so the two are read together. */}
      <section aria-labelledby="service-capacity-heading">
        <div id="service-capacity-heading" className="muted" style={{ fontSize: 11, margin: '0 0 6px 2px' }}>
          SERVICE CAPACITY
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 210px), 1fr))', gap: 8 }}>
          {SERVICES.filter(([key]) => snap.maximums?.[key] !== undefined).map(([key, label]) => {
              const app = { web: 'acp-app', discovery: 'acp-discovery', assess: 'acp-assess',
                            remediate: 'acp-remediate', gpu: 'acp-ollama' }[key]
              const seen = snap.observed?.[app]
              return (
                <article className="panel" key={key} data-service={key} style={{ padding: 12 }}>
                  <b style={{ fontSize: 13 }}>{label}</b>
                  <dl style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '5px 10px', margin: '9px 0 0', fontSize: 12 }}>
                    <dt className="muted">Warm · business hours</dt><dd style={{ margin: 0 }}>{snap.business_hours[key]}</dd>
                    <dt className="muted">Warm · off hours</dt><dd style={{ margin: 0 }}>{snap.off_hours[key]}</dd>
                    <dt className="muted">Maximum when busy</dt><dd style={{ margin: 0 }}>{snap.maximums[key]}</dd>
                    <dt className="muted">Azure configured range</dt>
                    <dd style={{ margin: 0 }}>{seen && seen.min_replicas != null ? `${seen.min_replicas}–${seen.max_replicas}` : '—'}</dd>
                  </dl>
                  {snap.off_hours[key] === 0 && <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
                    Scales to zero off hours; the first job may wait for startup.
                  </div>}
                </article>
              )
            })}
        </div>
      </section>

      <section className="panel" aria-labelledby="capacity-verification-heading" style={{ padding: 12 }}>
        <div id="capacity-verification-heading" className="muted" style={{ fontSize: 11 }}>POLICY VERIFICATION · READ ONLY</div>
        <p className="muted" style={{ fontSize: 12, margin: '5px 0 10px' }}>
          Desired is ACP’s current authority. Applied is the last policy certified by the reconciler. Azure is the range read from each app.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <caption className="sr-only">Desired, applied, and Azure capacity verification</caption>
            <thead><tr><th scope="col" style={{ textAlign: 'left' }}>Service</th><th scope="col">Desired floor</th><th scope="col">Applied floor</th><th scope="col">Azure range</th></tr></thead>
            <tbody>{SERVICES.filter(([key]) => snap.effective_floors?.[key] !== undefined).map(([key, label]) => {
              const app = { web: 'acp-app', discovery: 'acp-discovery', assess: 'acp-assess', remediate: 'acp-remediate', gpu: 'acp-ollama' }[key]
              const seen = snap.observed?.[app]
              return <tr key={key} data-verification-service={key}>
                <th scope="row" style={{ textAlign: 'left' }}>{label}</th>
                <td style={{ textAlign: 'center' }}>{snap.effective_floors[key]}</td>
                <td style={{ textAlign: 'center' }}>{appliedPolicyMatches ? snap.effective_floors[key] : 'Not verified'}</td>
                <td style={{ textAlign: 'center' }}>{seen?.min_replicas != null && seen?.max_replicas != null ? `${seen.min_replicas}–${seen.max_replicas}` : 'Not reported'}</td>
              </tr>
            })}</tbody>
          </table>
        </div>
        <div role="status" style={{ fontSize: 12, marginTop: 9 }}>
          <b>Desired:</b> {desiredAuthority}. <b>Applied:</b>{' '}
          {appliedPolicyMatches ? 'Matches desired policy.' : reconciliation.applied_key ? 'Does not yet match desired policy.' : 'Not yet verified.'}
          {reconciliation.attempted_at ? <> Last attempt {viewerTimestamp(reconciliation.attempted_at)}.</> : null}
        </div>
      </section>

      <details className="panel" style={{ padding: 12 }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>
          Diagnostics
        </summary>
        <div className="muted" style={{ fontSize: 11, marginTop: 4, marginBottom: 10 }}>
          Azure attribution, queue scaler health, and configuration drift.
        </div>

      {/* AC 14: whether capacity is where it is because of the schedule, the queue, an override
          or a deployment. `below_floor` is deliberately its own word — a tier running short of
          its floor looks identical to one sitting exactly on it in a bare replica count, and
          only one of them is a problem. */}
      {!!Object.keys(snap.attribution || {}).length && (
        <div style={{ padding: '8px 0' }}>
          <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>WHY CAPACITY IS WHERE IT IS</div>
          <div style={{ display: 'grid', gap: 5 }}>
            {Object.entries(snap.attribution).map(([service, why]) => (
              <div key={service} style={{ fontSize: 12 }}>
                <b>{service}</b>{' · '}
                <span style={{ color: ATTRIBUTION[why.reason]?.tone || 'var(--muted)' }}>
                  {ATTRIBUTION[why.reason]?.label || why.reason}
                </span>
                {why.detail && <div className="muted" style={{ fontSize: 11 }}>{why.detail}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {!!snap.holidays?.length && (
        <div className="panel" style={{ padding: 12, fontSize: 12 }}>
          <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>HOLIDAY EXCEPTIONS</div>
          <div>{snap.holidays.join(' · ')}</div>
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
            ACP treats these as off-hours days. A published Azure policy does not observe them —
            a cron scale rule cannot express an exception to its own window — so warm capacity
            stays at the business-hours floor on these dates unless an override is used.
          </div>
        </div>
      )}

      {/* Scaler health. `pinned` is the state AC 10 did not have a word for. */}
      <div style={{ padding: '8px 0', borderTop: '1px solid var(--line)' }}>
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
      <div style={{ padding: '8px 0', borderTop: '1px solid var(--line)', fontSize: 12 }}>
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
      </details>

      {/* AC 15 and §13's non-goal, stated where somebody would otherwise assume the opposite.
          A tab called "Scheduling" in a product that already has scheduled re-scans is exactly
          the place that confusion starts, and the two are different features with different
          controls in different screens. Saying so is cheaper than the support ticket. */}
      <div className="muted" style={{ fontSize: 11 }}>
        <b>Capacity scheduling</b> decides how much warm processing capacity ACP holds and when.
        It does not schedule scans: scheduled re-scans remain in Monitor and are unchanged by
        anything here. Saving a schedule records what ACP intends — schedules saved here do not
        change live Azure replicas yet; applying a published policy is a separate, deliberate
        step. Live replica counts, queue depth and scale events are in Monitor → Workers &amp;
        Queue, and immediate warm capacity is adjusted in Settings → Worker
        Configuration.{!isAdmin && ' You have view-only access, so the schedule is shown but cannot be changed.'}
      </div>
    </div>
  )
}
