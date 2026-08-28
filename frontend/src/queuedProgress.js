import { outcomesFromRun } from './assessmentProgress.js'

// What the durable-scan poll should render this tick, given the latest scan_runs read (`g`,
// from GET /scans/{id}) and, when available, the job's own live progress (`job`, from
// GET /scans/jobs/{id} — Redis-backed, cross-replica; see core.update_job/get_job_state).
//
// WHY THE JOB ROW MATTERS. Discovery's real steps are listing -> reading metadata ->
// classifying -> applying lifecycle rules -> saving, and the backend already ticks live
// progress for two of them (files_found while listing, then files_evaluated/rules_enabled/etc
// once lifecycle rules start evaluating — see api/handlers.py's _listing_progress/_lc_progress).
// The NON-durable scan path already renders this directly (App.jsx passes the raw job object
// straight to setProgress). The durable path did not: phase here was inferred purely from
// scan_runs.files/files_done, which only distinguishes "nothing listed yet" from "per-file
// analysis" — the instant ANY file was listed, phase jumped straight to 'analysing', skipping
// over listing/metadata/classifying/lifecycle entirely, and none of the live counters the
// backend was already computing ever reached the screen.
//
// Prefer the job's own phase whenever we have a live one (queued/never-claimed excluded — that
// is not progress, it is the absence of it). It is never more than one poll tick stale, and a
// miss fetching it (job TTL'd out of Redis, a transient error) must never be treated as the scan
// itself failing — the caller passes job=null on a miss and this just falls back to the coarser
// scan_runs-derived phase for that one tick.
export function queuedProgress(g, elapsed, job) {
  const run = g && g.run
  if (job && job.phase && job.phase !== 'queued') {
    return { ...job, elapsed, outcomes: outcomesFromRun(run), files: (g && g.files) || [],
             inventory: (run && run.scope && run.scope.inventory) || null }
  }
  const total = (run && run.files) || 0
  const done = (run && run.files_done) || 0
  // Pre-created stub: job enqueued but no worker has claimed it yet. Surfaces as
  // phase:'queued' so the checklist shows the correct waiting state without 404s.
  //
  // started_at carries the REAL enqueue instant (store.pre_create_queued_scan stamps it at
  // creation) — not the component's own mount time. Without it, "Created Ns ago" on a page
  // refresh would restart from 0 on every reload of a scan that has actually been queued for
  // minutes, which is exactly the kind of dishonest-progress bug this component exists to avoid
  // elsewhere (see DiscoverRunProgress.jsx's own comments on simulated progress).
  if (run && run.status === 'queued') return { phase: 'queued', elapsed, started_at: run.started_at }
  if (!total) return { phase: 'discovering', elapsed }        // estate not listed yet
  const phase = done < total ? 'analysing' : 'scoring'
  const pct = Math.round(12 + Math.min(1, done / total) * (95 - 12))
  // Outcome tally, streamed live off the run summary (certifiable/uncertain/error, derived from
  // file_records as each file lands) — so the progress chips show real state, not just a counter.
  // `files` carries the per-file results get_scan streams, for the expandable Processing details table.
  return { phase, files_found: total, files_done: done, current: null, elapsed, pct,
           outcomes: outcomesFromRun(run), files: (g && g.files) || [],
           inventory: (run && run.scope && run.scope.inventory) || null }
}
