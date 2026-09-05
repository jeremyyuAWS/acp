import { useEffect, useMemo, useRef, useState } from 'react'
import { prefersReducedMotion, useDialog } from './a11y.js'
import {
  EVENT_FILTERS, EVENT_ICONS, NOT_REPORTED, TONE, alertRuleState, alertRuleTone, alertsModel,
  DEPLOY_ICONS, configurationModel, costModel, costText, deploymentModel, incidentRegions,
  isAzureBacked,
  notAzureBackedReason, resourceHealthModel, serviceHealthModel,
  revisionComparisonModel,
  arcPath, capacityMatchesService, chartModel,
  capacityForService, componentState, defaultMetricFor, eventClock, eventsForNode, filterEvents,
  formatDuration,
  REPLICA_STATES, gaugeModel, metricGroups, nodeTypeLabel, outputModel, provenance, queueModel,
  THROUGHPUT_SERIES, replicaLifecycle, reported, requestHealth, saturationModel, scaleEvents,
  scaleExplanation, throughputModel, tracingModel, workerJobHealth,
  revisionLabel, runModel, seriesForMetric, sourceModel, tenantConcentration, trendMarkers,
  updatedAgo,
} from './liveOpsDrawer.js'

/**
 * The Live Operations detail drawer: what is happening now, whether it is healthy, how it has
 * changed over the last 15 minutes, and whether capacity is sufficient — as visualizations rather
 * than a wall of fact tiles (PRD "Visual, Real-Time Live Operations Detail Drawer").
 *
 * Every number here comes from `liveOpsDrawer.js`, which returns null for anything ACP cannot
 * measure. This file renders null as "Not reported" and NEVER substitutes a zero, an average, or
 * a line drawn between fewer than two real samples. That is the whole point of the redesign: a
 * drawer that reads as live has to be trustworthy when the telemetry behind it is not there.
 *
 * Accessibility: status is icon + text (1.4.1), the live indicator is static under reduced motion
 * (2.3.3), the gauge and chart carry text equivalents (1.1.1), updates can be paused (2.2.2), and
 * focus is moved into the dialog, trapped, and restored on close (2.4.3 / 2.1.2 via useDialog).
 */

const PANEL = { minWidth: 0, padding: 12, border: '1px solid var(--line)', borderRadius: 10, background: 'var(--card, #fff)' }
const LABEL = { display: 'block', fontSize: 11, letterSpacing: '.02em', color: 'var(--muted)', marginBottom: 3 }

function Value({ children }) {
  return <b style={{ fontSize: 15, overflowWrap: 'anywhere' }}>{children}</b>
}

/** Where a number came from and how stale it is, next to the number. Live Operations mixes a
 *  two-second event stream, a one-minute Azure sample and figures that were never measured at
 *  all; rendered identically they all read as "now". */
function Source({ kind, at, nowMs, detail }) {
  const source = provenance(kind, { at, nowMs, detail })
  return <div className="muted" style={{ fontSize: 10.5, marginTop: 3, overflowWrap: 'anywhere' }}>
    {source.text}
  </div>
}

function Tile({ label, value, detail, source, at, nowMs }) {
  return <div style={PANEL}>
    <span style={LABEL}>{label}</span>
    <Value>{value}</Value>
    {detail && <div className="muted" style={{ fontSize: 11, marginTop: 3, overflowWrap: 'anywhere' }}>{detail}</div>}
    {source && <Source kind={source} at={at} nowMs={nowMs} />}
  </div>
}

function StateChip({ state }) {
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 700,
    color: TONE[state.tone], border: `1px solid ${TONE[state.tone]}`, borderRadius: 8, padding: '3px 9px' }}>
    <span aria-hidden="true">{state.icon}</span>{state.label}
  </span>
}

/* ─────────────────────────── A. Live header ─────────────────────────── */

function LiveHeader({ name, kind, state, connection, generatedAt, revision, nowMs, onClose, onViewAll }) {
  const still = prefersReducedMotion()
  const connected = connection === 'live'
  return <div style={{ position: 'sticky', top: 0, zIndex: 1, display: 'grid',
    gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'start', gap: 12,
    margin: '0 -20px', padding: '18px 20px 12px', background: 'var(--card, #fff)',
    borderBottom: '1px solid var(--line)' }}>
    <div style={{ minWidth: 0 }}>
      <h2 style={{ margin: 0, fontSize: 18, overflowWrap: 'anywhere' }}>{name}</h2>
      <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{nodeTypeLabel(kind)}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <StateChip state={state} />
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
          <span aria-hidden="true" className={connected && !still ? 'liveops-pulse' : undefined}
            style={{ width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
              background: connected ? 'var(--success-fg)' : 'var(--muted)' }} />
          {connected ? 'Live stream connected' : `Live stream ${connection}`}
        </span>
        <span className="muted" style={{ fontSize: 12 }}>{updatedAgo(generatedAt, nowMs)}</span>
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 5, overflowWrap: 'anywhere' }}>
        Deployment revision: {revision}
      </div>
    </div>
    <div style={{ display: 'grid', gap: 6, justifyItems: 'end' }}>
      <button className="ghost small" aria-label="Close component details" onClick={onClose}>Close</button>
      <button className="ghost small" onClick={onViewAll}>View full Live Operations</button>
    </div>
  </div>
}

/* ─────────────── B. Primary operational visualization ─────────────── */

function WorkerGauge({ gauge, service, capacity, nowMs, saturation, health, queueDepth }) {
  if (!gauge.available) {
    return <div style={{ ...PANEL, padding: 14 }} role="status">
      <b>Worker utilization unavailable</b>
      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{gauge.reason}</div>
    </div>
  }
  const color = TONE[gauge.tone]
  return <section aria-label="Worker slot utilization" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
      <svg viewBox="0 0 200 118" style={{ width: 200, height: 118, flex: '0 0 auto' }} role="img"
        aria-label={gauge.text}>
        <path d={arcPath(100, 100, 78, 1)} fill="none" stroke="var(--line)" strokeWidth="16" strokeLinecap="round" />
        {gauge.fraction > 0 && <path d={arcPath(100, 100, 78, gauge.fraction)} fill="none" stroke={color}
          strokeWidth="16" strokeLinecap="round" />}
        <text x="100" y="86" textAnchor="middle" fontSize={gauge.overCommitted ? 20 : 30}
          fontWeight="700" fill="var(--ink)">
          {gauge.pct == null ? (gauge.overCommitted ? 'over' : '—') : `${gauge.pct}%`}
        </text>
        <text x="100" y="104" textAnchor="middle" fontSize="11" fill="var(--muted)">
          {gauge.active} of {gauge.slots} slots
        </text>
        <text x="14" y="114" fontSize="10" fill="var(--muted)">0</text>
        <text x="176" y="114" fontSize="10" fill="var(--muted)">{gauge.slots}</text>
      </svg>
      <div style={{ minWidth: 160, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 700, color }}>
          <span aria-hidden="true">{{ available: '●', approaching: '▲', saturated: '■', idle: '○', unavailable: '—' }[gauge.state]}</span>
          {gauge.stateLabel}
        </div>
        <p style={{ margin: '6px 0 0', fontSize: 13 }}>{gauge.text}.</p>
        {gauge.overCommittedNote
          ? <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>{gauge.overCommittedNote}</p>
          : <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            Amber from 75% of slots, red at 100% — the documented capacity rule, not a colour range.
          </div>}
        <div className="muted" style={{ fontSize: 11, marginTop: 4, overflowWrap: 'anywhere' }}>
          Heartbeat {service?.age_s == null ? NOT_REPORTED : `${Math.round(service.age_s)}s ago`}
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 2, overflowWrap: 'anywhere' }}>
          Provisioning capacity: {capacityMatchesService(capacity, service) && capacity?.revision_provisioning_state
            ? `revision ${capacity.revision_provisioning_state}`
            : NOT_REPORTED}
        </div>
      </div>
    </div>
    <Saturation saturation={saturation} nowMs={nowMs} measuredAt={capacity?.measured_at} />
    <ScalingActivity capacity={capacity} saturation={saturation} queueDepth={queueDepth}
      lifecycle={replicaLifecycle(capacity, service)} nowMs={nowMs} />
    <JobHealth health={health} />
    <ReplicaLifecycle lifecycle={replicaLifecycle(capacity, service)} nowMs={nowMs}
      measuredAt={capacity?.measured_at} />
    <AzureMetrics capacity={capacity} service={service} nowMs={nowMs} />
  </section>
}

/**
 * Where this service's capacity actually is: how many replicas are serving, coming up or going
 * away, the active revision and its share of traffic, and — when a revision is not Provisioned —
 * Azure's own error string, which is the only place a failed rollout surfaces at all.
 */
