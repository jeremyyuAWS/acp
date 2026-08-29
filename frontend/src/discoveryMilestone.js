// Which round-thousand milestone `filesFound` has just reached, for the one class of live-count
// update worth telling a screen-reader user about mid-discovery — see the design review: "Announce
// only meaningful milestones, such as worker assigned, 1,000 documents found, or Discovery
// complete." Every other tick of files/folders found stays silent (LiveCounter.jsx's own numbers
// are never wrapped in aria-live) — announcing every increment on a fast-moving count would bury
// the signal a screen-reader user actually wants under noise.

/**
 * @param filesFound  the current live count.
 * @param lastAnnounced  the highest threshold already announced (0 if none yet).
 * @returns the new threshold to announce (e.g. 1000, 2000, …), or null if `filesFound` hasn't
 *          crossed a new one since `lastAnnounced`.
 */
export function nextMilestone(filesFound, lastAnnounced) {
  if (filesFound == null || filesFound < 1000) return null
  const reached = Math.floor(filesFound / 1000) * 1000
  return reached > (lastAnnounced ?? 0) ? reached : null
}
