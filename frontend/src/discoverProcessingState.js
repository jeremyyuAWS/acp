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

// "Xs ago" / "Xm ago" — matches this file's existing "${Math.round(elapsedSecs)}s elapsed" style
// rather than pulling in a formatting dependency for one line.
function fmtAgo(secs) {
  const s = Math.round(secs)
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`
}

// "2–4 min" from the queue-estimate route's earliest_at/latest_at (ISO timestamps, absolute —
// so this stays correct across however long the fact sits on screen before its next poll,
// unlike a range computed once at fetch time and left to go stale).
function fmtPickupRange(earliestAt, latestAt) {
  const now = Date.now()
  const lo = Math.max(0, Math.round((Date.parse(earliestAt) - now) / 60000))
  const hi = Math.max(lo, Math.round((Date.parse(latestAt) - now) / 60000))
  if (hi === 0) return 'under a minute'
  return lo === hi ? `about ${hi} min` : `${lo}–${hi} min`
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
  // The richer queued card (stakeholder review, 2026-08-28): "N compatible jobs ahead" rather
  // than a fragile "#3 in queue" — priority, retries and cancellations can all reorder a strict
  // position, but a plain count of this owner's OTHER queued discovery-type jobs is real and
  // does not promise an order. workersOnline/workersTotal is the SAME pool-size signal
  // WorkerAvailability already polls (GET /jobs), not a fabricated "X of Y busy" fraction —
  // this account only ever sees its own job counts (owner-scoped), never a true system-wide
  // busy/idle split, so the card says what is actually knowable instead of implying more.
  compatibleJobsAhead = null, workersTotal = null, workersOnline = null, submittedSecsAgo = null,
  // GET /scans/{id}/queue-estimate's own result (Discover.jsx's pickupEstimate state) — real
  // recent-throughput math, not a guess. Only its "estimated" shape (earliest_at/latest_at) turns
  // into a fact here; every other state (no live job yet, insufficient_history,
  // no_worker_available, or the fetch simply hasn't resolved) leaves pickupUnavailable at its
  // existing true default rather than rendering a placeholder range.
  pickupEstimate = null,
  // Live-activity facts for the discovering/lifecycle stage. foldersFound is the real
  // folders_found counter — api/scanner.py's _search_folder counts a folder the instant it is
  // DISCOVERED (added to seen_folders), not once its own listing completes, so this is honestly
  // "folders found", not "folders visited" (only populated on the folder-BFS listing path; the
  // flat Drive-query path has no folder concept and reports none, which this simply omits rather
  // than showing a fake 0). filesPerSec is NOT a backend field — Discover.jsx derives it
  // client-side from a small rolling window of real (count, timestamp) poll samples (smoothed,
  // and withheld until at least two samples span a meaningful interval — see its own comment),
  // the same way a network-speed indicator derives Mbps from byte deltas. inventoryChangedSecsAgo
  // is a SEPARATE signal from `live`/freshness on purpose: freshness says the worker is still
  // checking in; this says whether the count has actually moved recently — a large or slow
  // folder can legitimately produce neither new files nor a stall. Deliberately does NOT attempt
  // "now scanning <folder>" or "current file <name>": the backend walks several folders in
  // parallel (a thread-pool BFS, not one file at a time) and reports one aggregate total today,
  // so a single "current item" pointer would be fiction. Naming folders as *currently being
  // explored* needs backend work (folder id→path tracking, per-folder events) not built yet —
  // this only shows what a real counter can back.
  foldersFound = null, filesPerSec = null, inventoryChangedSecsAgo = null,
  // Whether Discover.jsx's separate FolderActivity component (progress.active_folders /
  // recent_folders, #929/#930 — shipped the night after the comingSoon copy below was written)
  // has real folder-level detail to show. Found live 2026-08-29: on a folder-BFS scan this
  // panel's "isn't tracked yet" note rendered directly above FolderActivity actively showing
  // folder names — the two contradicted each other on the same screen at the same time. Only
  // withhold comingSoon once there is actually something else on the page saying otherwise; a
  // flat Drive-query scan (no folder concept at all) still gets the honest "not tracked" note.
  hasFolderActivity = false,
  // The THIRD of the "Live Discovery Operations Card" PRD's three freshness timestamps (§15):
  // whether the ASSIGNED WORKER is still alive, distinct from `freshness` (the browser's own
  // SSE connection to the server) and `inventoryChangedSecsAgo` (whether the count has actually
  // moved). GET /jobs' worker_heartbeat_age_s (added 2026-08-29) — a worker container can be
  // alive with a fresh heartbeat while genuinely taking a long time on one large folder, which
  // is a different situation from the connection dropping or the worker having actually died;
  // this is what lets the card tell those apart instead of only ever showing two of three facts.
  workerHeartbeatAgeS = null,
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
        next: 'Opening the source and listing its files.',
      }
    }
    const degraded = capacityState && capacityState !== 'ready'
    const pickupFact = pickupEstimate?.state === 'estimated' && pickupEstimate.earliest_at && pickupEstimate.latest_at
      ? { label: 'Estimated pickup', value: fmtPickupRange(pickupEstimate.earliest_at, pickupEstimate.latest_at) }
      : null
    // Every fact is independently optional — a caller that cannot supply one (no scan-scoped
    // queue read, a `GET /jobs` poll that hasn't resolved yet) simply omits it rather than
    // rendering a placeholder. See ProcessingStatusPanel's own comment on this array.
    const facts = [
      compatibleJobsAhead != null
        ? { label: 'Compatible jobs ahead', value: String(compatibleJobsAhead) } : null,
      workersTotal != null
        ? { label: 'Worker pool', value: workersOnline ? `${workersTotal} online` : 'offline' } : null,
      submittedSecsAgo != null ? { label: 'Submitted', value: fmtAgo(submittedSecsAgo) } : null,
      pickupFact,
    ].filter(Boolean)
    return {
      state: 'queued',
      headline: 'Waiting for a worker',
      detail: degraded ? CAPACITY_DETAIL[capacityState] || CAPACITY_DETAIL.busy
        : 'Your Discovery request is safely queued and will start automatically.',
      recommendedAction: null,
      severity: degraded && capacityState === 'unavailable' ? 'blocked' : 'waiting',
      pickupUnavailable: !pickupFact,
      facts,
      next: 'A worker will connect to the source and begin discovering documents.',
    }
  }
  if (busy) {
    const facts = [
      discoveredCount != null ? { label: 'Files found', value: discoveredCount.toLocaleString() } : null,
      foldersFound != null ? { label: 'Folders found', value: foldersFound.toLocaleString() } : null,
      // Caller withholds this (passes null) until its own rolling window has enough samples —
      // this just renders whatever it's given, same "omit, never placeholder" rule as elsewhere.
      filesPerSec != null && filesPerSec > 0
        ? { label: 'Recent discovery rate', value: `${filesPerSec < 10 ? filesPerSec.toFixed(1) : Math.round(filesPerSec)} files/sec` } : null,
      inventoryChangedSecsAgo != null
        ? { label: 'Inventory updated', value: fmtAgo(inventoryChangedSecsAgo) } : null,
      workerHeartbeatAgeS != null
        ? { label: 'Worker heartbeat', value: fmtAgo(workerHeartbeatAgeS) } : null,
    ].filter(Boolean)
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
      facts,
      // Not a value the UI is missing by accident — the backend genuinely has no per-folder or
      // per-file signal today (a thread-pool BFS walks several folders at once and reports one
      // aggregate total). Says so, rather than a "Now scanning: —" that would look like a real
      // field waiting to populate. Withheld when FolderActivity (below, on the same screen) is
      // already showing real folder names — see hasFolderActivity above.
      comingSoon: hasFolderActivity ? null
        : 'Folder- and file-level detail (which folder or file is being read right now) '
          + "isn't tracked yet — this section will show it once that backend signal ships.",
    }
  }
  return { state: 'idle', headline: null, detail: null, recommendedAction: null, severity: 'info' }
}
