import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Source-level, matching the repo's other Settings/Users pins (usersTab.test.js): a full mount of
// Settings needs the whole admin/store/auth stack, and the load-bearing facts here are wiring — the
// endpoint, the dark-until-configured gate, and that the auto-add is reflected in the list.
const here = dirname(fileURLToPath(import.meta.url))
const settings = readFileSync(join(here, 'Settings.jsx'), 'utf8')
const api = readFileSync(join(here, 'api.js'), 'utf8')

describe('tester guest-invite (ADR 0033)', () => {
  it('api.js posts the invite to /admin/invite', () => {
    expect(api).toMatch(/export const inviteTester = \(email\)/)
    expect(api).toMatch(/inviteTester[\s\S]{0,220}\/admin\/invite/)
    expect(api).toMatch(/inviteTester[\s\S]{0,220}method: 'POST'/)
  })

  it('Settings imports inviteTester and hides the UI until the credential is configured', () => {
    expect(settings).toMatch(/import \{[^}]*inviteTester[^}]*\} from '\.\/api\.js'/)
    expect(settings).toMatch(/invite_enabled/)        // read from the allowlist payload
    expect(settings).toMatch(/\{inviteEnabled && \(/) // the block renders only when enabled → ships dark
  })

  it('inviting calls the endpoint and reflects the auto-add back into the visible list', () => {
    expect(settings).toMatch(/inviteTester\(e\)/)
    expect(settings).toMatch(/setEmails\(d\.emails \|\| \[\]\)/)  // the endpoint's updated list shows immediately
  })
})
