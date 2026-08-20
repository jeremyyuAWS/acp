// Rolling throughput + a calibrated ETA RANGE for the Assess running screen (PRD §4.2/4.3).
//
// The existing progress line shows a CUMULATIVE average (files_done / elapsed) — it's slow to react to
// the current speed. This computes a ROLLING rate over a recent window, and presents time-remaining as a
// RANGE that appears ONLY after the rate has stabilised (a "calibration" gate). The honesty rule (same
// discipline as the rest of this screen): never show a confident single ETA off two noisy early samples,
// and never fabricate one when the run has stalled — say "estimating…" instead.
//
// Pure and stateless: the caller (a hook) keeps the sample history and passes it in, so this is fully
// unit-tested with plain arrays and injected timestamps.

const DEFAULTS = {
  windowMs: 60_000,   // rolling window — recent speed, not the whole-run average
  maxSamples: 40,     // cap history so a very long scan stays bounded
  minSamples: 4,      // calibration: need at least this many points…
  minSpanMs: 12_000,  // …spanning at least this long, before we show any ETA
}

// Append a (done, at) point, deduping identical polls and pruning to the window + cap. Returns a NEW
// array (never mutates), so React state updates stay clean.
export function recordSample(history, done, at, opts = {}) {
  const { windowMs, maxSamples } = { ...DEFAULTS, ...opts }
  const d = typeof done === 'number' && done >= 0 ? done : 0
  const h = Array.isArray(history) ? history.slice() : []
  const last = h[h.length - 1]
  if (last && last.done === d && at - last.at < 500) return h   // same poll again → ignore
  h.push({ done: d, at })
  const cutoff = at - windowMs
  return h.filter((s) => s.at >= cutoff).slice(-maxSamples)
}

// { ratePerMin, eta: {lowSec, highSec} | null, calibrating } from the sample history + remaining count.
export function estimate(history, remaining, opts = {}) {
  const { minSamples, minSpanMs } = { ...DEFAULTS, ...opts }
  const h = Array.isArray(history) ? history : []
  const rem = typeof remaining === 'number' && remaining > 0 ? remaining : 0
  const first = h[0]
  const last = h[h.length - 1]

  // Not enough signal yet → calibrating: no rate, no ETA, no fabricated number.
  if (h.length < minSamples || !first || !last || (last.at - first.at) < minSpanMs) {
    return { ratePerMin: null, eta: null, calibrating: true }
  }

  const spanSec = (last.at - first.at) / 1000
  const ratePerSec = spanSec > 0 ? (last.done - first.done) / spanSec : 0
  const ratePerMin = ratePerSec > 0 ? Math.round(ratePerSec * 60) : 0

  if (rem === 0) return { ratePerMin, eta: { lowSec: 0, highSec: 0 }, calibrating: false }
  if (ratePerSec <= 0) return { ratePerMin: 0, eta: null, calibrating: true }   // stalled → no ETA

  // The RANGE reflects how variable the speed has actually been: fast intervals give the low bound, slow
  // ones the high bound. Cap the high bound so a single slow sample can't blow the estimate out.
  const rates = []
  for (let i = 1; i < h.length; i++) {
    const dt = (h[i].at - h[i - 1].at) / 1000
    const dd = h[i].done - h[i - 1].done
    if (dt > 0 && dd > 0) rates.push(dd / dt)
  }
  const minRate = rates.length ? Math.min(...rates) : ratePerSec
  const maxRate = rates.length ? Math.max(...rates) : ratePerSec
  const centerSec = rem / ratePerSec
  let lowSec = Math.round(rem / Math.max(maxRate, ratePerSec))
  let highSec = Math.round(rem / Math.max(minRate, ratePerSec / 4))   // floor slow-rate at ¼ the average
  if (highSec > centerSec * 3) highSec = Math.round(centerSec * 3)
  if (lowSec > highSec) { const t = lowSec; lowSec = highSec; highSec = t }
  return { ratePerMin, eta: { lowSec, highSec }, calibrating: false }
}

// Human copy for the range: "about 5–8 min left" / "under a minute" / "about 3 min left" (equal bounds).
export function etaRangeText(eta) {
  if (!eta) return null
  const { lowSec, highSec } = eta
  if (highSec <= 0) return 'almost done'
  if (highSec < 90) return 'under a minute left'
  const lo = Math.max(1, Math.round(lowSec / 60))
  const hi = Math.max(1, Math.round(highSec / 60))
  return lo === hi ? `about ${hi} min left` : `about ${lo}–${hi} min left`
}
