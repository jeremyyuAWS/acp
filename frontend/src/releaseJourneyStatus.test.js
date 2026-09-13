import { expect, it } from 'vitest'
import { releaseJourneyStatus as status } from './releaseJourneyStatus.js'
it('prioritizes a blocked delivery over busy or published counters', () => {
  expect(status({ error: { summary: 'Reconnect Microsoft' }, publishing: true }).detail).toBe('Reconnect Microsoft')
})
it('does not claim a partially published batch is finished', () => {
  expect(status({ publishedCount: 36, scopeCount: 147, automaticRelease: {}, readyCount: 111 }).label).toBe('Automatic publication queued')
  expect(status({ publishedCount: 147, scopeCount: 147 }).label).toBe('Batch published')
  expect(status({ publishedCount: 0, scopeCount: 0 }).label).not.toBe('Batch published')
})
it('keeps Q3 automation explicit while checking or publishing', () => {
  expect(status({ loading: true, automaticRelease: {} }).label).toBe('Checking release requirements')
  expect(status({ deliveringCount: 1, automaticRelease: {} }).label).toBe('Publishing corrected copies')
  expect(status({ automaticRelease: {} }).detail).toContain('no extra click')
})