function ReplicaLifecycle({ lifecycle, nowMs, measuredAt }) {
  if (!lifecycle.available) {
    return <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>{lifecycle.reason}</p>
  }
  return <section aria-label="Replica lifecycle" style={{ marginTop: 12 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
      <b style={{ fontSize: 13 }}>Replica lifecycle</b>
      <span className="muted" style={{ fontSize: 11 }}>
        {lifecycle.total} replica{lifecycle.total === 1 ? '' : 's'} reported
      </span>
    </div>
    {lifecycle.blocked && <p role="status" style={{ margin: '8px 0 0', padding: '9px 11px', fontSize: 12,
      borderLeft: `4px solid ${TONE.bad}`, background: 'var(--error-bg)', color: 'var(--ink)' }}>
      <b>■ Active revision is {lifecycle.blocked.state}</b>
      {lifecycle.blocked.ageS == null ? '' : ` · created ${formatDuration(lifecycle.blocked.ageS)} ago`}
      {lifecycle.blocked.error && <><br /><code style={{ overflowWrap: 'anywhere' }}>{lifecycle.blocked.error}</code></>}
    </p>}
    <ul style={{ listStyle: 'none', margin: '9px 0 0', padding: 0, display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 6, fontSize: 12 }}>
      {lifecycle.counts.map((row) => <li key={row.state} style={{ display: 'flex', gap: 7, alignItems: 'baseline' }}>
        <span aria-hidden="true" style={{ color: TONE[row.tone] }}>{row.icon}</span>
        <span style={{ flex: 1 }}>{row.label}</span><b>{row.count}</b>
      </li>)}
    </ul>
    {!!lifecycle.unreported.length && <p className="muted" style={{ fontSize: 11, margin: '8px 0 0' }}>
      Not counted: {lifecycle.unreported.join(' and ')}. {lifecycle.unreportedReason}
    </p>}
    {!!lifecycle.replicas.length && <ul style={{ listStyle: 'none', margin: '9px 0 0', padding: 0,
      display: 'grid', gap: 6, fontSize: 12 }}>
      {lifecycle.replicas.map((replica) => {
        const state = REPLICA_STATES[replica.state] || REPLICA_STATES.unknown
        return <li key={`${replica.revision}:${replica.name}`} style={{ ...PANEL, padding: 9 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <span aria-hidden="true" style={{ color: TONE[state.tone] }}>{state.icon}</span>
            <b style={{ overflowWrap: 'anywhere' }}>{replica.name || 'unnamed replica'}</b>
            <span style={{ color: TONE[state.tone], fontWeight: 700 }}>{state.label}</span>
            <span className="muted" style={{ marginLeft: 'auto' }}>
              {replica.age_s == null ? NOT_REPORTED : `up ${formatDuration(replica.age_s)}`}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 3, overflowWrap: 'anywhere' }}>
            {replica.containers_ready}/{replica.containers} containers ready ·{' '}
            {replica.restarts == null ? 'restarts not reported' : `${replica.restarts} restart${replica.restarts === 1 ? '' : 's'}`}
            {replica.revision ? ` · ${replica.revision}` : ''}
          </div>
          {replica.image && <div className="muted" style={{ fontSize: 11, overflowWrap: 'anywhere' }}>
            <code>{replica.image}</code>
          </div>}
          {replica.state_detail && <div style={{ fontSize: 11, marginTop: 3, color: TONE.bad, overflowWrap: 'anywhere' }}>
            {replica.state_detail}
          </div>}
        </li>
      })}
    </ul>}
    {!!lifecycle.revisions.length && <ul style={{ listStyle: 'none', margin: '9px 0 0', padding: 0,
      display: 'grid', gap: 4, fontSize: 11 }}>
      {lifecycle.revisions.map((revision) => <li key={revision.name} className="muted"
        style={{ overflowWrap: 'anywhere' }}>
        {revision.active ? '▶ ' : '· '}{revision.name} — {revision.health || NOT_REPORTED} ·{' '}
        {revision.provisioning_state || NOT_REPORTED} ·{' '}
        {revision.traffic_percent == null ? 'traffic not reported' : `${revision.traffic_percent}% traffic`} ·{' '}
        {revision.replicas == null ? 'replicas not reported' : `${revision.replicas} replicas`}
      </li>)}
    </ul>}
    <Source kind="azure" at={measuredAt} nowMs={nowMs} detail="Container Apps control plane" />
  </section>
}

/**
 * Whether a trace drill-down exists — and, when it does not, why, so an operator is not sent to an
 * empty query during an incident.
 */
function Tracing({ tracing }) {
  return <section aria-label="Distributed tracing" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>Traces</b>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 700,
        color: tracing.enabled ? TONE.ok : 'var(--muted)' }}>
        <span aria-hidden="true">{tracing.enabled ? '●' : '○'}</span>
        {tracing.enabled ? 'Collecting' : 'Off'}
      </span>
      {tracing.samplingRatio != null && <span className="muted" style={{ fontSize: 11 }}>
        sampling {Math.round(tracing.samplingRatio * 100)}%
      </span>}
    </div>
    {!!tracing.correlate.length && <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
      Correlates by {tracing.correlate.join(', ')}
    </div>}
    {tracing.note && <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>{tracing.note}</p>}
  </section>
}

/**
 * Active alerts — section 5.
 *
 * The panel is built around one distinction that a conventional alerts widget does not make. An
 * empty firing list renders as a green tick everywhere; here it does so ONLY when rules exist to
 * fire. Zero rules is reported as "Not monitored", in the warning tone, because a green tick over
 * a service no alert covers answers the operator's actual question — is this component healthy? —
 * with evidence that does not exist.
 *
 * A query that failed is a third state again, and says whether the cause is a missing Monitoring
 * Reader grant, which is the version an operator can act on.
 *
 * WCAG 1.4.1: every state carries its own glyph and its own words; the tone is never the only
 * thing separating firing from clear from unmonitored.
 */
function ActiveAlerts({ alerts, measuredAt, nowMs }) {
  return <section aria-label="Active alerts" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>Alerts</b>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
        fontWeight: 700, color: TONE[alerts.tone] || 'var(--muted)' }}>
        <span aria-hidden="true">{alerts.icon}</span>{alerts.text}
      </span>
      {alerts.rulesEnabled != null && alerts.rulesTotal ? <span className="muted" style={{ fontSize: 11 }}>
        {alerts.rulesEnabled} of {alerts.rulesTotal} enabled
      </span> : null}
    </div>
    <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>{alerts.reason}</p>
    {!!alerts.rules.length && <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0,
      display: 'grid', gap: 6 }}>
      {alerts.rules.map((rule) => <li key={rule.name}
        style={{ display: 'grid', gap: 2, borderTop: '1px solid var(--line,#eee)', paddingTop: 6 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 700 }}>{rule.name}</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: TONE[alertRuleTone(rule)] || 'var(--muted)' }}>
            {alertRuleState(rule)}
          </span>
          {rule.severity_label && <span className="muted" style={{ fontSize: 11 }}>
            {rule.severity_label}
          </span>}
        </div>
        {rule.condition && <span className="muted" style={{ fontSize: 11 }}>{rule.condition}</span>}
        {rule.state === 'fired' && rule.since && <span className="muted" style={{ fontSize: 11 }}>
          Firing since {eventClock(rule.since)}
        </span>}
      </li>)}
    </ul>}
    {/* No `at` when the query did not answer: an age beside "Not reported" would date a
        measurement that was never taken. */}
    <Source kind={alerts.state === 'unavailable' ? 'unavailable' : 'azure'}
      at={alerts.state === 'unavailable' ? null : measuredAt} nowMs={nowMs} />
  </section>
}

/**
 * Azure's view of this container app — section 5, beside the alerts.
 *
 * Every claim here is past tense with a time attached, because the activity log reports health
 * TRANSITIONS and Azure's current-status API is a provider this repo does not install. The state
 * that carries the design: a quiet window says "no health events", not "Available", and points at
 * the live metrics above for right now. A quiet 24 hours is the healthy case and is also what an
 * outage looks like ninety seconds in, before Azure has ingested it.
 */
function ResourceHealth({ health, nowMs }) {
  return <section aria-label="Azure resource health" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>Azure health</b>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
        fontWeight: 700, color: TONE[health.tone] || 'var(--muted)' }}>
        <span aria-hidden="true">{health.icon}</span>{health.text}
      </span>
    </div>
    <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>{health.reason}</p>
    {health.summary && <p className="muted" style={{ fontSize: 11, margin: '4px 0 0' }}>{health.summary}</p>}
    {health.transitions.length > 1 && <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0,
      display: 'grid', gap: 3 }}>
      {health.transitions.slice(0, 5).map((t, i) => <li key={`${t.at}-${i}`}
        className="muted" style={{ fontSize: 11 }}>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{eventClock(t.at)}</span>
        {' — '}{t.previous ? `${t.previous} → ` : ''}{t.status || NOT_REPORTED}
      </li>)}
    </ul>}
    {/* Dated, never live: the reading is an event Azure recorded, not a status taken just now. */}
    <Source kind={health.reportedAt ? 'azure' : 'unavailable'} at={health.reportedAt} nowMs={nowMs}
      detail={health.reportedAt ? 'last reported health transition' : undefined} />
  </section>
}

