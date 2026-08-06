import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { SEVERITY_WEIGHTS } from './RiskScore.jsx'

// The "Why {score}?" breakdown only builds trust if its arithmetic matches the backend rubric.
// SEVERITY_WEIGHTS mirrors config/rubric.default.json → severity_weights; pin them together so a
// change to one without the other fails CI instead of silently showing a score that doesn't add up.
describe('RiskScore score-explanation weights', () => {
  const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
  const cfg = JSON.parse(readFileSync(join(repo, 'config', 'rubric.default.json'), 'utf8'))

  it('match the backend rubric severity_weights exactly', () => {
    const w = cfg.severity_weights
    expect(SEVERITY_WEIGHTS.critical).toBe(w.CRITICAL)
    expect(SEVERITY_WEIGHTS.serious).toBe(w.SERIOUS)
    expect(SEVERITY_WEIGHTS.moderate).toBe(w.MODERATE)
    expect(SEVERITY_WEIGHTS.minor).toBe(w.MINOR)
  })

  it('reconcile the example: 2 critical + 2 serious + 2 moderate → 100 − 96 = 4', () => {
    const penalty = 2 * SEVERITY_WEIGHTS.critical + 2 * SEVERITY_WEIGHTS.serious + 2 * SEVERITY_WEIGHTS.moderate
    expect(100 - penalty).toBe(4)
  })
})
