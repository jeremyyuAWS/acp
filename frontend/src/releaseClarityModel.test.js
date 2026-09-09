import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { hasCorrectedCopy, deliveryIsCurrent, releaseReadiness, canSelectRelease, releaseSourceState } from './releaseClarityModel.js'
const corrected = { file: 'a.pdf', compliant: 1, remediated_at: '2026-09-01' }
describe('Release corrected-copy contract', () => {
  it('matches the existing backend eligibility boundary without inferring from score', () => {
    const routes = readFileSync('../api/routes/scans.py', 'utf8')
    expect(routes).toContain('if not record or not record.get("compliant") or not record.get("remediated_at"):')
    expect(hasCorrectedCopy(corrected)).toBe(true)
    for (const file of [{ score: 100 }, { compliant: true }, { compliant: null, remediated_at: '2026-09-01' }, { compliant: 'false', remediated_at: '2026-09-01' }]) {
      expect(hasCorrectedCopy(file)).toBe(false)
      expect(releaseReadiness(file).label).toBe('Needs attention')
    }
  })
  it('does not select queued, running, unknown, changed, unreachable or unapproved files', () => {
    for (const status of ['queued', 'running']) {
      const state = releaseReadiness(corrected, { results: { 'a.pdf': { status } } })
      expect(state.label).toBe('Delivering'); expect(canSelectRelease(state)).toBe(false)
    }
    for (const source of ['stale', 'unavailable']) expect(canSelectRelease(releaseReadiness(corrected, { sourceState: () => source }))).toBe(false)
    expect(canSelectRelease(releaseReadiness(corrected, { pending: { 'a.pdf': 1 } }))).toBe(false)
  })
  it('requires delivery evidence for the current correction, never a mirror URL', () => {
    expect(deliveryIsCurrent({ ...corrected, drive_write_url: 'https://example.test/mirror' })).toBe(false)
    expect(deliveryIsCurrent(corrected, { status: 'published', published_at: '2026-08-31' })).toBe(false)
    expect(deliveryIsCurrent(corrected, { status: 'published', published_at: '2026-09-02' })).toBe(true)
    expect(deliveryIsCurrent(corrected, { status: 'failed' }, { 'a.pdf': true })).toBe(false)
    expect(deliveryIsCurrent({ ...corrected, published_at: 'unknown' })).toBe(false)
  })
})

it('preserves source errors and drift under lifecycle overlays', () => {
  expect(releaseSourceState({ state: 'conflict' })).toBe('stale')
  expect(releaseSourceState({ state: 'publish_pending', error: 'forbidden' })).toBe('unavailable')
  expect(releaseSourceState({ state: 'acp_newer', baseline: '2026-09-01', current: '2026-09-02' })).toBe('stale')
  expect(releaseSourceState({ state: 'publish_pending', baseline: '2026-09-01', current: '2026-09-01' })).toBe('publish_pending')
})