/**
 * Azure's own incidents, subscription-wide.
 *
 * Rendered once for the whole drawer rather than per service: a regional Azure incident is not a
 * fault in any one worker, and putting it inside a service's panel would read as though it were.
 * The heading says "Azure platform" for the same reason.
 */
function ServiceHealth({ platform }) {
  const rows = [...platform.active, ...platform.resolved]
  if (!platform.available && !platform.failed && !rows.length) return null
  return <section aria-label="Azure platform incidents" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>Azure platform</b>
      {!!platform.active.length && <span style={{ display: 'inline-flex', alignItems: 'center',
        gap: 6, fontSize: 12, fontWeight: 700, color: TONE.bad }}>
        <span aria-hidden="true">■</span>
        {platform.active.length} active {platform.active.length === 1 ? 'incident' : 'incidents'}
      </span>}
    </div>
    {platform.reason && <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>{platform.reason}</p>}
    {!!rows.length && <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0, display: 'grid', gap: 6 }}>
      {rows.map((incident, i) => {
        const regions = incidentRegions(incident)
        return <li key={incident.tracking_id || i}
          style={{ display: 'grid', gap: 2, borderTop: '1px solid var(--line,#eee)', paddingTop: 6 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, fontWeight: 700 }}>{incident.title || NOT_REPORTED}</span>
            <span style={{ fontSize: 11, fontWeight: 700,
              color: incident.resolved ? TONE.ok : TONE.bad }}>
              {incident.resolved ? 'Resolved' : incident.stage || 'Active'}
            </span>
            {incident.kind && <span className="muted" style={{ fontSize: 11 }}>{incident.kind}</span>}
          </div>
          {incident.summary && <span className="muted" style={{ fontSize: 11 }}>{incident.summary}</span>}
          {!!regions.length && <span className="muted" style={{ fontSize: 11 }}>{regions.join(', ')}</span>}
          {incident.tracking_id && <span className="muted" style={{ fontSize: 10.5 }}>
            Tracking {incident.tracking_id}
          </span>}
        </li>
      })}
    </ul>}
  </section>
}

/**
 * Deployment activity — section 7, with the steps Azure cannot see stated rather than skipped.
 *
 * The named gaps are the point of the panel, not a footnote. Build, image publish and smoke test
 * happen in CI and the registry; a timeline that begins at "revision created" reads as though the
 * deployment began there, and a build that never produced an image would show up as an empty
 * timeline — indistinguishable from no deployment at all.
 *
 * The revision comparison shows what Azure attributes per revision (image, requested CPU and
 * memory) and names what it does not (error rate, latency, actual use), because those are
 * collected per container app and a per-revision figure would be app-wide data under one
 * revision's name.
 */
function Deployments({ deploy, comparison }) {
  return <section aria-label="Deployment activity" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>Deployments</b>
      {deploy.failedCount > 0 && <span style={{ display: 'inline-flex', alignItems: 'center',
        gap: 6, fontSize: 12, fontWeight: 700, color: TONE.bad }}>
        <span aria-hidden="true">{DEPLOY_ICONS.failed}</span>
        {deploy.failedCount} failed
      </span>}
      {deploy.partial && <span className="muted" style={{ fontSize: 11, fontWeight: 700 }}>
        Partial
      </span>}
    </div>
    {deploy.reason && <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>{deploy.reason}</p>}

    {!!deploy.events.length && <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0,
      display: 'grid', gap: 5 }}>
      {deploy.events.slice(0, 12).map((event, i) => <li key={`${event.at}-${i}`}
        style={{ display: 'grid', gap: 1 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span aria-hidden="true" style={{ color: event.failed ? TONE.bad : 'var(--muted)' }}>
            {event.failed ? DEPLOY_ICONS.failed : DEPLOY_ICONS[event.kind] || '·'}
          </span>
          <span className="muted" style={{ fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
            {eventClock(event.at)}
          </span>
          <span style={{ fontSize: 12 }}>{event.label}</span>
          {event.status && <span style={{ fontSize: 11, fontWeight: 700,
            color: event.failed ? TONE.bad : 'var(--muted)' }}>{event.status}</span>}
        </div>
        {event.detail && <span className="muted" style={{ fontSize: 11, paddingLeft: 18,
          overflowWrap: 'anywhere' }}>{event.detail}</span>}
      </li>)}
    </ul>}

    {comparison.available && <div style={{ marginTop: 12, borderTop: '1px solid var(--line,#eee)',
      paddingTop: 10 }}>
      <span style={LABEL}>THIS REVISION VS THE LAST</span>
      {comparison.reason && <p className="muted" style={{ fontSize: 11, margin: '4px 0 0' }}>
        {comparison.reason}
      </p>}
      {!!comparison.changes.length && <ul style={{ listStyle: 'none', margin: '6px 0 0', padding: 0,
        display: 'grid', gap: 3 }}>
        {comparison.changes.map((change) => <li key={change.field} style={{ fontSize: 11 }}>
          <b>{change.label}</b>{': '}
          <span className="muted" style={{ overflowWrap: 'anywhere' }}>
            {String(change.from ?? NOT_REPORTED)} → {String(change.to ?? NOT_REPORTED)}
          </span>
        </li>)}
      </ul>}
      <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>
        {comparison.rollback
          ? `Rollback target: ${comparison.rollback.name}.`
          : comparison.rollbackReason}
      </p>
    </div>}

    {/* The gaps, last and explicit. Each says where the step actually lives, so the absence is
        a pointer rather than a blank. */}
    {(!!deploy.notReported.length || deploy.systemLogs) && <details style={{ marginTop: 10 }}>
      <summary style={{ cursor: 'pointer', fontSize: 11, fontWeight: 700 }}>
        What Azure cannot report here
      </summary>
      <ul style={{ listStyle: 'none', margin: '6px 0 0', padding: 0, display: 'grid', gap: 4 }}>
        {deploy.notReported.map((gap) => <li key={gap.step} style={{ fontSize: 11 }}>
          <b>{gap.step}</b>{' — '}<span className="muted">{gap.reason}</span>
        </li>)}
        {deploy.systemLogs && !deploy.systemLogs.available && <li style={{ fontSize: 11 }}>
          <b>System logs</b>{' — '}<span className="muted">{deploy.systemLogs.reason}</span>
        </li>}
        {comparison.notCompared.map((row) => <li key={row.field} style={{ fontSize: 11 }}>
          <b>{row.label}</b>{' — '}<span className="muted">{row.reason}</span>
        </li>)}
      </ul>
    </details>}
  </section>
}

/**
 * One of the drawer's seven sections (PRD "Best drawer experience").
 *
 * The heading is the point: every node opens the SAME seven, in the same order, so a reader who
 * has learned one node's drawer has learned all of them and can go straight to the section that
 * answers their question. A section that has little to say for this node still appears and says
 * why — an omitted section reads as "nothing to report here", which is a claim, and usually the
 * wrong one.
 */
function Section({ n, title, children }) {
  return <section aria-label={`${n}. ${title}`} style={{ display: 'grid', gap: 10 }}>
    <h3 style={{ margin: 0, fontSize: 11, fontWeight: 800, letterSpacing: '.08em',
      textTransform: 'uppercase', color: 'var(--muted)' }}>
      <span aria-hidden="true" style={{ opacity: .6 }}>{n}. </span>{title}
    </h3>
    {children}
  </section>
}

/** The sentence sections 5 and 7 show for a node Azure does not describe. One component so all of
 *  them say the same thing, and so the reason is never mistaken for an all-clear. */
function NotAzureBacked({ node }) {
  return <p className="muted" style={{ ...PANEL, padding: 12, fontSize: 11, margin: 0 }}>
    {notAzureBackedReason(node)}
  </p>
}

/**
 * Section 6 — what is CONFIGURED, as opposed to what is happening.
 *
 * It exists because "is capacity sufficient" cannot be answered from live figures alone: 90% CPU
 * against a one-core limit and 90% against four are different situations, and the limit is the
 * half a live metric never shows. Every number here is an allocation; the live counterparts are
 * in sections 2 and 3.
 */
function Configuration({ config }) {
  return <div style={{ ...PANEL, padding: 14 }}>
    {config.reason && <p className="muted" style={{ fontSize: 11, margin: 0 }}>{config.reason}</p>}
    {!!config.rows.length && <div style={{ display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 8 }}>
      {config.rows.map((row) => <div key={row.label} style={{ ...PANEL, padding: 11,
        overflowWrap: 'anywhere' }}>
        <span style={LABEL}>{row.label.toUpperCase()}</span>
        <div style={{ fontSize: 13, fontWeight: 700, marginTop: 3 }}>{row.value}</div>
        {row.detail && <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>{row.detail}</div>}
      </div>)}
    </div>}
  </div>
}

/**
 * Cost, in section 6 beside the limits it is derived from.
 *
 * Two labels that never swap. Everything computed here is "Estimated from configured capacity" —
 * derived, never measured — and actual spend is "billing data", which Azure refreshes roughly
 * every four hours. Neither is ever called live, because Cost Management is not, and a dashboard
 * that says otherwise is wrong in the direction that costs money to discover.
 *
 * With no rate configured the panel shows RESOURCE-HOURS rather than a currency figure. That is
 * the honest form of the answer: ACP knows exactly how much capacity is provisioned and cannot
 * know what the operator pays for it, and a made-up price rendered in dollars would be the most
 * confidently wrong number on the screen.
 */
function CostPanel({ cost, nowMs }) {
  if (!cost.available) return null
  return <div style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
      <b style={{ fontSize: 12 }}>Capacity cost</b>
      <span className="muted" style={{ fontSize: 11 }}>{cost.basis}</span>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))',
      gap: 8, marginTop: 10 }}>
      <div style={{ ...PANEL, padding: 11 }}>
        <span style={LABEL}>PROVISIONED NOW</span>
        <div style={{ fontSize: 13, fontWeight: 700, marginTop: 3 }}>
          {cost.totalVcpuHours == null ? NOT_REPORTED : `${cost.totalVcpuHours} vCPU-h/h`}
        </div>
        <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>
          {cost.totalGibHours == null ? NOT_REPORTED : `${cost.totalGibHours} GiB-h/h`}
        </div>
      </div>
      <div style={{ ...PANEL, padding: 11 }}>
        <span style={LABEL}>ALWAYS-ON FLOOR</span>
        <div style={{ fontSize: 13, fontWeight: 700, marginTop: 3 }}>
          {cost.floorVcpuHours == null ? NOT_REPORTED : `${cost.floorVcpuHours} vCPU-h/h`}
        </div>
        <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>
          Paid for whether or not work arrives.
        </div>
      </div>
      {cost.rateConfigured && <div style={{ ...PANEL, padding: 11 }}>
        <span style={LABEL}>ESTIMATED PER DAY</span>
        <div style={{ fontSize: 13, fontWeight: 700, marginTop: 3 }}>
          {costText(cost.estimatedDaily, cost.currency)}
        </div>
        <div className="muted" style={{ fontSize: 10.5, marginTop: 2 }}>
          At your configured rate · {costText(cost.estimatedHourly, cost.currency)}/h
        </div>
      </div>}
    </div>

    {cost.rateNote && <p className="muted" style={{ fontSize: 11, margin: '8px 0 0' }}>
      {cost.rateNote}
    </p>}

    {/* Actual spend, and why it is not here. The four-hour caveat rides with it so that when
        access does exist nobody reads the figure as current. */}
    {cost.actuals && !cost.actuals.available && <p className="muted"
      style={{ fontSize: 11, margin: '8px 0 0' }}>
      <b>Actual spend:</b> {NOT_REPORTED} — {cost.actuals.reason} {cost.actuals.billing_note}
    </p>}

    {!!cost.notInstrumented.length && <ul style={{ listStyle: 'none', margin: '8px 0 0',
      padding: 0, display: 'grid', gap: 3 }}>
      {cost.notInstrumented.map((row) => <li key={row.item} style={{ fontSize: 11 }}>
        <b>{row.item}</b>{' — '}<span className="muted">{row.reason}</span>
      </li>)}
    </ul>}

    <Source kind="estimate" nowMs={nowMs} />
  </div>
}

