// Pure decision logic for LiveCounter's animate-vs-jump and delta-badge behavior — kept separate
// from the requestAnimationFrame/setTimeout plumbing in LiveCounter.jsx so it is testable without
// a rAF polyfill or fake timers.
//
// Design review (2026-08-29): a live count should count UP (not just jump) when it increases, with
// a brief "+N" and a soft green wash — visual confirmation that a long, single-phase operation
// (folder discovery can run minutes with the checklist showing the same step throughout) is still
// doing real work. But never on a DECREASE: a recount or a truncation applied after the fact is a
// correction, not progress, and showing it in green would say the opposite of what happened.

/** Whether a value change should count up smoothly, or just jump straight to the new value.
 *  Never animates the first value a counter ever receives (nothing to count UP from) or a
 *  decrease (see module docstring). */
export function shouldAnimate(prev, next) {
  return prev != null && next != null && next > prev
}

/** The "+N" to show beside the number, or null when no delta badge belongs on screen. Only ever
 *  positive — a decrease shows no delta at all, not a "-N" (see module docstring). */
export function deltaFor(prev, next) {
  if (prev == null || next == null || next <= prev) return null
  return next - prev
}

/** Cubic ease-out: the same curve ScoreRing's useCountUp already uses, so a live counter and the
 *  score ring read as one visual language rather than two different animation feels on one page. */
export function ease(p) {
  const c = Math.min(1, Math.max(0, p))
  return 1 - Math.pow(1 - c, 3)
}

/** The number to display at `elapsedMs` into a `durationMs` count-up from `from` to `to`. */
export function interpolate(from, to, elapsedMs, durationMs) {
  if (durationMs <= 0 || elapsedMs >= durationMs) return to
  return Math.round(from + (to - from) * ease(elapsedMs / durationMs))
}
