import { currentCanonicalStage } from './canonicalStageCard.js'
const ORDER = { discover: 0, assess: 1, remediate: 2, release: 3 }

/** Earlier stages remain browseable once the same durable workflow advances. */
export function priorStageResults(lineage, scanId, { awaitingLineage = false } = {}) {
  if (scanId && awaitingLineage) return { discover: true, assess: true, remediate: true, release: false }
  const current = lineage?.scan_id === scanId && scanId ? currentCanonicalStage(lineage) : null
  const furthest = ORDER[current?.stage] ?? -1
  return Object.fromEntries(Object.entries(ORDER).map(([stage, order]) => [stage, order < furthest]))
}

/** Call-time guard also rejects events captured before a downstream stage arrived. */
export function guardStageAction(ref, stage, action) {
  const scanId = ref.current?.scanId
  return (...args) => {
    if (!ref.current?.[stage] && (!scanId || scanId === ref.current?.scanId)) return action?.(...args)
  }
}