/**
 * Ingress behaviour: rate, response time, the response-class split and the resiliency counters.
 *
 * The average response time is labelled an AVERAGE, and the percentiles are named as unavailable
 * rather than approximated from it. That is the point of the panel's most prominent caption: an
 * average under a percentile's label is quietly wrong exactly when latency matters, since a p99
 * blowout barely moves a mean.
 */
function RequestHealth({ health, measuredAt, nowMs }) {
  const anything = health.requestsPerMin != null || health.averageResponseMs != null
    || health.classified != null
  return <section aria-label="Request health" style={{ ...PANEL, padding: 14 }}>
    <b>Request health</b>
    {!anything && <p className="muted" style={{ fontSize: 12, margin: '7px 0 0' }}>
      Azure Monitor reports no ingress metrics for the measured app. ACP's workers claim from a
      queue rather than serving requests, so a worker app has none to report.
    </p>}
    {anything && <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 10 }}>
        <Tile label="REQUEST RATE" nowMs={nowMs} at={measuredAt}
          value={health.requestsPerMin == null ? NOT_REPORTED : `${health.requestsPerMin}/min`}
          detail={health.requestsPerMin == null ? undefined : `Over ${health.windowMinutes} min`}
          source={health.requestsPerMin == null ? 'unavailable' : 'azure'} />
        <Tile label="AVERAGE RESPONSE TIME" nowMs={nowMs} at={measuredAt}
          value={health.averageResponseMs == null ? NOT_REPORTED : `${health.averageResponseMs} ms`}
          detail="An average, not a percentile"
          source={health.averageResponseMs == null ? 'unavailable' : 'azure'} />
        <Tile label="REQUEST RETRIES" nowMs={nowMs} at={measuredAt}
          value={health.retries == null ? NOT_REPORTED : health.retries}
          source={health.retries == null ? 'unavailable' : 'azure'} />
        <Tile label="CONNECTION TIMEOUTS" nowMs={nowMs} at={measuredAt}
          value={health.connectTimeouts == null ? NOT_REPORTED : health.connectTimeouts}
          source={health.connectTimeouts == null ? 'unavailable' : 'azure'} />
        <Tile label="EJECTED HOSTS" nowMs={nowMs} at={measuredAt}
          value={health.ejectedHosts == null ? NOT_REPORTED : health.ejectedHosts}
          source={health.ejectedHosts == null ? 'unavailable' : 'azure'} />
      </div>
      <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0, display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit,minmax(110px,1fr))', gap: 6, fontSize: 12 }}>
        {health.classes.map((row) => <li key={row.name} style={{ display: 'flex', gap: 7, alignItems: 'baseline' }}>
          <span aria-hidden="true" style={{ color: row.name === '5xx' ? TONE.bad
            : row.name === '4xx' ? TONE.warn : TONE.ok }}>
            {row.name === '5xx' ? '■' : row.name === '4xx' ? '▲' : '●'}
          </span>
          <span style={{ flex: 1 }}>{row.name}</span>
          <b>{row.count == null ? NOT_REPORTED : row.count}</b>
          {row.sharePct != null && <span className="muted">{row.sharePct}%</span>}
        </li>)}
      </ul>
    </>}
    <p className="muted" style={{ fontSize: 11, margin: '9px 0 0' }}>{health.percentilesNote}</p>
  </section>
}

/**
 * Documents, findings and fixes per minute, each against the five minutes before it.
 *
 * The comparison is the point — a rate on its own says nothing about whether the system is
 * catching up or falling behind. Where a rate or its comparison cannot be measured yet, the row
 * says WHICH of the two is missing, because "nothing is happening" and "this tab has not been
 * open long enough" are different answers and an empty cell means neither.
 */
function Throughput({ samples, nowMs }) {
  const rows = THROUGHPUT_SERIES.map((series) => ({ ...series, ...throughputModel(samples, series.field, { nowMs }) }))
  return <section aria-label="Throughput" style={{ ...PANEL, padding: 14 }}>
    <b>Throughput</b>
    <ul style={{ listStyle: 'none', margin: '9px 0 0', padding: 0, display: 'grid', gap: 7, fontSize: 12 }}>
      {rows.map((row) => <li key={row.key} style={{ display: 'grid',
        gridTemplateColumns: 'minmax(70px,1fr) auto auto', gap: 9, alignItems: 'baseline' }}>
        <span>{row.label}</span>
        <b>{row.current == null ? NOT_REPORTED : `${row.current}${row.unit}`}</b>
        <span style={{ color: row.change == null ? 'var(--muted)'
          : row.change > 0 ? TONE.ok : row.change < 0 ? TONE.warn : 'var(--muted)', fontSize: 11 }}>
          {row.change == null ? '—'
            : `${row.change > 0 ? '▲' : row.change < 0 ? '▼' : '■'} ${Math.abs(row.change)}${row.unit} vs previous ${row.windowMinutes} min`}
        </span>
      </li>)}
    </ul>
    {rows.some((row) => row.reason) && <p className="muted" style={{ fontSize: 11, margin: '8px 0 0' }}>
      {rows.find((row) => row.reason).reason}
    </p>}
    <Source kind="session" nowMs={nowMs} />
  </section>
}

/**
 * Scaling: what changed, what the rules are, and — when work is waiting and capacity has not
 * grown — why not, answered from the configuration rather than guessed. Azure publishes the rules
 * and the replica count, never a decision log, so "which rule fired" is not claimed.
 */
