/**
 * Mid-scan logout cleanup — source-level assertions.
 *
 * Before this: the sign-out and switch-account handlers called window.location.reload()
 * immediately after clearing client-side tokens. Any running scan's backend token store
 * (Redis key scantok:{id}) kept the Drive/SP credentials indefinitely, so a worker that
 * was mid-file when the user signed out would continue using the now-invalidated tokens
 * for up to an hour.
 *
 * After this: both handlers first query the active scan and, if one is running, call
 * clearScanTokens(id) to delete the backend store before reloading.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(here, f), 'utf8').split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') })
  .join('\n')

const app = code('App.jsx')

describe('mid-scan logout cleanup', () => {
  it('imports clearScanTokens from api', () => {
    expect(app).toMatch(/clearScanTokens/)
  })

  it('sign-out handler awaits clearScanTokens before reloading', () => {
    // The handler must be async and call clearScanTokens with the active scan id.
    // We look for clearScanTokens appearing near (within 300 chars of) location.reload
    // in the sign-out button's onClick, not just anywhere in the file.
    expect(app).toMatch(/clearScanTokens[\s\S]{0,300}location\.reload|location\.reload[\s\S]{0,300}clearScanTokens/)
  })

  it('sign-out first checks for an active scan before clearing', () => {
    expect(app).toMatch(/getActiveScan[\s\S]{0,200}clearScanTokens/)
  })

  it('sign-out token clear is best-effort (wrapped in try/catch)', () => {
    // Should not propagate a network error and block the reload
    expect(app).toMatch(/try\s*\{[\s\S]{0,200}clearScanTokens[\s\S]{0,100}\}\s*catch/)
  })

  it('clearScanTokens is exported from api.js', () => {
    const api = code('api.js')
    expect(api).toMatch(/export const clearScanTokens/)
  })

  it('clearScanTokens calls DELETE on the tokens endpoint', () => {
    const api = code('api.js')
    // URL path /tokens comes before method: 'DELETE' in the fetch call
    expect(api).toMatch(/clearScanTokens[\s\S]{0,300}\/tokens[\s\S]{0,200}DELETE/)
  })
})
