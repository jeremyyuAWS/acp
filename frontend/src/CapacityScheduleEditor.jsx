import { useState } from 'react'
import { putCapacitySchedule, validateCapacitySchedule, createCapacityOverride,
         deleteCapacityOverride } from './api.js'

/**
 * The administrator half of Settings → Scheduling (Phase 3).
 *
 * RENDERED ONLY FOR AN ADMIN, and that is convenience rather than the gate: every endpoint here
 * runs `_require_admin`, and WorkerReplicaControl.jsx records what happens when the SPA is the
 * only check — a non-admin got an optimistic change that reverted with no message once the write
 * 403'd. The buttons are hidden for the same reason the count is not.
 *
 * THE THREE THINGS THE UI HAS TO GET RIGHT, because the API cannot do them for it:
 *
 *   * `version` travels with the edit. It comes from the snapshot this form was opened on, so a
 *     save built on a stale read is refused by the server rather than silently overwriting
 *     somebody else's floor. A 409 is rendered as what it is — someone else saved — with both
 *     numbers and a reload, not as a generic failure.
 *   * A reason is required before Save is reachable. §11 wants it in the audit row, and an audit
 *     row whose reason is empty is the one an operator finds a week later and cannot act on.
 *   * Validation is offered BEFORE saving and its verdict is shown, but Save does not depend on
 *     the client having run it — the server validates again and refuses. A client-side gate that
 *     could be bypassed would be the more dangerous half of a two-part check.
 *
 * NO OPTIMISTIC RENDERING. Warm capacity is real money and a real restart; the form waits for the
 * server and re-reads. An optimistic floor that reverts is indistinguishable from one that saved.
 */

const DAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'],
              ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']]
const SERVICES = [['web', 'Web app'], ['discovery', 'Discovery'], ['assess', 'Assess'],
                  ['remediate', 'Remediate'], ['gpu', 'GPU vision']]
const DURATIONS = [['30m', '30 minutes'], ['1h', '1 hour'], ['2h', '2 hours'],
                   ['4h', '4 hours'], ['until_next_transition', 'Until the next transition']]

const label = { display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 2 }
const num = { width: 58, padding: '3px 5px', fontSize: 12 }

function draftFrom(snap) {
  return {
    enabled: !!snap.enabled,
    timezone: snap.timezone || 'America/Los_Angeles',
    days: [...(snap.days || [])],
    start: snap.start || '06:00',
    end: snap.end || '20:00',
    business_hours: { ...(snap.business_hours || {}) },
    off_hours: { ...(snap.off_hours || {}) },
    maximums: { ...(snap.maximums || {}) },
    holidays: [...(snap.holidays || [])],
  }
}