function ScalingActivity({ capacity, saturation, queueDepth, lifecycle, nowMs }) {
  const scale = capacity?.scale
  const why = scaleExplanation({ capacity, saturation, lifecycle, queueDepth })
  const events = scaleEvents(capacity)
  if (!scale && !why && !events.length) return null
  return <section aria-label="Scaling activity" style={{ marginTop: 12 }}>
    <b style={{ fontSize: 13 }}>Scaling</b>
    {why && <p role="status" style={{ margin: '7px 0 0', padding: '9px 11px', fontSize: 12,
      borderLeft: `4px solid ${TONE.warn}`, background: 'var(--warn-bg)', color: 'var(--ink)' }}>
      <b>▲ Work is waiting.</b> {why.text}
      {why.detail && <><br /><span className="muted">{why.detail}</span></>}
    </p>}
    {scale ? <>
      <div className="muted" style={{ fontSize: 11, marginTop: 7 }}>
        {reported(scale.min_replicas)} min · {reported(scale.max_replicas)} max
        {scale.polling_interval_s ? ` · polled every ${scale.polling_interval_s}s` : ''}
        {scale.cooldown_period_s ? ` · ${scale.cooldown_period_s}s cooldown` : ''}
      </div>
      {scale.rules.length === 0
        ? <p className="muted" style={{ fontSize: 11, margin: '4px 0 0' }}>
          No scale rule configured — this app stays between its minimum and maximum.
        </p>
        : <ul style={{ listStyle: 'none', margin: '6px 0 0', padding: 0, display: 'grid', gap: 4, fontSize: 11 }}>
          {scale.rules.map((rule, index) => <li key={rule.name || index} className="muted"
            style={{ overflowWrap: 'anywhere' }}>
            <b>{rule.name || 'unnamed rule'}</b> · {rule.type || 'type not reported'}
            {rule.queue_length == null ? '' : ` · queue length ${rule.queue_length}`}
            {Object.entries(rule.metadata || {}).map(([key, value]) => ` · ${key} ${value}`).join('')}
          </li>)}
        </ul>}
      <p className="muted" style={{ fontSize: 10.5, margin: '6px 0 0' }}>{scale.attribution}</p>
    </> : <p className="muted" style={{ fontSize: 11, marginTop: 7 }}>
      The scale rule for this app is not reported.
    </p>}
    {!!events.length && <ul style={{ listStyle: 'none', margin: '7px 0 0', padding: 0,
      display: 'grid', gap: 3, fontSize: 11 }}>
      {events.slice(-5).map((event) => <li key={event.at} className="muted">
        {eventClock(event.at)} — {event.text} (scale {event.direction})
      </li>)}
    </ul>}
    <Source kind="azure" at={capacity?.measured_at} nowMs={nowMs} detail="Container Apps control plane" />
  </section>
}

/**
 * What this service is working on right now, and whether it has been failing.
 *
 * Deliberately attributed to the SERVICE, not to a replica: ACP does not record which replica ran
 * a job, and the panel says so rather than letting a reader assume the join exists just because
 * the replica list is right above it.
 */
function JobHealth({ health }) {
  if (!health) return null
  return <section aria-label="Current work" style={{ marginTop: 12 }}>
    <b style={{ fontSize: 13 }}>Current work</b>
    {health.jobs.length === 0
      ? <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>
        No job is being processed by this service right now.
      </p>
      : <ul style={{ listStyle: 'none', margin: '7px 0 0', padding: 0, display: 'grid', gap: 6 }}>
        {health.jobs.map((job) => <li key={job.scanId} style={{ ...PANEL, padding: 9, fontSize: 12 }}>
          <div style={{ overflowWrap: 'anywhere' }}>
            <code>{job.file || 'file not reported'}</code>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 3, overflowWrap: 'anywhere' }}>
            {job.ruleId ? `${job.ruleId} · ` : ''}{job.jobType || 'job type not reported'}
            {' · '}
            {job.runtimeS == null ? 'claim time not reported' : `running ${formatDuration(job.runtimeS)}`}
            {job.owner ? ` · ${job.owner}` : ''}
          </div>
        </li>)}
      </ul>}
    {!!health.failing.length && <ul style={{ listStyle: 'none', margin: '8px 0 0', padding: 0,
      display: 'grid', gap: 4, fontSize: 12 }}>
      {health.failing.map((failure) => <li key={failure.scanId} style={{ color: TONE.warn }}>
        <span aria-hidden="true">▲</span> Last failure: {failure.label}
        {failure.attempts ? ` · ${failure.attempts} retr${failure.attempts === 1 ? 'y' : 'ies'}` : ''}
      </li>)}
    </ul>}
    {health.attributionReason && <p className="muted" style={{ fontSize: 11, margin: '8px 0 0' }}>
      {health.attributionReason}
    </p>}
  </section>
}

/**
 * Slots and replicas are two different capacities and are shown as two. ACP's worker slots are
 * concurrency INSIDE a replica; Azure's replicas are how many copies are running against the
 * scale rule. Every slot busy with replicas to spare, and every replica up with slots idle, are
 * opposite problems that look identical when the two are added together.
 */
function Saturation({ saturation, nowMs, measuredAt }) {
  if (!saturation) return null
  const { slots, replicas, queueDepth, drainSeconds, drainReason } = saturation
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 11 }}>
    <Tile label="WORKER SLOTS" source="live" at={measuredAt ? undefined : undefined} nowMs={nowMs}
      value={slots.total == null ? NOT_REPORTED : `${slots.active ?? 0} of ${slots.total} busy`}
      detail={slots.available == null ? undefined : `${slots.available} available`} />
    <Tile label="REPLICAS" nowMs={nowMs} at={measuredAt} source={replicas.source}
      value={replicas.running == null ? NOT_REPORTED : `${replicas.running} running`}
      detail={replicas.min == null && replicas.max == null ? undefined
        : `${replicas.min ?? '—'} min · ${replicas.max ?? '—'} max`} />
    <Tile label="SCALE HEADROOM" nowMs={nowMs} at={measuredAt} source={replicas.source}
      value={replicas.headroom == null ? NOT_REPORTED : `${replicas.headroom} more`}
      detail={replicas.atMax ? 'At the scale rule maximum — Azure will not add more' : undefined} />
    <Tile label="QUEUE FOR THIS SERVICE" source={queueDepth == null ? 'unavailable' : 'live'} nowMs={nowMs}
      value={queueDepth == null ? NOT_REPORTED : `${queueDepth} waiting`} />
    <Tile label="TIME TO CLEAR QUEUE" source={drainSeconds == null ? 'unavailable' : 'session'} nowMs={nowMs}
      value={drainSeconds == null ? 'Not enough evidence' : drainSeconds === 0 ? 'Queue is clear' : formatDuration(drainSeconds)}
      detail={drainReason || (drainSeconds ? 'From this service own completion rate' : undefined)} />
  </div>
}

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

export function humanBytes(value) {
  if (value == null || !Number.isFinite(Number(value))) return NOT_REPORTED
  let n = Number(value)
  let unit = 0
  while (n >= 1024 && unit < BYTE_UNITS.length - 1) { n /= 1024; unit += 1 }
  return `${Math.round(n * 10) / 10} ${BYTE_UNITS[unit]}`
}

/**
 * What Azure Monitor reports about THIS service's container app, when the app it measured is
 * this service's. Production runs three differently sized worker apps and WORKER_APP_NAME names
 * one, so the alternative to this guard is showing one app's restarts and network as another's.
 */
function AzureMetrics({ capacity, service, nowMs }) {
  const mine = capacityMatchesService(capacity, service)
  if (!capacity?.configured) {
    return <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
      Azure Monitor is not configured, so replica, restart and network measurements are unavailable.
    </p>
  }
  if (!mine) {
    return <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
      Azure Monitor measured <code>{capacity.worker_app_name || 'another app'}</code>, not this
      service, so its replica, restart and network figures are not shown here — they would not
      describe this service.
    </p>
  }
  const rows = [
    ['REPLICAS', 'replicas', (v) => `${v}`],
    ['CPU IN USE', 'cpu_cores_used', (v) => `${v} cores`],
    ['MEMORY WORKING SET', 'working_set_bytes', humanBytes],
    ['REPLICA RESTARTS', 'restarts', (v) => `${v}`],
    ['NETWORK IN', 'network_in_bytes', humanBytes],
    ['NETWORK OUT', 'network_out_bytes', humanBytes],
    ['RESERVED CORES', 'reserved_cores', (v) => `${v} cores`],
  ]
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 11 }}>
    {rows.map(([label, key, render]) => {
      const metric = capacity.metrics?.[key]
      const available = metric?.available && metric.latest != null
      return <Tile key={key} label={label}
        value={available ? render(metric.latest) : NOT_REPORTED}
        detail={metric?.azure_metric ? `Azure metric ${metric.azure_metric}` : undefined}
        source={available ? 'azure' : 'unavailable'} at={capacity.measured_at} nowMs={nowMs} />
    })}
  </div>
}

const SEGMENT_GLYPH = { running: '●', waiting: '◐', retrying: '▲', failed: '■' }

