// Motion describes current work, never inferred progress or a completed finding.
export const MOTION_FRESH_MS = 60_000
const fresh = (at, now) => {
  const time = Date.parse(at || '')
  return Number.isFinite(time) && now - time >= -5_000 && now - time < MOTION_FRESH_MS
}
export function waterfallMotion(snapshot, view, { now = Date.now(), paused = false, error = false, selected } = {}) {
  const running = !paused && !snapshot.terminal && (snapshot.state === 'running' || (snapshot.state === 'needs_attention' && snapshot.also?.includes('running')))
    && fresh(snapshot.generated_at, now)
    && snapshot.progress?.lease_healthy === true
    && !snapshot.integrity?.affected?.some(key => ['documents', 'freshness'].includes(key))
  const documents = running && Number.isSafeInteger(snapshot.documents?.processing) ? snapshot.documents.processing : 0
  const ai = running && !error && view?.available === true && view.ai_enabled === true && fresh(view.generated_at, now)
    ? (view.stages || []).filter(stage => stage.active > 0 && [1, 2].includes(stage.tier)).map(stage => stage.tier === 1 ? 'first' : 'next') : []
  const verifying = running && (snapshot.active_attempts || []).some(attempt =>
    /verif|re-?check|validat/i.test(attempt.phase || '') && attempt.lease_valid === true
    && Date.parse(attempt.lease_expires_at || '') > now)
  const candidates = [...ai, ...(verifying ? ['verify'] : [])]
  return { documents, stage: candidates.includes(selected) ? selected : candidates[0] || null }
}
