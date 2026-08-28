// Discover's own instance of the "Processing status" panel derivation — see processingState.js
// (Assess) for the sibling this was generalized from. Same shape (state/headline/detail/
// recommendedAction/severity/pickupUnavailable), fed into the SAME ProcessingStatusPanel
// component, but Discover's lifecycle is genuinely different from Assess's per-file worker
// fan-out: one job walks a source (queued → discovering → lifecycle → done), not many files
// claimed independently — so "workers busy/idle" is less meaningful here than "is a worker even
// available to pick this job up", which the existing capacity_state signal already answers.
//
// Deliberately reuses signals THIS tab already computes for its own existing banners, rather
// than deriving a second, possibly-diverging notion of the same thing:
//   - failureReason: discoveryFailureReason.js (#919) — the recorded reason a failed run failed.
//   - capacityState: the same value the existing "Preparing Discovery capacity" banner reads.
//   - freshness: the same value DiscoverRunProgress's live/reconnecting/checkpoint/stale badge
//     reads (#916).
// Not a replacement for those banners (yet) — additive, matching how the Assess panel shipped
// alongside its own existing worker strip rather than replacing it.

const CAPACITY_DETAIL = {
  starting: 'A worker is starting. Your scan will begin automatically once it is ready.',
  busy: 'Discovery capacity is currently busy. Your scan will be queued and start automatically.',
  degraded: 'Discovery capacity is limited. This scan may not progress immediately.',
  unavailable: 'No compatible worker is online.',
}

const STAGE_HEADLINE = {
  discovering: 'Discovering documents',
  lifecycle: 'Applying lifecycle rules',
  connecting: 'Reconnecting',
  retrying: 'Retrying',
}

export function deriveDiscoverProcessingState({
  busy, phase, freshness, runStatus, failureReason, capacityState, discoveredCount = null,
  elapsedSecs = null,
  // Whether the durable-queue job (GET /jobs/{id}, polled only while nothing has progressed
  // yet — see Discover.jsx) has been claimed by a worker, and how long ago. This is a REAL
  // claim timestamp (jobs.locked_at), the same one AssessRunner's own job strip already reads
  // for the identical reason: "queued, nobody's claimed it" and "a worker claimed it Ns ago and
  // is opening the source" are different situations that used to render identically here.
  jobClaimed = false, assignedSecsAgo = null,
} = {}) {
  if (!busy && runStatus === 'failed') {
    return {
      state: 'failed',
      headline: 'Discovery did not finish',
      detail: failureReason || 'The last attempt to list this source failed.',
      recommendedAction: 'rerun',
      severity: 'blocked',
    }
  }
  if (!busy && (runStatus === 'cancelled' || runStatus === 'interrupted')) {
    return {
      state: runStatus,
      headline: runStatus === 'cancelled' ? 'Discovery was stopped' : 'Discovery was interrupted',
      detail: 'The counts on this scan reflect only what was found up to that point.',
      recommendedAction: 'rerun',
      severity: 'warning',
    }
  }
  if (!busy && runStatus === 'running') {
    return {
      state: 'stuck',
      headline: 'This scan may be stuck',
      detail: 'It still shows as running, but nothing here is tracking its live progress right now.',
      recommendedAction: 'rerun',
      severity: 'warning',
    }
  }
  if (!busy && runStatus === 'queued') {
    return {
      state: 'queued',
      headline: 'Queued — not started yet',
      detail: 'This scan has not been picked up by a worker yet.',
      recommendedAction: null,
      severity: 'waiting',
      pickupUnavailable: true,
    }
  }
  if (busy && phase === 'queued') {
    if (jobClaimed) {
      return {
        state: 'assigned',
        headline: 'Worker assigned',
        detail: assignedSecsAgo != null
          ? `A worker claimed this job ${Math.round(assignedSecsAgo)}s ago and is opening the source.`
          : 'A worker has claimed this job and is opening the source.',
        recommendedAction: null,
        severity: 'active',
      }
    }
    const degraded = capacityState && capacityState !== 'ready'
    return {
      state: 'queued',
      headline: 'Waiting for a worker',
      detail: degraded ? CAPACITY_DETAIL[capacityState] || CAPACITY_DETAIL.busy
        : 'Discovery is queued and will begin automatically.',
      recommendedAction: null,
      severity: degraded && capacityState === 'unavailable' ? 'blocked' : 'waiting',
      pickupUnavailable: true,
    }
  }
  if (busy) {
    return {
      state: 'discovering',
      headline: STAGE_HEADLINE[phase] || 'Discovering documents',
      detail: [
        discoveredCount != null ? `${discoveredCount} found so far` : null,
        elapsedSecs != null ? `${Math.round(elapsedSecs)}s elapsed` : null,
        freshness === 'reconnecting' ? 'Live connection lost — reconnecting' : null,
        freshness === 'stale' ? 'No live signal — data may be outdated' : null,
      ].filter(Boolean).join(' · '),
      recommendedAction: null,
      severity: freshness === 'stale' ? 'warning' : 'active',
      // freshness === 'live' means api/routes/scans.py's _scan_freshness saw this scan's Redis
      // job state update within the last 30s (#916) — the SSE-fed signal already flowing into
      // `progress.freshness`. Surfaced here as its own flag (not inferred from severity/state by
      // the panel) so "near real-time" is an honest claim tied to the same freshness value the
      // reconnecting/stale clauses above already read, not a separate, invented notion of live.
      live: freshness === 'live',
    }
  }
  return { state: 'idle', headline: null, detail: null, recommendedAction: null, severity: 'info' }
}