function QueueBar({ queue, concentration, generatedAt, nowMs }) {
  const total = queue.total
  return <section aria-label="Shared queue composition" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
      <b>Queue composition</b>
      <span className="muted" style={{ fontSize: 12 }}>{total} job{total === 1 ? '' : 's'} counted</span>
    </div>
    <div role="img" aria-label={queue.segments.map((s) => `${s.count} ${s.label.toLowerCase()}`).join(', ') || 'No queue composition reported'}
      style={{ display: 'flex', height: 22, borderRadius: 6, overflow: 'hidden', marginTop: 9,
        border: '1px solid var(--line)', background: 'var(--bg)' }}>
      {total > 0 ? queue.segments.filter((s) => s.count > 0).map((segment) => <div key={segment.key}
        title={`${segment.label}: ${segment.count}`}
        style={{ width: `${(segment.count / total) * 100}%`, background: TONE[segment.tone],
          display: 'grid', placeItems: 'center', color: '#fff', fontSize: 11, fontWeight: 700 }}>
        {(segment.count / total) > 0.12 ? segment.count : ''}
      </div>) : <div className="muted" style={{ display: 'grid', placeItems: 'center', width: '100%', fontSize: 11 }}>
        Nothing queued, running, retrying or failed
      </div>}
    </div>
    <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0, display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 6, fontSize: 12 }}>
      {queue.rows.map((row) => <li key={row.key} style={{ display: 'flex', gap: 7, alignItems: 'baseline' }}>
        <span aria-hidden="true" style={{ color: TONE[row.tone] }}>{SEGMENT_GLYPH[row.key]}</span>
        <span style={{ flex: 1 }}>{row.label}</span>
        <b>{row.count == null ? NOT_REPORTED : row.count}</b>
      </li>)}
    </ul>
    {queue.partial && <p className="muted" style={{ fontSize: 11, margin: '8px 0 0' }}>
      Rows marked “{NOT_REPORTED}” are not published by this deployment’s activity snapshot. They are
      never estimated from the counts that are.
    </p>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 11 }}>
      <Tile label="OLDEST WAIT" value={queue.oldestWaitS == null ? NOT_REPORTED : formatDuration(queue.oldestWaitS)}
        source={queue.oldestWaitS == null ? 'unavailable' : 'live'} at={generatedAt} nowMs={nowMs} />
      <Tile label="MEDIAN WAIT" value={queue.medianWaitS == null ? NOT_REPORTED : formatDuration(queue.medianWaitS)}
        detail={queue.waitSampled ? `Across ${queue.waitSampled} claimable jobs` : undefined}
        source={queue.medianWaitS == null ? 'unavailable' : 'live'} at={generatedAt} nowMs={nowMs} />
      <Tile label="95TH PERCENTILE WAIT" value={queue.p95WaitS == null ? NOT_REPORTED : formatDuration(queue.p95WaitS)}
        detail={queue.p95WaitS == null ? undefined : 'The tail, not the typical job'}
        source={queue.p95WaitS == null ? 'unavailable' : 'live'} at={generatedAt} nowMs={nowMs} />
      <Tile label="ARRIVAL RATE" value={queue.arrivalPerMin == null ? NOT_REPORTED : `${queue.arrivalPerMin}/min`}
        detail={queue.arrivalPerMin == null ? undefined : `Over the last ${Math.round(queue.windowMinutes)} min`}
        source={queue.arrivalPerMin == null ? 'unavailable' : 'live'} at={generatedAt} nowMs={nowMs} />
      <Tile label="COMPLETION RATE" value={queue.completionPerMin == null ? NOT_REPORTED : `${queue.completionPerMin}/min`}
        detail={queue.completionPerMin == null ? undefined : `Over the last ${Math.round(queue.windowMinutes)} min`}
        source={queue.completionPerMin == null ? 'unavailable' : 'live'} at={generatedAt} nowMs={nowMs} />
      <Tile label="USERS WAITING" value={queue.waitingUsers == null ? NOT_REPORTED : queue.waitingUsers}
        detail={queue.schedulingPolicy ? queue.schedulingPolicy.replaceAll('_', ' ') : undefined}
        source={queue.waitingUsers == null ? 'unavailable' : 'live'} at={generatedAt} nowMs={nowMs} />
    </div>
    {queue.fairness?.available && <div style={{ marginTop: 11 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 12 }}>Fairness</b>
        <span className="muted" style={{ fontSize: 11 }}>
          {queue.fairness.tenants} tenant{queue.fairness.tenants === 1 ? '' : 's'} waiting
        </span>
      </div>
      <div role="img" aria-label={`Waiting work split across ${queue.fairness.tenants} tenants: `
        + queue.fairness.shares.map((share) => `${share}%`).join(', ')}
        style={{ display: 'flex', height: 12, borderRadius: 4, overflow: 'hidden', marginTop: 6,
          border: '1px solid var(--line)', gap: 1 }}>
        {queue.fairness.shares.map((share, index) => <div key={index} title={`${share}%`}
          style={{ width: `${share}%`, background: index === 0 && queue.fairness.concentrated
            ? TONE.warn : 'var(--plum)', opacity: 1 - Math.min(0.6, index * 0.12) }} />)}
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
        Largest share {queue.fairness.topSharePct == null ? NOT_REPORTED : `${queue.fairness.topSharePct}%`}
        {' · '}tenants are counted, never named
      </div>
    </div>}
    {concentration.concentrated && <p role="status" style={{ margin: '10px 0 0', padding: '9px 11px', fontSize: 12,
      borderLeft: `4px solid ${TONE.warn}`, background: 'var(--warn-bg)', color: 'var(--ink)' }}>
      <b>▲ Tenant concentration:</b> one user holds {concentration.pct}% of the {concentration.total} waiting
      jobs. Tenant-fair scheduling gives other waiting users the next equally prioritized capacity.
    </p>}
  </section>
}

function RunRadial({ model, run, accent }) {
  const radius = 46
  const circumference = 2 * Math.PI * radius
  const dash = model.total ? circumference * model.fraction : 0
  const label = model.total == null
    ? 'Run progress is not reported'
    : `${model.completed} of ${model.total} documents complete`
  return <section aria-label="Run progress" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
      <svg viewBox="0 0 120 120" style={{ width: 120, height: 120, flex: '0 0 auto' }} role="img" aria-label={label}>
        <circle cx="60" cy="60" r={radius} fill="none" stroke="var(--line)" strokeWidth="12" />
        {dash > 0 && <circle cx="60" cy="60" r={radius} fill="none" stroke={accent} strokeWidth="12"
          strokeLinecap="round" strokeDasharray={`${dash.toFixed(1)} ${(circumference - dash).toFixed(1)}`}
          transform="rotate(-90 60 60)" />}
        <text x="60" y="58" textAnchor="middle" fontSize="24" fontWeight="700" fill="var(--ink)">
          {model.pct == null ? '—' : `${model.pct}%`}
        </text>
        <text x="60" y="76" textAnchor="middle" fontSize="10" fill="var(--muted)">
          {model.completed}/{model.total ?? '—'}
        </text>
      </svg>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(128px,1fr))', gap: 8, flex: 1, minWidth: 200 }}>
        <Tile label="COMPLETED" value={`${model.completed} of ${model.total ?? NOT_REPORTED}`} />
        <Tile label="PROCESSING NOW" value={model.running} />
        <Tile label="WAITING" value={model.queued}
          detail={run.queue_position ? `Queue position ${run.queue_position}` : undefined} />
        <Tile label="FAILED" value={model.failed == null ? NOT_REPORTED : model.failed}
          detail={model.failed == null ? 'Per-run failures are not published by the activity snapshot' : undefined} />
        <Tile label="ESTIMATED REMAINING"
          value={model.eta == null ? 'Not enough evidence' : formatDuration(model.eta)}
          detail={model.eta == null ? 'Needs 30s of samples with completions' : 'From this run’s own completion rate'} />
        <Tile label="OLDEST WAIT" value={model.oldestWaitS == null ? NOT_REPORTED : formatDuration(model.oldestWaitS)} />
      </div>
    </div>
    {model.currentFile && <div style={{ ...PANEL, marginTop: 10 }}>
      <span style={LABEL}>PROCESSING NOW</span>
      <code style={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{model.currentFile}</code>
      {model.ruleId && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>WCAG criterion {model.ruleId}</div>}
      {model.jobType && <div className="muted" style={{ fontSize: 12 }}>{model.jobType}</div>}
    </div>}
  </section>
}

function SourceHealth({ model, state, nowMs }) {
  return <section aria-label="Source connector health" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
      <b>Connection health</b><StateChip state={state} />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 10 }}>
      <Tile label="ACTIVE RUNS" value={model.activeRuns} detail={`${model.recentRuns} finished in the last 15 min`} />
      <Tile label="LATEST SUCCESSFUL READ"
        value={model.latestRead ? `${formatDuration(Math.max(0, Math.round((nowMs - new Date(model.latestRead).getTime()) / 1000)))} ago` : NOT_REPORTED} />
      {model.unavailable.map((label) => <Tile key={label} label={label.toUpperCase()} value={NOT_REPORTED}
        detail="The connector layer does not publish this to the activity snapshot"
        source="unavailable" />)}
    </div>
  </section>
}

