import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const api = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'api.js'), 'utf8')

describe('capacity schedule mutations are bounded', () => {
  it('bounds save, validation, override creation, and override cancellation', () => {
    const section = api.slice(api.indexOf('export const putCapacitySchedule'),
      api.indexOf('export const getCapacityPolicy'))
    expect(section.match(/AbortSignal\.timeout\(CAPACITY_MUTATION_TIMEOUT_MS\)/g)).toHaveLength(4)
  })
})
