// How many poll ticks to wait before the next fallback getJob() call, once the SSE stream
// (openDiscoverStream) has failed and the queued-scan poll loop has degraded to polling.
//
// The outer loop's own cadence (1s per tick, driving scanPollDecision's settlement/miss
// thresholds) is deliberately left untouched — those thresholds are tuned in NUMBER OF TICKS,
// and stretching the loop's own sleep would silently change how long "never started"/"session
// lost" take to trigger. This instead skips ticks for the FALLBACK getJob() call specifically:
// poll every tick (~1s) while the job state keeps changing, back off up to
// FALLBACK_BACKOFF_CAP_TICKS ticks (~5s) once it stops changing, and reset to every tick the
// instant it changes again. That matches the Redis live-state spec's own "poll ~once per second
// while active, back off to 2-5s when unchanged" — applied to the degraded path only, where
// reducing load matters most (a dead SSE stream usually means the backend is already stressed).
export const FALLBACK_BACKOFF_CAP_TICKS = 5

export function nextFallbackInterval(changed, currentInterval) {
  return changed ? 1 : Math.min(FALLBACK_BACKOFF_CAP_TICKS, currentInterval + 1)
}