function OutputSummary({ model }) {
  return <section aria-label="Durable output" style={{ ...PANEL, padding: 14 }}>
    <b>Durable output</b>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 10 }}>
      <Tile label="CORRECTED COPIES PRODUCED" value={model.correctedCopies == null ? NOT_REPORTED : model.correctedCopies}
        detail="Completed remediation work in view" />
      <Tile label="RESULTS VERIFIED" value={model.verified == null ? NOT_REPORTED : model.verified}
        detail="Completed release work in view" />
      <Tile label="WRITES AWAITING COMPLETION" value={model.awaitingWrite} />
      <Tile label="STORAGE FAILURES" value={model.storageFailures == null ? NOT_REPORTED : model.storageFailures}
        detail={model.storageFailures == null ? undefined : 'Dead-lettered jobs in the reporting window'} />
      <Tile label="TOTAL OUTPUT SIZE" value={NOT_REPORTED} source="unavailable"
        detail="Azure does not report this to the activity snapshot" />
    </div>
    <p className="muted" style={{ fontSize: 11, margin: '9px 0 0' }}>
      Original source documents are never modified; corrected copies and their evidence are written alongside.
    </p>
  </section>
}

function IntakeSummary({ snapshot, state }) {
  const summary = snapshot?.summary || {}
  return <section aria-label="Intake and orchestration" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
      <b>Intake health</b><StateChip state={state} />
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginTop: 10 }}>
      <Tile label="ACTIVE RUNS" value={reported(summary.active_runs)} />
      <Tile label="RECENTLY FINISHED" value={reported(summary.recent_runs)} />
      <Tile label="ACTIVE USERS" value={reported(summary.active_users)} />
    </div>
  </section>
}

/* ─────────────────── C. Real-time trend strip ─────────────────── */

function TrendStrip({ groups, metricKey, onMetric, chart, markers, paused, source, measuredAt, nowMs }) {
  const [active, setActive] = useState(null)
  const point = active == null ? null : chart.points[active]
  const { width, height, padLeft, padBottom, padTop } = chart.geometry
  return <section aria-label="Fifteen minute trend" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap' }}>
      <b>Last 15 minutes</b>
      <span style={{ fontSize: 18, fontWeight: 700 }}>{chart.currentLabel}</span>
    </div>
    {groups.map((group) => <div key={group.source} role="group" aria-label={`${group.label} metrics`}
      style={{ margin: '9px 0' }}>
      <div className="muted" style={{ fontSize: 10.5, marginBottom: 4 }}>{group.label}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {group.metrics.map((metric) => <button key={metric.key} type="button" className="ghost small"
          aria-pressed={metric.key === metricKey} onClick={() => { setActive(null); onMetric(metric.key) }}
          style={metric.key === metricKey ? { borderColor: 'var(--plum)', fontWeight: 700 } : undefined}>
          {metric.label}
        </button>)}
      </div>
    </div>)}
    {chart.insufficient
      ? <div className="muted" role="status" style={{ height, display: 'grid', placeItems: 'center', fontSize: 12,
        border: '1px dashed var(--line)', borderRadius: 8, textAlign: 'center', padding: 10 }}>
        {chart.sampleCount === 0
          ? `${chart.metric.label} is not reported for this component.`
          : `Collecting samples — one measurement so far. A line needs at least two.`}
      </div>
      : <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }} role="group"
        aria-label={`${chart.metric.label} over the last 15 minutes, currently ${chart.currentLabel}`}>
        <line x1={padLeft} y1={padTop} x2={padLeft} y2={height - padBottom} stroke="var(--line)" />
        <line x1={padLeft} y1={height - padBottom} x2={width - 6} y2={height - padBottom} stroke="var(--line)" />
        <text x="2" y={padTop + 4} fontSize="9" fill="var(--muted)">{chart.axis.yTop}</text>
        <text x="2" y={height - padBottom} fontSize="9" fill="var(--muted)">{chart.axis.yZero}</text>
        <text x={padLeft} y={height - 6} fontSize="9" fill="var(--muted)">{chart.axis.xStart}</text>
        <text x={width - 24} y={height - 6} fontSize="9" fill="var(--muted)">{chart.axis.xEnd}</text>
        {markers.map((marker) => <g key={marker.id}>
          <line x1={chart.xFor(marker.t)} y1={padTop} x2={chart.xFor(marker.t)} y2={height - padBottom}
            stroke="var(--info-fg)" strokeDasharray="3 3" />
          <title>{`${eventClock(marker.at)} ${marker.text}`}</title>
        </g>)}
        {chart.segments.map((segment, index) => <polyline key={index} points={segment} fill="none"
          stroke="var(--plum)" strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
        {chart.points.map((sample, index) => sample.value == null ? null : <circle key={index}
          cx={sample.x} cy={sample.y} r={active === index ? 4 : 2.5} fill="var(--plum)" tabIndex={0}
          role="img" aria-label={`${eventClock(sample.at)}: ${sample.value}${chart.metric.unit}`}
          onFocus={() => setActive(index)} onBlur={() => setActive(null)}
          onMouseEnter={() => setActive(index)} onMouseLeave={() => setActive(null)} />)}
      </svg>}
    <div aria-live="polite" className="muted" style={{ fontSize: 12, minHeight: 18, marginTop: 4 }}>
      {point ? `${eventClock(point.at)} — ${point.value}${chart.metric.unit}`
        : `${chart.metric.label}: ${chart.currentLabel} now${paused ? ' · updates paused' : ''}`}
    </div>
    <Source kind={source} at={source === 'azure' ? measuredAt : undefined} nowMs={nowMs} />
    {!!markers.length && <div className="muted" style={{ fontSize: 11 }}>
      Dashed markers: deployment and scaling moments observed during this session.
    </div>}
  </section>
}

/* ─────────────────── D. Live event timeline ─────────────────── */

function EventTimeline({ events, filter, onFilter, paused, onPause, showAll, onShowAll, copied, onCopy }) {
  const visible = showAll ? events : events.slice(0, 12)
  return <section aria-label="Live event timeline" style={{ ...PANEL, padding: 14 }}>
    <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap' }}>
      <b>Live events</b>
      <button type="button" className="ghost small" aria-pressed={paused} onClick={onPause}>
        {paused ? 'Resume visual updates' : 'Pause visual updates'}
      </button>
    </div>
    <div role="group" aria-label="Filter events" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '9px 0' }}>
      {EVENT_FILTERS.map((option) => <button key={option.key} type="button" className="ghost small"
        aria-pressed={option.key === filter} onClick={() => onFilter(option.key)}
        style={option.key === filter ? { borderColor: 'var(--plum)', fontWeight: 700 } : undefined}>
        {option.label}
      </button>)}
    </div>
    {paused && <p role="status" className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
      Updates paused — the list below is frozen. Live data keeps arriving and appears on resume.
    </p>}
    {visible.length === 0
      ? <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        No {filter === 'all' ? '' : `${filter} `}events observed for this component yet. Events appear as the
        live stream reports a change.
      </p>
      : <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 7 }}>
        {visible.map((event) => <li key={event.id} style={{ display: 'grid',
          gridTemplateColumns: 'auto auto minmax(0,1fr)', gap: 9, alignItems: 'baseline', fontSize: 12,
          borderTop: '1px solid var(--line)', paddingTop: 7 }}>
          <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--muted)' }}>{eventClock(event.at)}</span>
          <span aria-hidden="true" style={{ color: TONE[{ activity: 'ok', capacity: 'info', deployment: 'info', warning: 'warn', error: 'bad' }[event.kind] || 'idle'] }}>
            {EVENT_ICONS[event.kind] || '·'}
          </span>
          <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
            <b style={{ fontWeight: 600 }}>{event.text}</b>
            <span className="muted"> · {event.stage ? `${event.stage} · ` : ''}{event.kind}
              {event.outcome ? ` · ${event.outcome}` : ''}
              {event.durationS == null ? '' : ` · ${formatDuration(event.durationS)}`}</span>
            {event.correlation && <button type="button" className="ghost small" style={{ marginLeft: 6 }}
              onClick={() => onCopy(event.correlation)}>
              {copied === event.correlation ? 'Copied' : 'Copy correlation ID'}
            </button>}
          </span>
        </li>)}
      </ol>}
    {events.length > visible.length && <button type="button" className="ghost small"
      style={{ marginTop: 9 }} onClick={onShowAll}>Show all events ({events.length})</button>}
    <p className="muted" style={{ fontSize: 11, margin: '9px 0 0' }}>
      Events are derived from changes observed between live snapshots in this session. Document
      contents, tokens and credentials are never shown.
    </p>
  </section>
}

/* ─────────────────────────── The drawer ─────────────────────────── */

