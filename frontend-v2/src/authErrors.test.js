import { describe, it, expect } from 'vitest'
import { friendlyAuthError } from './authErrors.js'

// Sign-in is the first thing a user hits; a raw MSAL/AADSTS string there reads as "the app is
// broken." These pin that the common failures map to one actionable sentence, and that a raw
// AADSTS wall never becomes the primary message.
describe('friendlyAuthError', () => {
  it('a cancelled sign-in', () => {
    expect(friendlyAuthError({ errorCode: 'user_cancelled' })).toMatch(/cancelled/i)
  })
  it('a blocked pop-up says how to unblock it', () => {
    expect(friendlyAuthError({ errorCode: 'popup_window_error' })).toMatch(/pop-up/i)
  })
  it('a stuck interaction', () => {
    expect(friendlyAuthError({ errorCode: 'interaction_in_progress' })).toMatch(/still finishing/i)
  })
  it('wrong tenant (AADSTS50020) → use the ACP work account', () => {
    const m = friendlyAuthError({ errorMessage: "AADSTS50020: User account 'x' does not exist in tenant 'fgxlxj' and cannot access the application ..." })
    expect(m).toMatch(/work account provided for ACP/i)
    expect(m).not.toMatch(/cannot access the application/)      // the raw guts are hidden
  })
  it('wrong account (AADSTS700016) → use another account', () => {
    const m = friendlyAuthError({ errorMessage: 'AADSTS700016: Application ... was not found in the directory ...' })
    expect(m).toMatch(/different work account/i)
    expect(m).toMatch(/Use another account/i)
  })
  it('consent needed → ask your admin', () => {
    expect(friendlyAuthError({ errorMessage: 'AADSTS65001: The user or administrator has not consented ...' })).toMatch(/admin/i)
  })
  it('an unrecognised AADSTS keeps the code (useful to an admin)', () => {
    expect(friendlyAuthError({ errorMessage: 'AADSTS99999: brand new failure' })).toMatch(/AADSTS99999/)
  })
  it('a plain error passes through', () => {
    expect(friendlyAuthError({ message: 'network glitch' })).toBe('network glitch')
  })
})
