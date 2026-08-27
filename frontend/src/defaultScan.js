// Which scan a dashboard should default to — the newest that is NOT "collapsed".
//
// Every dashboard, report and selector defaults to the latest scan. A degenerate small scan as the
// newest (the fallback-sweep fingerprint: a 1-file local-corpus scan landing on top of a real
// estate) makes the whole app show a shrunken estate — the exact condition scripts/monitor.py's
// "newest scan is full-size" probe fails on. This picks the newest scan that is NOT collapsed and
// falls back to the most recent full-size one, so the app's default and the production probe agree
// on what "collapsed" means (ratio 0.5 over the last 10 siblings — mirror those constants).
//
// Conservative by construction: it only skips a scan that is < half the biggest of its recent
// siblings, so a legitimately small estate (no larger sibling to compare against) is never hidden —
// the newest still wins.
const COLLAPSE_RATIO = 0.5
const COLLAPSE_WINDOW = 10

const _files = (s) => (s && Number.isFinite(s.files) ? s.files : 0)

export function pickDefaultScan(scans, { ratio = COLLAPSE_RATIO, window = COLLAPSE_WINDOW } = {}) {
  if (!Array.isArray(scans) || scans.length === 0) return null
  const recent = scans.slice(0, window)                  // newest-first, as list_scans returns them
  const biggest = Math.max(...recent.map(_files))
  if (!biggest) return scans[0]                          // no sizes to compare on — keep the newest
  const floor = biggest * ratio
  // Among candidates that pass the collapse check, prefer a published scan (enumeration
  // verified complete, not a suspicious zero) over an unverified one.
  const aboveFloor = recent.filter((s) => _files(s) >= floor)
  if (!aboveFloor.length) return scans[0]
  return aboveFloor.find((s) => s.published_at) || aboveFloor[0]
}