export default function LiveOpsDrawer({ nodeId, node, snapshot, capacity, connection = 'connecting',
  samples = [], events = [], facts = [], accent = 'var(--plum)', onClose, nowMs = Date.now() }) {
  const panelRef = useRef(null)
  const [metricKey, setMetricKey] = useState(() => defaultMetricFor(node?.kind))
  const [filter, setFilter] = useState('all')
  const [showAll, setShowAll] = useState(false)
  const [copied, setCopied] = useState(null)
  // Pause holds the samples and events the reader was looking at (WCAG 2.2.2). Live data keeps
  // arriving into props; freezing a copy rather than stopping the stream is what lets resume show
  // everything that happened while paused instead of a gap.
  const [frozen, setFrozen] = useState(null)
  const paused = frozen != null
  const shown = frozen || { samples, events }

  useDialog(panelRef, onClose)
  useEffect(() => { setMetricKey(defaultMetricFor(node?.kind)); setShowAll(false) }, [nodeId, node?.kind])

  // A worker node reads ITS OWN app's block when the backend published one; every other node
  // keeps the top-level reading. Before the multi-app read, two of three worker services showed
  // nothing here, because the single measured app was not theirs.
  const serviceCapacity = node?.kind === 'worker'
    ? (capacityForService(capacity, node.service) || capacity)
    : capacity
  const state = componentState(node, { snapshot, capacity: serviceCapacity, connection })
  const name = node?.kind === 'run'
    ? `${node.run?.stage || 'Run'} run · ${node.run?.owner || 'unknown user'}`
    : node?.label || 'Component'
  const groups = metricGroups(node?.kind)
  // Azure Monitor's own fifteen minutes where it has them — that history covers time before this
  // tab was opened, which the browser's own samples never can.
  const picked = seriesForMetric(shown.samples, metricKey,
    { capacity: serviceCapacity, service: node?.kind === 'worker' ? node.service : null })
  const chart = useMemo(() => chartModel(picked.samples, metricKey, { nowMs }), [picked.samples, metricKey, nowMs])
  const nodeEvents = useMemo(() => filterEvents(eventsForNode(shown.events, nodeId), filter), [shown.events, nodeId, filter])
  const markers = useMemo(() => trendMarkers(eventsForNode(shown.events, nodeId),
    { start: nowMs - 15 * 60000, end: nowMs }), [shown.events, nodeId, nowMs])

  const copy = (value) => {
    setCopied(value)
    navigator?.clipboard?.writeText?.(value)?.catch?.(() => {})
  }

  let primary = null
  if (node?.kind === 'worker') {
    primary = <WorkerGauge service={node.service} capacity={serviceCapacity} nowMs={nowMs}
      gauge={gaugeModel(node.service, { stalled: snapshot?.summary?.pressure === 'stalled' })}
      saturation={saturationModel(node.service, serviceCapacity, { samples: shown.samples,
        queueDepth: snapshot?.summary?.by_stage?.[node.service?.stage]?.queued })}
      health={workerJobHealth(snapshot, node.service?.stage, { nowMs })}
      queueDepth={snapshot?.summary?.by_stage?.[node.service?.stage]?.queued} />
  } else if (node?.kind === 'queue') {
    primary = <><QueueBar queue={queueModel(snapshot?.summary, { nowMs })} nowMs={nowMs}
      generatedAt={snapshot?.generated_at} concentration={tenantConcentration(snapshot?.runs)} />
      <Throughput samples={shown.samples} nowMs={nowMs} /></>
  } else if (node?.kind === 'run') {
    primary = <RunRadial run={node.run || {}} accent={accent}
      model={runModel(node.run, shown.samples, { nowMs })} />
  } else if (node?.kind === 'intake') {
    primary = <><IntakeSummary snapshot={snapshot} state={state} />
      <Throughput samples={shown.samples} nowMs={nowMs} />
      <RequestHealth health={requestHealth(capacity, { windowMinutes: capacity?.metrics_window_minutes || 15 })}
        measuredAt={capacity?.measured_at} nowMs={nowMs} /></>
  } else if (node?.kind === 'source') {
    primary = <SourceHealth model={sourceModel(node, snapshot)} state={state} nowMs={nowMs} />
  } else if (node?.kind === 'output') {
    primary = <OutputSummary model={outputModel(snapshot)} />
  } else {
    primary = <IntakeSummary snapshot={snapshot} state={state} />
  }

  return <>
    <button type="button" aria-label="Close component details" onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 79, border: 0, padding: 0,
        background: 'rgba(28,22,32,.28)', cursor: 'default' }} />
    <aside role="dialog" aria-modal="true" aria-label={`${name} live details`} ref={panelRef} tabIndex={-1}
      style={{ position: 'fixed', zIndex: 80, top: 0, right: 0, bottom: 0,
        width: 'clamp(360px, 38vw, 560px)', maxWidth: '100vw', overflowY: 'auto',
        overflowX: 'hidden', boxSizing: 'border-box', padding: '0 20px 24px',
        background: 'var(--card, #fff)', color: 'var(--ink, #2b2330)',
        borderLeft: `5px solid ${accent}`, display: 'grid', alignContent: 'start', gap: 12,
        boxShadow: '-12px 0 35px rgba(24,20,28,.22)', isolation: 'isolate' }}>
      <LiveHeader name={name} kind={node?.kind} state={state} connection={connection}
        generatedAt={snapshot?.generated_at} revision={revisionLabel(node, serviceCapacity)} nowMs={nowMs}
        onClose={onClose} onViewAll={onClose} />

      {/* THE SEVEN SECTIONS, in this order for EVERY node kind. The order is the reading order of
          an incident: what is it doing, is that healthy, how did it get here, what changed, what
          is shouting, what are its limits, and what is it running. A section thin for this node
          says why rather than disappearing — an absent section is a claim that there is nothing
          to report, and usually the wrong one. */}

      <Section n={1} title="Current state">
        {state.detail
          ? <p className="muted" style={{ fontSize: 12, margin: 0 }}>{state.detail}</p>
          : <p className="muted" style={{ fontSize: 12, margin: 0 }}>
              {nodeTypeLabel(node?.kind)} · state and freshness are in the header above.
            </p>}
      </Section>

      <Section n={2} title="Right now">{primary}</Section>

      <Section n={3} title="Last 15 minutes">
        <TrendStrip groups={groups} metricKey={metricKey} onMetric={setMetricKey} chart={chart}
          markers={markers} paused={paused} source={picked.source} measuredAt={picked.measuredAt}
          nowMs={nowMs} />
      </Section>

      <Section n={4} title="Live events">
        <EventTimeline events={nodeEvents} filter={filter} onFilter={setFilter} paused={paused}
          onPause={() => setFrozen((held) => (held ? null : { samples, events }))}
          showAll={showAll} onShowAll={() => setShowAll(true)}
          copied={copied} onCopy={copy} />
      </Section>

      <Section n={5} title="Alerts and platform health">
        {isAzureBacked(node)
          ? <><ActiveAlerts alerts={alertsModel(serviceCapacity)}
              measuredAt={serviceCapacity?.measured_at} nowMs={nowMs} />
            <ResourceHealth health={resourceHealthModel(serviceCapacity)} nowMs={nowMs} /></>
          : <NotAzureBacked node={node} />}
        {/* Subscription-wide, so it is read from the TOP of the capacity payload and shown on
            every node — an Azure incident is context for the whole map, not one service's fault. */}
        <ServiceHealth platform={serviceHealthModel(capacity)} />
      </Section>

      <Section n={6} title="Configuration and limits">
        <Configuration config={configurationModel(node, serviceCapacity, snapshot)} />
        {/* Subscription-wide and derived, so it is read from the top of the payload and
            shown on every node — capacity cost is a property of the deployment, not of
            whichever node happens to be open. */}
        <CostPanel cost={costModel(capacity)} nowMs={nowMs} />
      </Section>

      <Section n={7} title="Revision, deployments and traces">
        {isAzureBacked(node)
          ? <Deployments deploy={deploymentModel(serviceCapacity)}
              comparison={revisionComparisonModel(serviceCapacity)} />
          : <NotAzureBacked node={node} />}
        <Tracing tracing={tracingModel(snapshot)} />
        {!!facts.length && <details style={{ ...PANEL, padding: 12 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 700 }}>Operational facts</summary>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(175px,1fr))', gap: 8, marginTop: 10 }}>
            {facts.map(([label, value]) => <div key={label} style={{ ...PANEL, padding: 11, overflowWrap: 'anywhere' }}>
              <b style={{ display: 'block', fontSize: 11, marginBottom: 4 }}>{label}</b>{value}
            </div>)}
          </div>
          <p className="muted" style={{ fontSize: 11, margin: '9px 0 0' }}>
            This view keeps updating from ACP and Azure while the drawer is open. Values marked
            “{NOT_REPORTED}” are never estimated.
          </p>
        </details>}
      </Section>
    </aside>
  </>
}
