import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { timezoneBadge } from './userTimezone.js'

describe('account timezone badge', () => {
  it.each([
    ['America/Los_Angeles', 'PT', 'US Pacific'],
    ['America/Denver', 'MT', 'US Mountain'],
    ['America/Chicago', 'CT', 'US Central'],
    ['America/New_York', 'ET', 'US Eastern'],
    ['Asia/Kolkata', 'IST', 'India'],
    ['UTC', 'UTC', 'UTC'],
  ])('uses a stable readable label for %s', (zone, short, name) => {
    expect(timezoneBadge(zone)).toEqual({ short, name })
  })

  it('is wired beside the account name and reads the saved per-user setting', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    expect(app).toMatch(/getMyScope\(\)[^]*setUserTimezone/)
    expect(app).toMatch(/me\.name \|\| me\.email[^]*Timezone: \$\{timezoneBadge\(userTimezone\)\.name\}/)
    expect(app).toMatch(/Release folder timezone: \$\{userTimezone\}/)
  })
})
