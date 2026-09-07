import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const monitor = readFileSync(join(here, 'Monitor.jsx'), 'utf8')
const api = readFileSync(join(here, 'api.js'), 'utf8')

describe('scheduled scan operations', () => {
  it('sends the backend policy contract and tolerates legacy nested responses', () => {
    for (const field of ['source_scope', 'include_ids', 'exclude_ids', 'notification_policy', 'queue_policy', 'defer_when_interactive', 'max_queue_depth']) {
      expect(monitor).toContain(field)
    }
    expect(monitor).toMatch(/value\.scope \|\| value\.source_scope/)
    expect(monitor).toMatch(/value\.execution \|\| value\.queue_policy/)
  })

  it('offers source and include/exclude scope controls', () => {
    expect(monitor).toContain('What to scan')
    expect(monitor).toContain('Connected source')
    expect(monitor).toContain('Include')
    expect(monitor).toContain('Exclude')
    expect(api).toContain('export const getSchedule')
  })

  it('offers quiet notification and queue-aware performance controls', () => {
    expect(monitor).toContain('When to notify me')
    expect(monitor).toContain('Successful scans with no changes stay quiet.')
    expect(monitor).toContain('Wait if interactive work is busy')
    expect(monitor).toContain('Warm workers before the scan')
  })

  it('makes admin limits, run history, and reliability visible', () => {
    expect(monitor).toContain('Organization guardrails')
    expect(monitor).toContain('Recent scheduled scans')
    expect(monitor).toContain('Schedule reliability')
    for (const label of ['On time', 'Missed runs', 'Overlaps prevented', 'Catch-up runs']) expect(monitor).toContain(label)
    expect(monitor).toContain('aria-labelledby="schedule-history"')
  })
})
