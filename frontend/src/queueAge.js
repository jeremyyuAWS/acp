/**
 * How long has this run actually been going? Answered from the server's own timestamp, or not
 * answered at all.
 *
 * THE DEFECT. DiscoverRunProgress anchored its clock to MOUNT:
 *
 *     const [startedAt] = useState(() => Date.now())
 *     …
 *     setElapsed(Math.round((Date.now() - startedAt) / 1000))
 *
 * so navigating to another tab and back remounts the component and the age restarts at zero. A
 * scan five minutes in reads as "0s" the moment you look away and back — which is exactly when
 * someone is checking whether it is stuck.
 *
 * The queued line already preferred `progress.started_at` for this reason, but with a silent
 * fallback:
 *
 *     const waitedSecs = secsSince(progress.started_at) ?? elapsed
 *
 * and that fallback is the second half of the same problem. When the server timestamp is absent
 * it substitutes the mount-relative number and presents it in the same words — "Created 4s ago" —
 * so a fabricated age is indistinguishable from a real one. A number nobody can tell is wrong is
 * worse than no number.
 *
 * So: derive from the persisted instant, and when there isn't one, say so.
 *
 * WHAT THIS IS NOT FOR. The component's mount-relative `elapsed` is still the right input for
 * "this view has been watching for N seconds with nothing happening" heuristics — the
 * long-running and lifecycle-slow hints. Those are questions about the watching, not about the
 * run, and server-anchoring them would fire them instantly on any reload of an older scan.
 * Deliberately left alone.
 */

/** Seconds since an ISO instant, or null if there isn't a usable one. */
export function secondsSince(iso, now = Date.now()) {
  if (!iso) return null
  const parsed = Date.parse(iso)
  if (!Number.isFinite(parsed)) return null
  // Clamped at zero: clock skew between this tab and the server, or a timestamp that arrives
  // fractionally in the future, must never render as a negative age.
  return Math.max(0, Math.round((now - parsed) / 1000))
}

/**
 * The age of a run, and where the number came from.
 *
 * @returns {{seconds: number|null, source: 'server'|'unavailable'}}
 *
 * `source` is the point. A caller cannot accidentally render an unavailable age as a real one,
 * because there is no number to render — `seconds` is null and the caller has to handle it.
 */
export function deriveRunAge({ startedAt, now = Date.now() } = {}) {
  const seconds = secondsSince(startedAt, now)
  return seconds === null ? { seconds: null, source: 'unavailable' } : { seconds, source: 'server' }
}

/**
 * What to show for a run's age. Returns the phrase, never a bare number, so the "unavailable"
 * case cannot be formatted into something that looks measured.
 */
export function ageText(age, fmt) {
  if (!age || age.source !== 'server' || age.seconds === null) return 'submission time unavailable'
  return `${fmt(age.seconds)} ago`
}

/**
 * The same instant read as a DURATION rather than an age — for a run that is still going, where
 * "N elapsed" is the natural phrasing. Same contract as ageText: a whole phrase, so a missing
 * timestamp cannot be formatted into a number that looks measured.
 */
export function elapsedText(age, fmt) {
  if (!age || age.source !== 'server' || age.seconds === null) return 'elapsed time unavailable'
  return `${fmt(age.seconds)} elapsed`
}

/**
 * For a run that has ENDED. "N elapsed" would be a lie on a terminal run — nothing is elapsing,
 * and the number keeps growing forever after the run stopped, so a scan stopped last Tuesday
 * would report "6d elapsed". The honest reading of (now - started_at) on a finished run is when
 * it STARTED, which is what this says.
 *
 * The run's actual DURATION is not derivable: scan_runs records started_at and completed_at, and
 * completed_at stays NULL for a run that stopped or died — the exact case this renders. Saying
 * "started 6d ago" is the true statement available; inventing an end instant to subtract is not.
 */
export function startedText(age, fmt) {
  if (!age || age.source !== 'server' || age.seconds === null) return 'start time unavailable'
  return `started ${fmt(age.seconds)} ago`
}
