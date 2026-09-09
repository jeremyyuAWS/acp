import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { hasCorrectedCopy, deliveryIsCurrent, releaseReadiness, canSelectRelease, releaseSourceState } from './releaseClarityModel.js'
const corrected = { file: 'a.pdf', compliant: 1, remediated_at: '2026-09-01' }
describe('Release corrected-copy contract', () => {
  it('matches the existing backend eligibility boundary without inferring from score', () => {
    const routes = readFileSync('../api/routes/scans.py', 'utf8')
    expect(routes).toContain('release_ready(row, allow_remaining_issues)')
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

it('prefers exact artifact identity over timestamps when the server provides it', () => {
  const file = { ...corrected, corrected_sha256: 'b'.repeat(64), remediated_at: '2026-09-03' }
  expect(deliveryIsCurrent(file, { status: 'published', published_at: '2026-09-04', artifact_digest: `sha256:${'a'.repeat(64)}` })).toBe(false)
  expect(deliveryIsCurrent(file, { status: 'published', published_at: '2026-09-02', artifact_digest: `sha256:${'b'.repeat(64)}` })).toBe(true)
})

it('partial release preserves source and artifact gates while allowing unresolved findings explicitly', () => {
  const file = { file: 'partial.docx', compliant: false, corrected_sha256: 'digest', remediated_at: '2026-09-09' }
  expect(releaseReadiness(file).status).toBe('attention')
  expect(releaseReadiness(file, { allowRemainingIssues: true, pending: { 'partial.docx': 3 } }).label).toBe('Ready with remaining issues')
  expect(releaseReadiness({ ...file, corrected_sha256: null }, { allowRemainingIssues: true }).status).toBe('attention')
  expect(releaseReadiness(file, { allowRemainingIssues: true, sourceState: () => 'stale' }).status).toBe('changed')
  expect(releaseReadiness(file, { allowRemainingIssues: true, blockers: { 'partial.docx': 'Write incomplete' } }).status).toBe('attention')
})
