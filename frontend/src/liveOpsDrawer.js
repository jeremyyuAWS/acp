/**
 * Live Operations detail drawer — every derivation the drawer draws from, kept out of the
 * component so each one is testable without a DOM (PRD "Visual, Real-Time Live Operations
 * Detail Drawer").
 *
 * THE ONE INVARIANT. A measurement ACP does not have is `null` here and renders as
 * "Not reported" — never 0, never a line drawn through a gap, never an average standing in for a
 * sample. The drawer's whole claim is that it shows what is happening right now; a plausible
 * number in place of a missing one is the failure mode that claim cannot survive. Every function
 * below that can fail to measure returns null rather than a substitute, and the chart refuses to
 * draw a line through fewer than two real samples rather than implying a trend from one.
 *
 * `nowMs` / `nowIso` are injected everywhere rather than read from the clock, so a drawer state is
 * reproducible in a test and a 15-minute window means the same thing on every run.
 */

const MINUTE_MS = 60000
export const TREND_WINDOW_MS = 15 * MINUTE_MS
export const NOT_REPORTED = 'Not reported'

/** Finite number or null. Anything else — undefined, '', NaN, a string from JSON — is not a
 *  measurement and must not become 0. */
export function num(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function reported(value, suffix = '') {
  const n = num(value)
  return n == null ? NOT_REPORTED : `${n}${suffix}`
}

/* ───────────────────── Provenance and freshness ───────────────────── */

/**
 * Where a number came from and how stale it is, attached to the number itself.
 *
 * Live Operations mixes measurements with very different standing: a job tally from a two-second
 * event stream, an Azure Monitor metric sampled once a minute, a Log Analytics row three minutes
 * behind, a figure derived from configured capacity that was never measured at all, and billing
 * data Microsoft refreshes roughly every four hours. Rendered identically they all read as "now",
 * which is the quiet way a dashboard becomes untrustworthy — the reader cannot tell which numbers
 * they may act on immediately.
 *
 * So every value carries its source. An estimate says it is an estimate, in the same place a
 * measurement says when it was measured.
 */
export const PROVENANCE = {
  live: { label: 'Live', detail: 'ACP event stream' },
  azure: { label: 'Azure Monitor', detail: '1 min interval' },
  session: { label: 'Observed in this session', detail: 'sampled from the live stream' },
  logs: { label: 'Log Analytics', detail: 'delayed' },
  estimate: { label: 'Estimated from configured capacity', detail: 'derived, not measured' },
  billing: { label: 'Cost Management', detail: 'billing data, not live' },
  unavailable: { label: 'Not reported', detail: 'no measurement available' },
}

/**
 * "Live · 2s ago", "Azure Monitor · 1 min interval · 20s ago", "Estimated from configured
 * capacity". An age is shown only when there is an instant to compute it from — a source with no
 * timestamp says what it is and stops, rather than implying it was measured just now.
 */
export function provenance(kind, { at, nowMs = Date.now(), detail } = {}) {
  const source = PROVENANCE[kind] || PROVENANCE.unavailable
  const age = at ? secondsSince(at, nowMs) : null
  const parts = [source.label, detail ?? source.detail, age == null ? null : `${formatDuration(age)} ago`]
  return { kind, label: source.label, ageS: age, text: parts.filter(Boolean).join(' · ') }
}

/* ─────────────────────────── A. Live header ─────────────────────────── */

/** Status is icon + text, never colour alone (WCAG 1.4.1). The glyphs are deliberately
 *  different SHAPES rather than different colours of the same dot. */
export const STATES = {
  online: { label: 'Online', icon: '●', tone: 'ok' },
  degraded: { label: 'Degraded', icon: '▲', tone: 'warn' },
  offline: { label: 'Offline', icon: '■', tone: 'bad' },
  provisioning: { label: 'Provisioning', icon: '◇', tone: 'info' },
  waiting: { label: 'Waiting', icon: '◔', tone: 'warn' },
  idle: { label: 'Idle', icon: '○', tone: 'idle' },
  unavailable: { label: 'Unavailable', icon: '—', tone: 'idle' },
}

export const TONE = {
  ok: 'var(--success-fg)', warn: 'var(--warn-fg)', bad: 'var(--error-fg)',
  info: 'var(--info-fg)', idle: 'var(--muted)',
}

const NODE_TYPE = {
  worker: 'Worker service', queue: 'Shared queue', run: 'Active run',
  source: 'Source connector', output: 'Durable output', intake: 'Intake and orchestration',
}

export function nodeTypeLabel(kind) {
  return NODE_TYPE[kind] || 'Component'
}

/** Heartbeats older than this are stale: the role beat is written far more often, so a beat this
 *  old means the service stopped reporting rather than that it is merely quiet. Matches the
 *  backend's own 120s liveness window (store.worker_roles_status). */
export const STALE_HEARTBEAT_S = 120

/**
 * Which of the six states the selected component is in, with the words a reader needs. Derived
 * only from what the snapshot actually reports — a component whose evidence is missing is
 * `unavailable`, not assumed healthy.
 */
export function componentState(data = {}, ctx = {}) {
  const { snapshot = {}, capacity = null, connection = 'connecting' } = ctx
  const summary = snapshot?.summary || {}
  const withLabel = (key, label, detail) => ({ key, ...STATES[key], ...(label ? { label } : {}), detail })

  if (data.kind === 'worker') {
    const service = data.service || {}
    if (!service.alive) {
      return withLabel('offline', 'Offline', 'No heartbeat within the liveness window — this service is not claiming work.')
    }
    const age = num(service.age_s)
    if (age != null && age > STALE_HEARTBEAT_S) {
      return withLabel('degraded', 'Degraded', `Last heartbeat ${Math.round(age)}s ago.`)
    }
    const provisioningState = capacity?.revision_provisioning_state
    if (provisioningState && !/^(provisioned|succeeded)$/i.test(String(provisioningState))) {
      return withLabel('provisioning', 'Provisioning', `Active revision is ${provisioningState}.`)
    }
    if (num(service.active) === 0) {
      return withLabel('idle', 'Idle', 'Online with no work claimed — healthy, not stalled.')
    }
    return withLabel('online', 'Online', 'Claiming and processing work.')
  }

  if (data.kind === 'queue') {
    const queued = num(summary.queued) || 0
    if (summary.pressure === 'stalled') {
      return withLabel('offline', 'Stalled', 'Work is waiting and no worker tier is alive to claim it.')
    }
    if (summary.pressure === 'saturated') {
      return withLabel('degraded', 'At capacity', 'Every worker slot is busy while work waits.')
    }
    if (queued > 0) return withLabel('waiting', 'Work waiting', 'Waiting work with capacity still available.')
    return withLabel('idle', 'Idle', 'Nothing waiting for a worker.')
  }

  if (data.kind === 'run') {
    const run = data.run || {}
    if (run.status === 'recent') return withLabel('idle', 'Completed', 'Finished within the last 15 minutes.')
    if ((num(run.running) || 0) > 0) return withLabel('online', 'Processing', 'A worker is on this run now.')
    if ((num(run.queued) || 0) > 0) return withLabel('waiting', 'Waiting for capacity', 'Queued and not yet claimed.')
    return withLabel('idle', 'Idle', 'No queued or running work on this run.')
  }

  if (data.kind === 'source') {
    return (num(data.active) || 0) > 0
      ? withLabel('online', 'Active', 'Enumerating documents for at least one run.')
      : withLabel('idle', 'Ready', 'Connected with no run reading from it.')
  }

  if (data.kind === 'intake') {
    if (connection === 'live') return withLabel('online', 'Online', 'Live event stream connected.')
    if (connection === 'reconnecting') return withLabel('degraded', 'Reconnecting', 'The live event stream dropped and is retrying.')
    if (connection === 'unavailable') return withLabel('offline', 'Offline', 'The live event stream could not be established.')
    return withLabel('provisioning', 'Connecting', 'Opening the live event stream.')
  }

  if (data.kind === 'output') {
    return (num(summary.running) || 0) > 0
      ? withLabel('online', 'Writing', 'Corrected copies and results are being stored now.')
      : withLabel('idle', 'Ready', 'No writes in flight.')
  }

  return withLabel('unavailable', 'Unavailable', 'This component reports no state.')
}

/** "Updated 3s ago" — or the truth that we do not know when, which is different from "0s ago". */
export function updatedAgo(generatedAt, nowMs = Date.now()) {
  if (!generatedAt) return 'Update time unavailable'
  const then = new Date(generatedAt).getTime()
  if (!Number.isFinite(then)) return 'Update time unavailable'
  return `Updated ${formatDuration(Math.max(0, Math.round((nowMs - then) / 1000)))} ago`
}

export function formatDuration(seconds) {
  const s = num(seconds)
  if (s == null) return NOT_REPORTED
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

/** Deployment revision for the selected component. The worker capacity reading covers ONE
 *  container app (WORKER_APP_NAME), so its revision is only this service's revision when the app
 *  IS this service — otherwise the honest answer is the heartbeat's own version. */
export function revisionLabel(data = {}, capacity = null) {
  if (data.kind === 'worker') {
    const service = data.service || {}
    if (capacityMatchesService(capacity, service) && capacity?.active_revision_name) {
      return capacity.active_revision_name
    }
    return service.version || NOT_REPORTED
  }
  return capacity?.active_revision_name || NOT_REPORTED
}

/** True when the single container app Azure measured IS the service being shown. Production runs
 *  three differently sized worker apps, so a reading from one is not the others' — the same
 *  scoping AdminLiveTraffic.sizeScopeNote applies to the size figure, applied here to CPU, memory
 *  and replica counts before they are charted as this service's own. */
export function capacityMatchesService(capacity, service = {}) {
  const app = capacity?.worker_app_name
  const role = service?.role
  if (!app || !role) return false
  return app === `acp-${role}` || app.endsWith(`-${role}`)
}

/**
 * THIS service's own Azure reading.
 *
 * The backend now reads every configured worker app and returns them keyed by name under `apps`,
 * so a service whose app is in that list gets its OWN CPU, memory, replicas, restarts and
 * lifecycle instead of having them suppressed. When only one app is configured — or the service's
 * app is not among those read — this falls back to the old single-app behaviour: the top-level
 * block if it IS this service's, and null otherwise.
 *
 * Returning null rather than the wrong block is the whole point. Two of three worker services
 * used to show nothing because the one measured app was not theirs; showing that app's figures
 * instead would have been worse than showing none.
 */
export function capacityForService(capacity, service = {}) {
  if (!capacity || !service?.role) return null
  const apps = capacity.apps
  if (apps && typeof apps === 'object') {
    for (const [name, block] of Object.entries(apps)) {
      if (!block) continue
      const named = { ...block, worker_app_name: block.worker_app_name || name }
      if (capacityMatchesService(named, service)) return named
    }
  }
  return capacityMatchesService(capacity, service) ? capacity : null
}

/* ─────────────────────── Throughput ─────────────────────── */

export const THROUGHPUT_SERIES = [
  { key: 'documents', label: 'Documents', field: 'documents', unit: '/min' },
  { key: 'findings', label: 'Findings', field: 'findings', unit: '/min' },
  { key: 'fixes', label: 'Fixes', field: 'fixes', unit: '/min' },
]

/**
 * A rate now, and how it compares with the five minutes before.
 *
 * Both halves are measured the same way — a cumulative counter's change divided by the real time
 * between the first and last sample in each half — so the comparison is between like and like. It
 * needs a full previous window to compare against, which is why a tab open for four minutes gets a
 * current rate and an explicitly absent trend rather than a change computed from half a window and
 * presented as if it meant the same thing.
 *
 * A counter that goes backwards (a redeploy, a run leaving the snapshot's fifteen-minute tail)
 * yields null, not a negative rate: work is not un-done, so a fall in the counter is a change of
 * what is being counted, not a measurement of throughput.
 */
export function throughputModel(series = [], field, { nowMs = Date.now(), halfMs = 5 * 60000 } = {}) {
  const points = series
    .map((point) => ({ t: new Date(point.at).getTime(), value: num(point[field]) }))
    .filter((point) => Number.isFinite(point.t) && point.value != null)
  const rateOver = (from, to) => {
    const window = points.filter((point) => point.t >= from && point.t <= to)
    if (window.length < 2) return null
    const spanS = (window[window.length - 1].t - window[0].t) / 1000
    if (spanS < 30) return null            // the same evidence rule the run ETA uses
    const delta = window[window.length - 1].value - window[0].value
    if (delta < 0) return null
    return Math.round((delta / spanS) * 60 * 10) / 10
  }
  const current = rateOver(nowMs - halfMs, nowMs)
  const previous = rateOver(nowMs - 2 * halfMs, nowMs - halfMs)
  const change = current == null || previous == null ? null : Math.round((current - previous) * 10) / 10
  return {
    current, previous, change,
    direction: change == null ? null : change > 0 ? 'up' : change < 0 ? 'down' : 'flat',
    // Said, not implied by an empty space: the reader should know whether a missing trend means
    // "nothing happened" or "not measured for long enough yet".
    reason: current == null
      ? 'Not enough samples yet — a rate needs two readings at least 30s apart.'
      : previous == null
        ? `No comparison yet — that needs a full ${Math.round(halfMs / 60000)} minutes before this one.`
        : null,
    windowMinutes: Math.round(halfMs / 60000),
  }
}

/* ─────────────────────── Scaling activity ─────────────────────── */

/**
 * Why capacity has not grown, answered from the configuration rather than guessed.
 *
 * Every branch below is a FACT Azure or the scale rule reports, not an inference about what
 * Azure "probably" did: the app is at its configured maximum; the active revision is not
 * Provisioned so nothing can come up; replicas are still starting; or there is no scale rule at
 * all so the app sits between min and max and nothing will trigger. When none of those hold, the
 * honest answer is that Azure has not scaled YET and the reason is not reported — Container Apps
 * publishes the rules and the replica count, never a decision log.
 *
 * `null` means there is nothing to explain: the queue is empty, or capacity is in fact growing.
 */
export function scaleExplanation({ capacity = null, saturation = null, lifecycle = null,
  queueDepth = null } = {}) {
  const depth = num(queueDepth)
  if (!depth) return null
  const scale = capacity?.scale || null
  const replicas = saturation?.replicas || {}
  if (lifecycle?.blocked) {
    return { kind: 'revision', text: `The active revision is ${lifecycle.blocked.state}, so Azure `
      + 'cannot bring up more capacity until it resolves.', detail: lifecycle.blocked.error }
  }
  if (replicas.atMax) {
    return { kind: 'at_max', text: `Running ${replicas.running} replicas, the configured maximum. `
      + 'Azure will not add more until the scale rule\u2019s maximum is raised.' }
  }
  const starting = lifecycle?.counts?.find((row) => row.state === 'starting')?.count
  const allocating = lifecycle?.counts?.find((row) => row.state === 'allocating')?.count
  if ((starting || 0) + (allocating || 0) > 0) {
    return { kind: 'starting', text: `${(starting || 0) + (allocating || 0)} replica(s) are still `
      + 'coming up — capacity is being added and is not ready yet.' }
  }
  if (scale && scale.rules_reported && scale.rules.length === 0) {
    return { kind: 'no_rule', text: 'This app has no scale rule, so it stays between its minimum '
      + 'and maximum and nothing will trigger a scale-out from queue depth.' }
  }
  if (scale?.rules?.length) {
    const names = scale.rules.map((rule) => rule.name || rule.type).filter(Boolean)
    return { kind: 'not_yet',
      text: `Azure has not scaled out yet. ${names.length === 1 ? 'The rule that could' : 'The rules that could'} `
        + `is ${names.join(', ')}` + (scale.polling_interval_s
          ? `, polled every ${scale.polling_interval_s}s.` : '.'),
      detail: scale.attribution }
  }
  return { kind: 'unreported',
    text: 'Azure has not scaled out, and the scale rule for this app could not be read, so why is '
      + 'not reported.' }
}

/**
 * Scale-out and scale-in moments observed in Azure's own replica series. Azure reports the count
 * over time, never a scale event, so a change between two one-minute samples is the event — and
 * it is described as an observation rather than as something Azure announced.
 */
export function scaleEvents(capacity = null) {
  const series = capacity?.metrics?.replicas?.series
  if (!Array.isArray(series) || series.length < 2) return []
  const events = []
  for (let index = 1; index < series.length; index += 1) {
    const before = num(series[index - 1].value)
    const after = num(series[index].value)
    if (before == null || after == null || before === after) continue
    events.push({ at: series[index].at, from: before, to: after,
      direction: after > before ? 'out' : 'in',
      text: `Replicas ${after > before ? 'rose' : 'fell'} from ${before} to ${after}` })
  }
  return events
}

/* ─────────────────────── Per-worker job health ─────────────────────── */

/** The closed vocabulary the backend classifies failures into, in the words an operator uses.
 *  Free-text error messages are deliberately NOT carried across tenants — a message can name
 *  another customer's document, a vocabulary term cannot. */
export const ERROR_CLASS_LABELS = {
  capacity: 'Capacity', worker_startup: 'Worker startup', worker_crash: 'Worker crash',
  lease_expired: 'Lease expired', source_authentication: 'Source authentication',
  source_authorization: 'Source authorization', source_rate_limit: 'Source rate limit',
  source_unavailable: 'Source unavailable', storage: 'Storage', database: 'Database',
  model_rate_limit: 'AI rate limit', model_safety: 'AI safety', model_unavailable: 'AI unavailable',
  invalid_document: 'Invalid document', unsupported_document: 'Unsupported document',
  timeout: 'Timeout', cancelled: 'Cancelled', unknown: 'Unclassified',
}

/**
 * What each of this service's runs is doing right now — the file, the criterion, how long a
 * worker has actually been on it, and whether the stage has been retrying.
 *
 * Runtime comes from the job's `locked_at`, not from its status: a job claimed forty seconds ago
 * and one claimed at boot are both "running", and only the claim instant separates them. A queued
 * job has no runtime and is given none.
 *
 * ATTRIBUTION IS TO A SERVICE, NEVER TO A REPLICA. ACP does not record which replica ran a job —
 * the registry that would carry it has no writer — so this cannot say "replica r2 is working on
 * X", and the snapshot's own `worker_instance_attribution` block says so rather than leaving a
 * reader to assume the join exists.
 */
export function workerJobHealth(snapshot = {}, stage, { nowMs = Date.now() } = {}) {
  const runs = (snapshot?.runs || []).filter((run) => run.stage === stage)
  const jobs = runs
    .filter((run) => run.current_file || run.current_job_started_at)
    .map((run) => ({
      scanId: run.scan_id,
      owner: run.owner || null,
      file: run.current_file || null,
      ruleId: run.current_rule_id || null,
      jobType: run.current_job_type ? String(run.current_job_type).replaceAll('_', ' ') : null,
      runtimeS: secondsSince(run.current_job_started_at, nowMs),
    }))
  const failing = runs
    .filter((run) => run.last_error_class)
    .map((run) => ({ scanId: run.scan_id, kind: run.last_error_class,
      label: ERROR_CLASS_LABELS[run.last_error_class] || run.last_error_class,
      attempts: num(run.max_attempts_seen) }))
  const attribution = snapshot?.summary?.worker_instance_attribution || null
  return {
    jobs, failing,
    retrying: runs.some((run) => (num(run.max_attempts_seen) || 0) > 0),
    perReplica: attribution?.available === true,
    attributionReason: attribution?.available === false ? attribution.reason : null,
  }
}

/* ─────────────────────── Worker saturation ─────────────────────── */

/**
 * Is this service's capacity sufficient, and when will its queue be clear?
 *
 * Two different capacities, kept apart because conflating them is how a saturated tier looks
 * healthy: WORKER SLOTS are ACP's own concurrency inside a replica (the heartbeat's pool_size),
 * while REPLICAS are Azure's — how many copies of the app are running against the scale rule's
 * min/max. A service can have every slot busy with replicas to spare, or every replica up with
 * slots idle, and those call for opposite responses.
 *
 * The drain estimate uses the SAME evidence rule as a run's ETA — at least two samples spanning
 * 30 seconds with work actually completing — and says "not enough evidence" otherwise. A queue
 * with no completions has no drain time, and a made-up one is worse than none: it is the number
 * an operator would use to decide not to scale.
 */
export function saturationModel(service = {}, capacity = null, { samples = [], queueDepth = null } = {}) {
  const mine = capacityMatchesService(capacity, service)
  const replicaMetric = mine ? capacity?.metrics?.replicas : null
  const running = replicaMetric?.available ? num(replicaMetric.latest) : (mine ? num(capacity?.current_replicas) : null)
  const max = mine ? num(capacity?.max_replicas) : null
  const min = mine ? num(capacity?.min_replicas) : null
  const depth = num(queueDepth)
  return {
    slots: { active: num(service.active), total: num(service.slots), available: num(service.available) },
    replicas: {
      running, min, max,
      // Headroom is only a number when both ends are measured. `max` with no `running` is a
      // limit, not spare capacity, and reporting it as headroom would overstate what is available.
      headroom: running == null || max == null ? null : Math.max(0, max - running),
      atMax: running != null && max != null && running >= max,
      source: mine ? 'azure' : 'unavailable',
    },
    queueDepth: depth,
    drainSeconds: depth == null || depth === 0 ? (depth === 0 ? 0 : null) : etaSeconds(samples, depth),
    // Stated so the UI can explain a missing estimate rather than just omitting it.
    drainReason: depth == null ? 'Queue depth is not reported for this service.'
      : depth === 0 ? null
      : etaSeconds(samples, depth) == null
        ? 'Needs 30s of samples with completions before a drain time can be measured.'
        : null,
  }
}

/* ─────────────────────── Replica lifecycle ─────────────────────── */

/** Each state's word, its shape, and its tone. Shapes again, not colours alone (1.4.1). */
export const REPLICA_STATES = {
  ready: { label: 'Ready', icon: '●', tone: 'ok' },
  starting: { label: 'Starting', icon: '◐', tone: 'warn' },
  allocating: { label: 'Allocating', icon: '◇', tone: 'info' },
  draining: { label: 'Draining', icon: '◑', tone: 'info' },
  not_running: { label: 'Not running', icon: '■', tone: 'bad' },
  unknown: { label: 'Unknown', icon: '—', tone: 'idle' },
}

/**
 * The replica lifecycle for the service being shown, or a stated reason there is none.
 *
 * Scoped by the same one-app guard as every other Azure figure: `WORKER_APP_NAME` names one
 * container app and production runs three, so another app's replicas are not this service's and
 * are not shown as though they were.
 *
 * `unreported` carries the states Azure does not report — requested and failed — so the UI can
 * say why a reader counting six states sees four, rather than showing a confident zero for
 * something never measured.
 */
export function replicaLifecycle(capacity, service = null) {
  if (!capacity?.configured) {
    return { available: false, reason: 'Azure Monitor is not configured, so replica lifecycle is unavailable.' }
  }
  if (service && !capacityMatchesService(capacity, service)) {
    return { available: false,
      reason: `Azure measured ${capacity.worker_app_name || 'another container app'}, not this service, `
        + 'so its replicas would not describe this one.' }
  }
  const replicas = Array.isArray(capacity.replicas) ? capacity.replicas : []
  const lifecycle = capacity.replica_lifecycle || null
  const revisions = Array.isArray(capacity.revisions) ? capacity.revisions : []
  const active = revisions.find((revision) => revision.active) || null
  return {
    available: true,
    replicas,
    // Ordered as a rollout reads: what is serving, what is coming up, what is going away.
    counts: ['ready', 'starting', 'allocating', 'draining', 'not_running', 'unknown']
      .map((state) => ({ state, ...REPLICA_STATES[state], count: num(lifecycle?.counts?.[state]) }))
      .filter((row) => row.count != null),
    total: num(lifecycle?.total) ?? replicas.length,
    unreported: lifecycle?.unreported_states || [],
    unreportedReason: lifecycle?.unreported_reason || null,
    active,
    revisions,
    // A revision that is not Provisioned is the answer to "where is my capacity"; its own error
    // string is the answer to "why". Both come from Azure, neither is inferred.
    blocked: active && active.provisioning_state && !/^provisioned$/i.test(active.provisioning_state)
      ? { state: active.provisioning_state, error: active.provisioning_error || null, ageS: num(active.age_s) }
      : null,
  }
}

/* ──────────────────── B. Primary visualization models ──────────────────── */

/**
 * Capacity thresholds. These are the SAME rule the backend uses to classify queue pressure
 * (`api/routes/system.py::_admin_activity_snapshot`: saturated once running >= slots), extended
 * with one documented amber band so "approaching capacity" is a stated rule rather than a colour
 * chosen to look right: amber from 75% of slots, red at 100% or when work waits with no capacity.
 */
export const CAPACITY_RULES = { approachingAt: 0.75, saturatedAt: 1 }

export function gaugeModel(service = {}, options = {}) {
  const slots = num(service.slots)
  const active = num(service.active)
  const provisioning = num(options.provisioning)
  if (!service.alive && slots == null) {
    return { available: false, reason: 'This service is not reporting worker slots.', tone: 'idle', state: 'unavailable' }
  }
  if (slots == null || active == null) {
    return { available: false, reason: 'Worker slot counts are not reported by this service.', tone: 'idle', state: 'unavailable' }
  }
  const fraction = slots > 0 ? Math.min(1, active / slots) : 0
  // MORE WORK IN FLIGHT THAN SLOTS IS NOT A PERCENTAGE, and rendering it as one is how this gauge
  // came to read "51 of 2 worker slots active (2550%)" against a real deployment. The two numbers
  // are measured differently: `active` is running jobs across the whole service, while `slots` is
  // the pool size carried in a heartbeat that is last-writer-wins across replicas — so a service
  // with several replicas reports one replica's concurrency against every replica's work. A stale
  // lease produces the same shape. Either way the ratio is not a utilisation, so the percentage is
  // withheld and the condition is named instead of being dressed up as 2550% of capacity.
  const overCommitted = slots > 0 && active > slots
  const pct = slots > 0 && !overCommitted ? Math.round((active / slots) * 100) : null
  const availableSlots = Math.max(0, slots - active)
  let state = 'available'
  if (!service.alive) state = 'unavailable'
  else if (options.stalled || overCommitted) state = 'saturated'
  else if (slots > 0 && active >= slots * CAPACITY_RULES.saturatedAt) state = 'saturated'
  else if (slots > 0 && active >= slots * CAPACITY_RULES.approachingAt) state = 'approaching'
  else if (active === 0) state = 'idle'
  const tone = { available: 'ok', approaching: 'warn', saturated: 'bad', idle: 'idle', unavailable: 'idle' }[state]
  return {
    available: true, active, slots, availableSlots, provisioning, fraction, pct, state, tone,
    overCommitted,
    // The accessible equivalent the PRD requires: the gauge is decorative, this sentence is the data.
    text: overCommitted
      ? `${active} jobs in flight against ${slots} reported worker slots`
      : `${active} of ${slots} worker slots active`
        + (pct == null ? '' : ` (${pct}%)`)
        + `, ${availableSlots} available`
        + (provisioning == null ? '' : `, ${provisioning} provisioning`),
    // Named rather than computed: this is the condition, not a share of capacity.
    overCommittedNote: overCommitted
      ? 'More jobs are running than this service reports slots for. The slot count comes from a '
        + 'heartbeat that is last-writer-wins across replicas, so it describes one replica while '
        + 'the job count covers them all; a stale lease looks the same. No utilisation percentage '
        + 'is shown, because this ratio is not one.'
      : null,
    stateLabel: overCommitted ? 'Over committed'
      : { available: 'Capacity available', approaching: 'Approaching capacity',
        saturated: 'At capacity', idle: 'Idle — capacity available', unavailable: 'Capacity unavailable' }[state],
  }
}

/** Semicircular arc path, 180° (left) through 270° (top) to 360° (right). */
export function arcPath(cx, cy, r, fraction) {
  const clamped = Math.max(0, Math.min(1, num(fraction) ?? 0))
  const end = 180 + 180 * clamped
  const p = (deg) => {
    const rad = (deg * Math.PI) / 180
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
  }
  const [x0, y0] = p(180)
  const [x1, y1] = p(end)
  const large = 180 * clamped > 180 ? 1 : 0
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`
}

/**
 * The shared queue as its four real states, plus the rates. `waiting` and `retrying` split the
 * same 'queued' status by whether the job has already failed at least once — counting a retry
 * storm as capacity demand is what makes a queue look busy when it is actually failing.
 *
 * Every field degrades to null when the backend does not report it (an older API, or a store that
 * cannot answer): `segments` then carries only what IS measured and `partial` says so.
 */
export function queueModel(summary = {}, { nowMs = Date.now() } = {}) {
  const queue = summary.queue || {}
  const running = num(queue.running) ?? num(summary.running)
  const waiting = num(queue.waiting)
  const retrying = num(queue.retrying)
  const failed = num(queue.failed)
  // Older snapshots report only a single `queued` total. Show it as waiting rather than
  // inventing a split that was never measured.
  const waitingFallback = waiting == null && retrying == null ? num(summary.queued) : waiting
  const rows = [
    { key: 'running', label: 'Running', count: running, tone: 'ok' },
    { key: 'waiting', label: 'Waiting', count: waitingFallback, tone: 'info' },
    { key: 'retrying', label: 'Retrying', count: retrying, tone: 'warn' },
    { key: 'failed', label: 'Failed / dead-lettered', count: failed, tone: 'bad' },
  ]
  const segments = rows.filter((row) => row.count != null)
  const total = segments.reduce((sum, row) => sum + row.count, 0)
  const windowMinutes = (num(queue.window_s) ?? 900) / 60
  const perMinute = (value) => {
    const n = num(value)
    return n == null || !windowMinutes ? null : Math.round((n / windowMinutes) * 10) / 10
  }
  return {
    rows, segments, total,
    partial: segments.length < rows.length,
    arrivalPerMin: perMinute(queue.arrived),
    completionPerMin: perMinute(queue.completed),
    windowMinutes,
    // Elapsed from the instant the backend reports, not from a server-side seconds counter — a
    // counter would change on every two-second snapshot and defeat the stream's emit-on-change rule.
    oldestWaitS: secondsSince(queue.oldest_queued_at, nowMs),
    waitingUsers: num(summary.waiting_users),
    schedulingPolicy: summary.scheduling_policy || null,
  }
}

/** One user holding most of the waiting work — the tenant-concentration warning. */
export function tenantConcentration(runs = [], threshold = 70) {
  const byOwner = new Map()
  let total = 0
  for (const run of runs) {
    const queued = num(run.queued) || 0
    if (!queued) continue
    total += queued
    byOwner.set(run.owner, (byOwner.get(run.owner) || 0) + queued)
  }
  const [owner, count] = [...byOwner.entries()].sort((a, b) => b[1] - a[1])[0] || []
  const pct = total ? Math.round(((count || 0) / total) * 100) : 0
  return { owner: owner || null, count: count || 0, total, pct, concentrated: pct >= threshold && total > 1 }
}

/**
 * Radial progress for one run, and an ETA only when the samples can carry one.
 *
 * `failed` is deliberately null rather than 0: `admin_live_activity` groups jobs by queued /
 * running / done and does not report a per-run failure count, so a 0 here would be a claim the
 * snapshot cannot make.
 */
export function runModel(run = {}, samples = [], options = {}) {
  const completed = num(run.completed) ?? 0
  const total = num(run.total)
  const running = num(run.running) ?? 0
  const queued = num(run.queued) ?? 0
  const pct = total ? Math.min(100, Math.round((completed / total) * 100)) : null
  return {
    completed, total, running, queued,
    failed: num(run.failed),
    pct,
    fraction: total ? Math.min(1, completed / total) : 0,
    currentFile: run.current_file || null,
    ruleId: run.current_rule_id || null,
    jobType: run.current_job_type ? String(run.current_job_type).replaceAll('_', ' ') : null,
    eta: etaSeconds(samples, total == null ? null : Math.max(0, total - completed), options),
    oldestWaitS: run.oldest_queued_at ? secondsSince(run.oldest_queued_at, options.nowMs) : null,
  }
}

export function secondsSince(iso, nowMs = Date.now()) {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return null
  return Math.max(0, Math.round((nowMs - then) / 1000))
}

/**
 * Remaining time, or null. "Enough evidence" is stated, not felt: at least two samples, spanning
 * at least `minSpanS` of real time, with completed work actually increasing over that span. One
 * sample is a reading, not a rate; a 4-second span turns a single document into an hour-long
 * projection.
 */
export function etaSeconds(samples = [], remaining, { minSpanS = 30, nowMs } = {}) {
  const left = num(remaining)
  if (left == null) return null
  if (left === 0) return 0
  const points = samples.filter((s) => num(s?.completed) != null)
  if (points.length < 2) return null
  const first = points[0]
  const last = points[points.length - 1]
  const spanS = (new Date(last.at).getTime() - new Date(first.at).getTime()) / 1000
  if (!Number.isFinite(spanS) || spanS < minSpanS) return null
  const done = num(last.completed) - num(first.completed)
  if (done <= 0) return null
  return Math.round(left / (done / spanS))
}

/** Source connector health. Request rate, throttling and auth freshness are NOT measured by the
 *  activity snapshot, so they are named as unavailable rather than filled with plausible numbers. */
export function sourceModel(data = {}, snapshot = {}) {
  const runs = (snapshot?.runs || []).filter((run) => run.source === data.source)
  const active = runs.filter((run) => run.status !== 'recent')
  const latest = runs.map((run) => run.updated_at).filter(Boolean).sort().at(-1) || null
  return {
    activeRuns: active.length,
    recentRuns: runs.length - active.length,
    latestRead: latest,
    // Named, never estimated — the connector layer does not publish these to the activity snapshot.
    requestsPerMin: null,
    throttling: null,
    authFreshness: null,
    unavailable: ['Requests per minute', 'Recent throttling', 'Authentication freshness'],
  }
}

/** Durable output. Corrected copies and verification counts come from completed remediate/release
 *  work; total output size is Azure's to report and is not in this snapshot. */
export function outputModel(snapshot = {}) {
  const summary = snapshot?.summary || {}
  const stages = summary.by_stage || {}
  const queue = summary.queue || {}
  return {
    correctedCopies: num(stages.remediate?.completed),
    verified: num(stages.release?.completed),
    awaitingWrite: (num(stages.remediate?.running) ?? 0) + (num(stages.release?.running) ?? 0),
    storageFailures: num(queue.failed),
    totalSize: null,
    unavailable: ['Total output size'],
  }
}

/* ─────────────────────── C. Real-time trend strip ─────────────────────── */

/**
 * `azure` names the key in the capacity payload's `metrics` block that this trend is measured
 * from. Those come with Azure Monitor's OWN fifteen-minute, one-minute-interval history, which
 * covers time before this tab was opened — so where an Azure series exists it is preferred over
 * the samples this browser collected, and the strip says which it is showing.
 */
export const TREND_METRICS = {
  active_jobs: { key: 'active_jobs', label: 'Active jobs', field: 'active_jobs', unit: '', source: 'live' },
  queue_depth: { key: 'queue_depth', label: 'Queue depth', field: 'queue_depth', unit: '', source: 'live' },
  throughput: { key: 'throughput', label: 'Throughput', field: 'completed', rate: true, unit: '/min', source: 'session' },
  failure_rate: { key: 'failure_rate', label: 'Failure rate', field: 'failure_pct', unit: '%', source: 'live' },
  oldest_wait: { key: 'oldest_wait', label: 'Oldest queue wait', field: 'oldest_wait_s', unit: 's', source: 'live' },
  cpu: { key: 'cpu', label: 'CPU utilization', field: 'cpu_pct', unit: '%', source: 'azure', azure: 'cpu_percent' },
  memory: { key: 'memory', label: 'Memory utilization', field: 'memory_pct', unit: '%', source: 'azure', azure: 'memory_percent' },
  replicas: { key: 'replicas', label: 'Replica count', field: 'replicas', unit: '', source: 'azure', azure: 'replicas' },
  cpu_cores: { key: 'cpu_cores', label: 'CPU in use', field: 'cpu_cores', unit: ' cores', source: 'azure', azure: 'cpu_cores_used' },
  working_set: { key: 'working_set', label: 'Memory working set', field: 'working_set_bytes', unit: ' B', bytes: true, source: 'azure', azure: 'working_set_bytes' },
  restarts: { key: 'restarts', label: 'Replica restarts', field: 'restarts', unit: '', source: 'azure', azure: 'restarts' },
  network_in: { key: 'network_in', label: 'Network in', field: 'network_in_bytes', unit: ' B', bytes: true, source: 'azure', azure: 'network_in_bytes' },
  network_out: { key: 'network_out', label: 'Network out', field: 'network_out_bytes', unit: ' B', bytes: true, source: 'azure', azure: 'network_out_bytes' },
  requests: { key: 'requests', label: 'Requests', field: 'requests', unit: '', source: 'azure', azure: 'requests' },
  response_ms: { key: 'response_ms', label: 'Average response time', field: 'response_ms', unit: ' ms', source: 'azure', azure: 'response_ms' },
  retries: { key: 'retries', label: 'Request retries', field: 'retries', unit: '', source: 'azure', azure: 'retries' },
  connect_timeouts: { key: 'connect_timeouts', label: 'Connection timeouts', field: 'connect_timeouts', unit: '', source: 'azure', azure: 'connect_timeouts' },
  ejected_hosts: { key: 'ejected_hosts', label: 'Ejected hosts', field: 'ejected_hosts', unit: '', source: 'azure', azure: 'ejected_hosts' },
}

const METRICS_BY_KIND = {
  worker: ['active_jobs', 'queue_depth', 'throughput',
    'cpu', 'memory', 'replicas', 'cpu_cores', 'working_set', 'restarts', 'network_in', 'network_out'],
  queue: ['queue_depth', 'oldest_wait', 'throughput', 'failure_rate', 'active_jobs'],
  run: ['throughput', 'active_jobs', 'queue_depth'],
  source: ['active_jobs', 'throughput'],
  output: ['throughput', 'failure_rate'],
  intake: ['active_jobs', 'queue_depth', 'throughput',
    'requests', 'response_ms', 'retries', 'connect_timeouts', 'ejected_hosts'],
}

export function metricsForKind(kind) {
  return (METRICS_BY_KIND[kind] || ['active_jobs', 'queue_depth', 'throughput']).map((key) => TREND_METRICS[key])
}

/** The same metrics, split by where they are measured, so the picker never puts a two-second ACP
 *  reading and a one-minute Azure sample side by side as though they were the same kind of fact. */
export function metricGroups(kind) {
  const groups = new Map()
  for (const metric of metricsForKind(kind)) {
    const source = metric.source === 'azure' ? 'azure' : 'live'
    if (!groups.has(source)) groups.set(source, { source, label: source === 'azure' ? 'Azure Monitor' : 'ACP live', metrics: [] })
    groups.get(source).metrics.push(metric)
  }
  return [...groups.values()]
}

/**
 * The samples to chart for one metric: Azure Monitor's own series when this component's app is
 * the one Azure measured, otherwise what this browser observed.
 *
 * The guard is the same one that governs the CPU and memory numbers — production runs three
 * differently sized worker apps and only one is measured, so charting the measured app's history
 * on a service it does not describe would be a fabrication with real data in it.
 */
export function seriesForMetric(observed = [], metricKey, { capacity = null, service = null } = {}) {
  const metric = TREND_METRICS[metricKey]
  if (!metric?.azure) return { samples: observed, source: metric?.source || 'session' }
  if (service && !capacityMatchesService(capacity, service)) return { samples: [], source: 'unavailable' }
  const azure = capacity?.metrics?.[metric.azure]
  if (!azure?.series?.length) return { samples: [], source: azure ? 'azure' : 'unavailable' }
  return { samples: azure.series.map((point) => ({ at: point.at, [metric.field]: num(point.value) })),
    source: 'azure', measuredAt: capacity?.measured_at }
}

export function defaultMetricFor(kind) {
  return metricsForKind(kind)[0].key
}

/**
 * The per-node metric sample for this snapshot. Anything the snapshot cannot measure for THIS
 * node is null, so the chart shows a gap rather than a zero.
 *
 * CPU, memory and replica counts are only this service's when the one container app Azure
 * measured is this service's app — see capacityMatchesService. Charting another app's utilization
 * on a service's own trend is the specific lie this guard exists to prevent.
 */
export function sampleForNode(data = {}, ctx = {}) {
  const { snapshot = {}, capacity = null, at } = ctx
  const summary = snapshot?.summary || {}
  const stages = summary.by_stage || {}
  const queue = summary.queue || {}
  const base = { at: at || snapshot?.generated_at || null }
  const blank = {
    active_jobs: null, queue_depth: null, completed: null, cpu_pct: null,
    memory_pct: null, failure_pct: null, replicas: null, oldest_wait_s: null,
    cpu_cores: null, working_set_bytes: null, restarts: null,
    network_in_bytes: null, network_out_bytes: null,
    documents: null, findings: null, fixes: null,
    requests: null, response_ms: null, retries: null, connect_timeouts: null, ejected_hosts: null,
  }
  if (data.kind === 'worker') {
    const service = data.service || {}
    const stage = stages[service.stage] || {}
    const mine = capacityMatchesService(capacity, service)
    // `latest` is the newest one-minute sample; the flat cpu_percent/memory_percent fields are the
    // window AVERAGE and are the fallback for a backend that does not publish the metrics block.
    const azure = (key, fallback) => {
      if (!mine) return null
      const metric = capacity?.metrics?.[key]
      if (metric) return metric.available ? num(metric.latest) : null
      return fallback === undefined ? null : num(fallback)
    }
    return { ...blank, ...base,
      active_jobs: num(service.active), queue_depth: num(stage.queued),
      completed: num(stage.completed),
      cpu_pct: azure('cpu_percent', capacity?.metrics_available ? capacity.cpu_percent : null),
      memory_pct: azure('memory_percent', capacity?.metrics_available ? capacity.memory_percent : null),
      replicas: azure('replicas', capacity?.current_replicas),
      cpu_cores: azure('cpu_cores_used'),
      working_set_bytes: azure('working_set_bytes'),
      restarts: azure('restarts'),
      network_in_bytes: azure('network_in_bytes'),
      network_out_bytes: azure('network_out_bytes') }
  }
  if (data.kind === 'queue' || data.kind === 'intake') {
    const failed = num(queue.failed)
    const done = num(queue.completed)
    const denominator = (failed ?? 0) + (done ?? 0)
    // Request health belongs to whatever app Azure measured. It is attached to intake rather than
    // to a worker because these are ingress metrics and the workers claim from a queue instead of
    // serving requests — on a worker app they would be a permanent row of zeroes.
    const ingress = (key) => {
      const metric = data.kind === 'intake' ? capacity?.metrics?.[key] : null
      return metric?.available ? num(metric.latest) : null
    }
    return { ...blank, ...base,
      requests: ingress('requests'), response_ms: ingress('response_ms'),
      retries: ingress('retries'), connect_timeouts: ingress('connect_timeouts'),
      ejected_hosts: ingress('ejected_hosts'),
      // Cumulative counters for the throughput panel. `findings` stays null unless a stage
      // actually counted them — assess does, the others do not, and a 0 there would read as
      // "no findings" rather than "not counted".
      documents: num(summary.completed_jobs),
      fixes: num(stages.remediate?.completed),
      findings: num(stages.assess?.findings),
      active_jobs: num(summary.running), queue_depth: num(summary.queued),
      completed: num(summary.completed_jobs),
      failure_pct: failed == null || done == null || !denominator
        ? null : Math.round((failed / denominator) * 1000) / 10,
      oldest_wait_s: queue.oldest_queued_at
        ? secondsSince(queue.oldest_queued_at, new Date(base.at || Date.now()).getTime())
        : null }
  }
  if (data.kind === 'run') {
    const run = data.run || {}
    return { ...blank, ...base,
      active_jobs: num(run.running), queue_depth: num(run.queued), completed: num(run.completed) }
  }
  if (data.kind === 'source') {
    const runs = (snapshot?.runs || []).filter((run) => run.source === data.source)
    return { ...blank, ...base,
      active_jobs: runs.filter((run) => run.status !== 'recent').length,
      completed: runs.reduce((sum, run) => sum + (num(run.completed) || 0), 0) }
  }
  if (data.kind === 'output') {
    const failed = num(queue.failed)
    const done = num(queue.completed)
    const denominator = (failed ?? 0) + (done ?? 0)
    return { ...blank, ...base,
      completed: num(summary.completed_jobs),
      failure_pct: failed == null || done == null || !denominator
        ? null : Math.round((failed / denominator) * 1000) / 10 }
  }
  return { ...blank, ...base }
}

/**
 * Append a sample and drop everything older than the 15-minute window. Consecutive identical
 * samples are collapsed onto the newest timestamp so a quiet system does not fill the buffer with
 * duplicate points — the retained line still spans the window.
 */
export function appendSample(series = [], sample, { nowMs = Date.now(), windowMs = TREND_WINDOW_MS } = {}) {
  if (!sample?.at) return series
  const next = series.slice()
  const last = next[next.length - 1]
  const fields = Object.keys(sample).filter((key) => key !== 'at')
  const same = last && fields.every((key) => last[key] === sample[key])
  if (same) next[next.length - 1] = { ...last, at: sample.at }
  else next.push(sample)
  const cutoff = nowMs - windowMs
  const kept = next.filter((point) => {
    const t = new Date(point.at).getTime()
    return !Number.isFinite(t) || t >= cutoff
  })
  return kept.length ? kept : next.slice(-1)
}

/**
 * Chart geometry for one metric over the retained window.
 *
 * `insufficient` is true with fewer than two real values, and the caller must not draw a line:
 * a single sample joined to the axis reads as a trend that was never measured. Gaps (null
 * samples) break the polyline into segments rather than being interpolated across.
 */
export function chartModel(series = [], metricKey, { nowMs = Date.now(), windowMs = TREND_WINDOW_MS,
  width = 300, height = 110, padLeft = 34, padRight = 8, padTop = 10, padBottom = 22 } = {}) {
  const metric = TREND_METRICS[metricKey] || TREND_METRICS.active_jobs
  const raw = series.map((point) => ({ at: point.at, t: new Date(point.at).getTime(), value: num(point[metric.field]) }))
    .filter((point) => Number.isFinite(point.t))
  const values = metric.rate ? rateSeries(raw) : raw
  const withValues = values.filter((point) => point.value != null)
  const insufficient = withValues.length < 2
  const max = withValues.length ? Math.max(...withValues.map((p) => p.value)) : null
  const top = niceCeiling(max)
  const start = nowMs - windowMs
  const x = (t) => padLeft + ((Math.min(Math.max(t, start), nowMs) - start) / windowMs) * (width - padLeft - padRight)
  const y = (value) => {
    const span = top || 1
    return padTop + (1 - Math.min(1, value / span)) * (height - padTop - padBottom)
  }
  const points = values.map((point) => ({ ...point,
    x: x(point.t), y: point.value == null ? null : y(point.value) }))
  const segments = []
  let current = []
  for (const point of points) {
    if (point.value == null) { if (current.length > 1) segments.push(current); current = []; continue }
    current.push(point)
  }
  if (current.length > 1) segments.push(current)
  return {
    metric, points, insufficient,
    segments: segments.map((seg) => seg.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')),
    max: top, current: withValues.at(-1)?.value ?? null,
    currentLabel: withValues.length ? `${withValues.at(-1).value}${metric.unit}` : NOT_REPORTED,
    sampleCount: withValues.length,
    geometry: { width, height, padLeft, padRight, padTop, padBottom },
    xFor: x, yFor: y,
    axis: {
      yTop: top == null ? NOT_REPORTED : `${top}${metric.unit}`,
      yZero: '0',
      xStart: `${Math.round(windowMs / MINUTE_MS)} min ago`,
      xEnd: 'now',
    },
  }
}

/** Cumulative counter → per-minute rate. The first point has no predecessor and is therefore
 *  null, not zero; a counter reset (redeploy, window roll-off) is also null rather than a
 *  negative rate. */
export function rateSeries(points = []) {
  return points.map((point, index) => {
    if (index === 0 || point.value == null) return { ...point, value: null }
    const prev = points[index - 1]
    if (prev.value == null) return { ...point, value: null }
    const minutes = (point.t - prev.t) / MINUTE_MS
    if (minutes <= 0) return { ...point, value: null }
    const delta = point.value - prev.value
    if (delta < 0) return { ...point, value: null }
    return { ...point, value: Math.round((delta / minutes) * 10) / 10 }
  })
}

export function niceCeiling(value) {
  const n = num(value)
  if (n == null) return null
  if (n <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(n))
  for (const step of [1, 2, 2.5, 5, 10]) {
    const candidate = step * magnitude
    if (n <= candidate) return Math.round(candidate * 10) / 10
  }
  return Math.ceil(n)
}

/* ─────────────────────── D. Live event timeline ─────────────────────── */

export const EVENT_FILTERS = [
  { key: 'all', label: 'All events' },
  { key: 'activity', label: 'Activity' },
  { key: 'capacity', label: 'Capacity' },
  { key: 'deployment', label: 'Deployment' },
  { key: 'warning', label: 'Warning' },
  { key: 'error', label: 'Error' },
]

export const EVENT_ICONS = { activity: '▸', capacity: '⇅', deployment: '⬆', warning: '▲', error: '■' }

/**
 * Every operational event the drawer shows is DERIVED FROM AN OBSERVED CHANGE between two live
 * snapshots — there is no event log endpoint, and inventing one would mean inventing its
 * contents. So an event here means "these two consecutive snapshots differed in this way", which
 * is a fact, and the timeline says so in the UI.
 *
 * Document contents, tokens and credentials never appear: the only document-identifying value is
 * `current_file`, the filename the authorized activity endpoint already returns for the drawer.
 */
export function deriveEvents(prev, next, { nowIso } = {}) {
  if (!prev || !next) return []
  const at = nowIso || next.snapshot?.generated_at || new Date().toISOString()
  const events = []
  const push = (event) => events.push({ id: `${at}:${events.length}:${event.key}`, at, ...event })

  const prevRuns = new Map((prev.snapshot?.runs || []).map((run) => [`${run.scan_id}:${run.stage}`, run]))
  for (const run of next.snapshot?.runs || []) {
    const key = `${run.scan_id}:${run.stage}`
    const before = prevRuns.get(key)
    if (!before) continue
    const nodes = [key, `stage:${run.stage}`, 'infra:queue', `source:${run.source}`, 'infra:intake']
    const done = (num(run.completed) || 0) - (num(before.completed) || 0)
    if (done > 0) {
      push({ key: `${key}:done`, kind: 'activity', stage: run.stage, nodes,
        text: `${done} document${done === 1 ? '' : 's'} completed`, outcome: 'Completed',
        correlation: run.scan_id })
      push({ key: `${key}:stored`, kind: 'activity', stage: run.stage, nodes: [...nodes, 'infra:output'],
        text: `${done} result${done === 1 ? '' : 's'} stored`, outcome: 'Durable', correlation: run.scan_id })
    }
    if (run.current_file && run.current_file !== before.current_file) {
      push({ key: `${key}:claim`, kind: 'activity', stage: run.stage, nodes,
        text: `Worker claimed ${run.current_file}`, outcome: 'Claimed', correlation: run.scan_id })
    }
    if (run.current_rule_id && run.current_rule_id !== before.current_rule_id) {
      push({ key: `${key}:rule`, kind: 'activity', stage: run.stage, nodes,
        text: `Working on ${run.current_rule_id}`, outcome: 'In progress', correlation: run.scan_id })
    }
    if (before.status !== 'recent' && run.status === 'recent') {
      push({ key: `${key}:finish`, kind: 'activity', stage: run.stage, nodes,
        text: `Run finished — ${run.completed} of ${run.total} documents`, outcome: 'Finished',
        durationS: secondsSinceIso(run.started_at, run.updated_at), correlation: run.scan_id })
    }
  }

  const prevRoles = prev.snapshot?.summary?.worker_roles || {}
  const nextRoles = next.snapshot?.summary?.worker_roles || {}
  for (const [role, beat] of Object.entries(nextRoles)) {
    const before = prevRoles[role]
    if (!before) continue
    const stage = role === 'discovery' ? 'discover' : role
    const nodes = [`stage:${stage}`]
    if (!before.alive && beat.alive) {
      push({ key: `${role}:online`, kind: 'capacity', stage, nodes,
        text: `${role} worker service came online`, outcome: 'Online', correlation: role })
    }
    if (before.alive && !beat.alive) {
      push({ key: `${role}:offline`, kind: 'warning', stage, nodes,
        text: `${role} worker service stopped reporting a heartbeat`, outcome: 'Offline', correlation: role })
    }
    const beforeSlots = num(before.pool_size)
    const slots = num(beat.pool_size)
    if (beforeSlots != null && slots != null && slots !== beforeSlots) {
      push({ key: `${role}:slots`, kind: 'capacity', stage, nodes,
        text: `${role} worker slots changed from ${beforeSlots} to ${slots}`,
        outcome: slots > beforeSlots ? 'Scaled up' : 'Scaled down', correlation: role })
    }
    if (before.version && beat.version && before.version !== beat.version) {
      push({ key: `${role}:version`, kind: 'deployment', stage, nodes,
        text: `${role} worker service now running ${beat.version}`, outcome: 'Deployed', correlation: role })
    }
  }

  const beforePressure = prev.snapshot?.summary?.pressure
  const pressure = next.snapshot?.summary?.pressure
  if (beforePressure && pressure && beforePressure !== pressure) {
    const nodes = ['infra:queue', 'infra:intake']
    const text = pressure === 'healthy'
      ? 'Queue returned below capacity'
      : `Queue pressure changed from ${beforePressure} to ${pressure}`
    push({ key: 'queue:pressure', kind: pressure === 'stalled' ? 'error' : 'capacity', nodes,
      text, outcome: pressure, correlation: 'shared-queue' })
  }

  const beforeFailed = num(prev.snapshot?.summary?.queue?.failed)
  const failed = num(next.snapshot?.summary?.queue?.failed)
  if (beforeFailed != null && failed != null && failed > beforeFailed) {
    push({ key: 'queue:failed', kind: 'error', nodes: ['infra:queue', 'infra:output'],
      text: `${failed - beforeFailed} job${failed - beforeFailed === 1 ? '' : 's'} dead-lettered`,
      outcome: 'Failed', correlation: 'shared-queue' })
  }

  const beforeReplicas = num(prev.capacity?.current_replicas)
  const replicas = num(next.capacity?.current_replicas)
  const workerNodes = ['stage:discover', 'stage:assess', 'stage:remediate']
  if (beforeReplicas != null && replicas != null && replicas !== beforeReplicas) {
    push({ key: 'azure:replicas', kind: 'capacity', nodes: workerNodes,
      text: `${next.capacity?.worker_app_name || 'Worker app'} replicas changed from ${beforeReplicas} to ${replicas}`,
      outcome: replicas > beforeReplicas ? 'New replica ready' : 'Replica removed',
      correlation: next.capacity?.worker_app_name || null })
  }
  if (prev.capacity?.active_revision_name && next.capacity?.active_revision_name
      && prev.capacity.active_revision_name !== next.capacity.active_revision_name) {
    push({ key: 'azure:revision', kind: 'deployment', nodes: workerNodes,
      text: `Active revision is now ${next.capacity.active_revision_name}`, outcome: 'Deployed',
      correlation: next.capacity.active_revision_name })
  }
  if (prev.connection !== next.connection && next.connection) {
    push({ key: 'sse:connection', kind: next.connection === 'live' ? 'capacity' : 'warning',
      nodes: ['infra:intake'], text: `Live event stream ${next.connection}`,
      outcome: next.connection, correlation: 'activity-stream' })
  }
  return events
}

function secondsSinceIso(from, to) {
  if (!from || !to) return null
  const a = new Date(from).getTime()
  const b = new Date(to).getTime()
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null
  return Math.round((b - a) / 1000)
}

/** Newest first, deduped by id, bounded so a long session cannot grow without limit. */
export function mergeEvents(log = [], incoming = [], cap = 200) {
  if (!incoming.length) return log
  const seen = new Set(log.map((event) => event.id))
  const fresh = incoming.filter((event) => !seen.has(event.id))
  return [...fresh.reverse(), ...log].slice(0, cap)
}

export function eventsForNode(log = [], nodeId) {
  if (!nodeId) return log
  return log.filter((event) => !event.nodes || event.nodes.includes(nodeId))
}

export function filterEvents(log = [], filter = 'all') {
  return filter === 'all' ? log : log.filter((event) => event.kind === filter)
}

/** Timeline timestamps are wall-clock, second-resolution — the format the PRD's examples use. */
export function eventClock(iso) {
  const t = new Date(iso)
  if (!Number.isFinite(t.getTime())) return '--:--:--'
  return t.toTimeString().slice(0, 8)
}

/** Markers for deployment and scaling moments on the trend timeline. */
export function trendMarkers(log = [], { start, end } = {}) {
  return log
    .filter((event) => event.kind === 'deployment' || event.kind === 'capacity')
    .map((event) => ({ ...event, t: new Date(event.at).getTime() }))
    .filter((event) => Number.isFinite(event.t) && (start == null || event.t >= start) && (end == null || event.t <= end))
}