export default function CapacityScheduleEditor({ snap, onSaved }) {
  const [draft, setDraft] = useState(() => draftFrom(snap))
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [overrideReason, setOverrideReason] = useState('')
  const [overrideMode, setOverrideMode] = useState('business_hours')
  const [overrideDuration, setOverrideDuration] = useState('1h')

  const setField = (field, value) => { setDraft((d) => ({ ...d, [field]: value })); setChecked(null) }
  const setCount = (group, service, value) => {
    const n = Math.max(0, Number.parseInt(value, 10) || 0)
    setDraft((d) => ({ ...d, [group]: { ...d[group], [service]: n } }))
    setChecked(null)
  }
  const toggleDay = (day) => setField('days',
    draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day])

  const check = () => {
    setBusy(true); setError(null)
    validateCapacitySchedule(draft)
      .then(setChecked)
      .catch(() => setError('The schedule could not be checked. Nothing was changed.'))
      .finally(() => setBusy(false))
  }

  const save = () => {
    setBusy(true); setError(null)
    // `version` is the one this form was opened on, never a re-read: re-reading it here would
    // defeat the whole mechanism by making every save look current.
    putCapacitySchedule({ ...draft, version: snap.version, reason })
      .then((saved) => {
        if (saved?.detail?.current_version !== undefined) {
          setError(`Someone else saved while you were editing (you had version `
            + `${saved.detail.your_version}, current is ${saved.detail.current_version}). `
            + 'Reload to see their change before saving yours.')
          return
        }
        if (saved?.detail?.findings) {
          setChecked(saved.detail)
          setError('This schedule cannot be applied — see the findings below.')
          return
        }
        setReason(''); setChecked(null); onSaved?.()
      })
      .catch(() => setError('The schedule could not be saved. Nothing was changed.'))
      .finally(() => setBusy(false))
  }

  const applyOverride = () => {
    setBusy(true); setError(null)
    createCapacityOverride({ mode: overrideMode, duration: overrideDuration,
                             reason: overrideReason,
                             floors: overrideMode === 'custom' ? draft.business_hours : null })
      .then((r) => {
        if (r?.detail) { setError(String(r.detail)); return }
        setOverrideReason(''); onSaved?.()
      })
      .catch(() => setError('The override could not be created. Nothing was changed.'))
      .finally(() => setBusy(false))
  }

  const cancelOverride = () => {
    setBusy(true); setError(null)
    deleteCapacityOverride()
      .then(() => onSaved?.())
      .catch(() => setError('The override could not be cancelled.'))
      .finally(() => setBusy(false))
  }

  const canSave = !busy && reason.trim().length > 0

  return (
    <div className="panel" style={{ padding: 12, display: 'grid', gap: 12 }}>
      <b style={{ fontSize: 13 }}>Edit the schedule</b>

      {error && <div role="alert" style={{ fontSize: 12, padding: '7px 9px',
        borderLeft: '4px solid var(--danger-fg, #a3222b)', background: 'var(--bg)' }}>{error}</div>}

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
          <input type="checkbox" checked={draft.enabled}
                 onChange={(e) => setField('enabled', e.target.checked)} />
          Schedule enabled
        </label>
        <span>
          <label style={label} htmlFor="cap-tz">Timezone (IANA)</label>
          <input id="cap-tz" value={draft.timezone} style={{ width: 190, padding: '3px 5px', fontSize: 12 }}
                 onChange={(e) => setField('timezone', e.target.value)} />
        </span>
        <span>
          <label style={label} htmlFor="cap-start">Business hours start</label>
          <input id="cap-start" type="time" value={draft.start} style={{ padding: '3px 5px', fontSize: 12 }}
                 onChange={(e) => setField('start', e.target.value)} />
        </span>
        <span>
          <label style={label} htmlFor="cap-end">Business hours end</label>
          <input id="cap-end" type="time" value={draft.end} style={{ padding: '3px 5px', fontSize: 12 }}
                 onChange={(e) => setField('end', e.target.value)} />
        </span>
      </div>

      <fieldset style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '6px 10px' }}>
        <legend style={{ fontSize: 11, color: 'var(--muted)' }}>Active days</legend>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {DAYS.map(([key, name]) => (
            <label key={key} style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center' }}>
              <input type="checkbox" checked={draft.days.includes(key)}
                     onChange={() => toggleDay(key)} /> {name}
            </label>
          ))}
        </div>
      </fieldset>

      <table style={{ borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: 'left' }}>
            <th style={{ padding: '3px 8px', fontWeight: 600 }}>Service</th>
            <th style={{ padding: '3px 8px', fontWeight: 600 }}>Business hours</th>
            <th style={{ padding: '3px 8px', fontWeight: 600 }}>Off hours</th>
            <th style={{ padding: '3px 8px', fontWeight: 600 }}>Maximum</th>
          </tr>
        </thead>
        <tbody>
          {SERVICES.filter(([k]) => draft.maximums[k] !== undefined).map(([key, name]) => (
            <tr key={key}>
              <td style={{ padding: '3px 8px' }}>{name}</td>
              {['business_hours', 'off_hours', 'maximums'].map((group) => (
                <td key={group} style={{ padding: '3px 8px' }}>
                  <input type="number" min="0" style={num} value={draft[group][key] ?? 0}
                         aria-label={`${name} ${group.replace(/_/g, ' ')}`}
                         onChange={(e) => setCount(group, key, e.target.value)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <span>
        <label style={label} htmlFor="cap-holidays">
          Holiday exceptions — YYYY-MM-DD, comma separated (optional)
        </label>
        <input id="cap-holidays" value={draft.holidays.join(', ')}
               style={{ width: '100%', padding: '4px 6px', fontSize: 12 }}
               onChange={(e) => setField('holidays',
                 e.target.value.split(',').map((d) => d.trim()).filter(Boolean))} />
        {/* The caveat belongs beside the field, not in a doc. ACP observes a holiday everywhere
            ACP decides; the published Azure policy cannot, because a KEDA cron rule has no way
            to express an exception to its own window. An administrator who types a date here and
            is not told that would reasonably expect the spend to drop on the day. */}
        <span className="muted" style={{ fontSize: 11 }}>
          ACP treats these as off-hours days. Azure does not: a cron scale rule cannot express an
          exception to its own window, so a published policy still holds the business-hours floor
          on them. Use a temporary override on the day, or republish without the schedule enabled.
        </span>
      </span>

      <span>
        <label style={label} htmlFor="cap-reason">Reason for this change (recorded in the audit log)</label>
        <input id="cap-reason" value={reason} onChange={(e) => setReason(e.target.value)}
               style={{ width: '100%', padding: '4px 6px', fontSize: 12 }} />
      </span>

      {checked && (
        <div role="status" style={{ fontSize: 12, padding: '7px 9px', background: 'var(--bg)',
          borderLeft: `4px solid ${checked.blocked ? 'var(--danger-fg, #a3222b)' : 'var(--success-fg)'}` }}>
          <b>{checked.blocked ? 'This schedule cannot be applied' : 'This schedule fits the fleet'}</b>
          {checked.capacity && (
            <div className="muted" style={{ marginTop: 3 }}>
              {checked.capacity.deploy_connections} connections during a revision overlap, plus{' '}
              {checked.capacity.reserve} reserved, against {checked.capacity.server_max_connections}.
            </div>
          )}
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {(checked.findings || []).map((f, i) => <li key={i}>{f.detail}</li>)}
          </ul>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className="ghost" onClick={check} disabled={busy}>Check this schedule</button>
        <button onClick={save} disabled={!canSave}>Save schedule</button>
        {/* Saving records the intention. Pushing it to Azure is a separate, deliberate step —
            see the module docstring on api/routes/control.py's PUT. */}
        <span className="muted" style={{ fontSize: 11 }}>
          {reason.trim() ? 'Saving records the schedule; applying it to Azure is a separate step.'
            : 'A reason is required before saving.'}
        </span>
      </div>

      <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: 0 }} />

      <b style={{ fontSize: 13 }}>Temporary override</b>
      {snap.override ? (
        <div style={{ fontSize: 12 }}>
          <div>
            <b>{snap.override.mode.replace(/_/g, ' ')}</b> capacity, set by {snap.override.actor},
            expiring {new Date(snap.override.expires_at).toLocaleString()}.
          </div>
          <div className="muted">Reason: {snap.override.reason}</div>
          <div className="muted">
            The schedule (version {snap.override.resumes_schedule_version}) resumes automatically
            when it expires — an override cannot become permanent.
          </div>
          <button className="ghost" onClick={cancelOverride} disabled={busy}
                  style={{ marginTop: 6 }}>Cancel the override now</button>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <span>
            <label style={label} htmlFor="ov-mode">Capacity</label>
            <select id="ov-mode" value={overrideMode} style={{ fontSize: 12, padding: '3px 5px' }}
                    onChange={(e) => setOverrideMode(e.target.value)}>
              <option value="business_hours">Business-hours capacity now</option>
              <option value="off_hours">Off-hours capacity now</option>
              <option value="custom">The business-hours column above</option>
            </select>
          </span>
          <span>
            <label style={label} htmlFor="ov-duration">Duration</label>
            <select id="ov-duration" value={overrideDuration} style={{ fontSize: 12, padding: '3px 5px' }}
                    onChange={(e) => setOverrideDuration(e.target.value)}>
              {DURATIONS.map(([key, name]) => <option key={key} value={key}>{name}</option>)}
            </select>
          </span>
          <span style={{ flex: '1 1 200px' }}>
            <label style={label} htmlFor="ov-reason">Reason (required)</label>
            <input id="ov-reason" value={overrideReason} style={{ width: '100%', padding: '4px 6px', fontSize: 12 }}
                   onChange={(e) => setOverrideReason(e.target.value)} />
          </span>
          <button onClick={applyOverride} disabled={busy || !overrideReason.trim()}>
            Apply override
          </button>
        </div>
      )}
    </div>
  )
}
