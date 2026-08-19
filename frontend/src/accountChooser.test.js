/**
 * Signing in must ASK which account, and refreshing must not.
 *
 * A browser with one signed-in Google session goes straight through on that account unless the
 * chooser is requested explicitly. That is right for a token refresh and wrong for a sign-in —
 * sign-in is the one moment the user is choosing who to be, and silently answering it for them
 * made "my personal Google Drive with my work Microsoft account" impossible without a second
 * Chrome profile. The same is true of MSAL's loginPopup and the single signed-in Entra account.
 *
 * THE ASYMMETRY IS THE POINT, and it is what these tests pin:
 *
 *   · SignIn.jsx / msalClient.js  ->  prompt: 'select_account'   (who am I?)
 *   · driveAuth.refreshDriveToken ->  prompt: ''                 (keep this scan alive)
 *
 * Putting a chooser in the refresh path would interrupt someone mid-scan with a modal, and worse,
 * re-picking there would swap the Drive underneath a scan already listing files — the count would
 * change sources halfway with nothing recording it. Making the refresh silent is deliberate, so a
 * later tidy-up that "makes them consistent" has to fail a test rather than look like clean-up.
 *
 * Asserted against source text rather than by driving GIS/MSAL: both are third-party globals
 * loaded from a script tag, and a stub deep enough to exercise them would be asserting on the
 * stub. The repo uses the same technique for its other wiring guards.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('sign-in asks which account', () => {
  it('Google requests the chooser', () => {
    const src = read('SignIn.jsx')
    expect(src).toMatch(/requestAccessToken\(\s*\{[^}]*prompt:\s*'select_account'/)
  })

  it('Microsoft requests the chooser', () => {
    const src = read('msalClient.js')
    expect(src).toMatch(/loginPopup\(\s*\{[^}]*prompt:\s*'select_account'/)
  })

  it('the header offers a switch-account control', () => {
    expect(read('App.jsx')).toContain('switch account')
  })
})

describe('refreshing does not', () => {
  it('the Drive token refresh stays silent', () => {
    // A chooser here would interrupt a running scan, and re-picking would swap the Drive
    // underneath it. Kept as its own assertion so "make these consistent" fails loudly.
    const src = read('driveAuth.js')
    expect(src).toMatch(/requestAccessToken\(\s*\{\s*prompt:\s*''\s*\}\s*\)/)
    expect(src).not.toContain('select_account')
  })
})

describe('switching account is a full teardown', () => {
  // The ACP identity is the Authorization bearer, and api/app.py stamps user_email from it —
  // which is what per-user data isolation keys on. Re-minting only the Drive token would leave
  // the user signed in as one account while reading another's Drive, with scans owned by the
  // first. So the control must clear tokens AND reload, exactly as sign out does.
  const src = read('App.jsx')
  const block = src.slice(src.indexOf('switch account') - 900, src.indexOf('switch account') + 60)

  it('clears every token', () => {
    expect(block).toContain('clearAllTokens()')
  })

  it('reloads rather than mutating state in place', () => {
    expect(block).toContain('window.location.reload()')
  })
})
