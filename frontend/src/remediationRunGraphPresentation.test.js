import { describe, expect, it } from 'vitest'
import { recordedRunGraphGroups } from './remediationRunGraphPresentation.js'
const step = (position, extra = {}) => ({ configured: true, position, step_id: ['primary', 'fallback_1', 'fallback_2'][position], enabled: true, provider: 'Provider', model: `Model ${position}`, attempt_ids: [], ...extra })
const graph = extra => ({ contract_version: 'remediation-run-graph.v1', coverage: 'complete', chain_version: 1, steps: [], attempts: [], ...extra })
const attempt = (id, purpose = 'fallback', extra = {}) => ({ attempt_id: id, purpose, provider: 'Actual provider', model: 'Actual model', ...extra })

describe('recorded run graph presentation', () => {
  it.each([0, 1, 2])('renders %i configured fallback positions in validated order', fallbacks => {
    const groups = recordedRunGraphGroups(graph({ steps: Array.from({ length: fallbacks + 1 }, (_, index) => step(index)).reverse() }))
    expect(groups.map(group => group[0].stepId)).toEqual(['primary', 'fallback_1', 'fallback_2'].slice(0, fallbacks + 1))
    expect(groups.flat().every(fact => fact.identityKind === 'configured' && !fact.canAnimate && fact.in_flight === false)).toBe(true)
    expect(groups[0][0].detail).toContain('dispatch not recorded')
    expect(groups[0][0].provider).toBe('Provider')
  })
  it('omits disabled unused options but retains explicitly linked attempts without retry nodes', () => {
    const a = attempt('a', 'fallback', { step_id: 'fallback_1', generation_position: 1, lineage_available: true })
    const b = { ...a, attempt_id: 'b' }
    const groups = recordedRunGraphGroups(graph({ steps: [step(0), step(1, { enabled: false, attempt_ids: ['a', 'b'] }), step(2, { enabled: false })], attempts: [a, b, b] }))
    expect(groups).toHaveLength(2)
    expect(groups[1][0].value).toBe(2)
    expect(groups[1][0].attemptIds).toEqual(['a', 'b'])
    expect(groups[1][0].identityKind).toBe('configured')
  })
  it('keeps legacy fallback models parallel without inferring levels from timestamps or names', () => {
    const attempts = [attempt('z', 'fallback', { model: 'Z model', created_at: 'later' }), attempt('a', 'fallback', { model: 'A model', created_at: 'earlier' })]
    const groups = recordedRunGraphGroups(graph({ coverage: 'partial', attempts }))
    expect(groups).toHaveLength(1)
    expect(groups[0]).toHaveLength(2)
    expect(groups[0].every(fact => fact.stepId === null && fact.role === 'Recorded fallback' && fact.detail.includes('sequence not recorded'))).toBe(true)
    const reversed = recordedRunGraphGroups(graph({ attempts: [...attempts].reverse() })).flat()
    expect(reversed.map(fact => fact.id).sort()).toEqual(groups.flat().map(fact => fact.id).sort())
  })
  it('distinguishes review and final review even for the same model', () => {
    const facts = recordedRunGraphGroups(graph({ attempts: [attempt('d', 'draft'), attempt('r', 'review'), attempt('f', 'final_review')] })).flat()
    expect(facts.map(fact => fact.role)).toEqual(['Recorded draft', 'AI review', 'Final AI review'])
    expect(new Set(facts.map(fact => fact.id)).size).toBe(3)
    expect(facts[1].stage).toBe('review')
    expect(facts[2].purpose).toBe('final_review')
  })
  it('never treats historical dispatch as current activity and handles missing identities', () => {
    const fact = recordedRunGraphGroups(graph({ attempts: [attempt('a', 'unknown', { provider: null, model: null, in_flight: true, status: 'started', spending_state: 'dispatched' })] }))[0][0]
    expect(fact.title).toBe('Model not recorded')
    expect(fact.provider).toBeNull()
    expect(fact.canAnimate).toBe(false)
    expect(fact.in_flight).toBe(false)
    expect(fact.role).toBe('Other recorded AI activity')
  })
  it('rejects unavailable contracts and invalid configured positions', () => {
    expect(recordedRunGraphGroups(null)).toBeNull()
    expect(recordedRunGraphGroups(graph({ contract_version: 'future' }))).toBeNull()
    expect(recordedRunGraphGroups(graph({ coverage: 'unavailable' }))).toBeNull()
    expect(recordedRunGraphGroups(graph({ steps: [step(0, { position: '0' }), step(1), step(1), step(2, { position: 3 })] }))).toEqual([])
    expect(recordedRunGraphGroups(graph({ chain_version: 2, steps: [step(0)] }))).toEqual([])
  })
  it('preserves model IDs when retries or other models arrive', () => {
    const a = attempt('a')
    const original = recordedRunGraphGroups(graph({ attempts: [a] }))[0][0]
    const updated = recordedRunGraphGroups(graph({ attempts: [a, { ...a, attempt_id: 'retry' }, attempt('other', 'fallback', { model: 'New model' })] }))[0]
    expect(updated[0].id).toBe(original.id)
    expect(updated[0].value).toBe(2)
    expect(updated).toHaveLength(2)
  })
})
