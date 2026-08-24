/**
 * Token-refresh failure banner — source-level assertions.
 *
 * Before this: both the Drive and SharePoint keep-alive useEffects swallowed every error
 * silently, so a user whose MSAL/GIS session expired mid-scan had no indication — files
 * simply stopped being found, with no message and no path to recovery.
 *
 * After this: the catch branches surface a dismissable amber banner (role="alert") below
 * the header, and a successful refresh clears it so it doesn't outlive the problem.
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

describe('token-refresh failure surfaces a dismissable banner', () => {
  it('App tracks a tokenRefreshError state', () => {
    expect(app).toMatch(/tokenRefreshError/)
    expect(app).toMatch(/setTokenRefreshError/)
  })

  it('Drive keep-alive catch sets the error instead of swallowing it', () => {
    // The old shape was: catch { /* best-effort keep-alive */ }
    // It must now call setTokenRefreshError with a message.
    expect(app).not.toMatch(/refreshScanDriveToken[\s\S]{0,300}catch\s*\{\s*\/\*/)
    expect(app).toMatch(/refreshScanDriveToken[\s\S]{0,400}setTokenRefreshError\(/)
  })

  it('SP keep-alive catch sets the error instead of swallowing it', () => {
    expect(app).not.toMatch(/refreshScanSPToken[\s\S]{0,300}catch\s*\{\s*\/\*/)
    expect(app).toMatch(/refreshScanSPToken[\s\S]{0,400}setTokenRefreshError\(/)
  })

  it('a successful Drive refresh clears the error so it cannot outlive the problem', () => {
    expect(app).toMatch(/refreshScanDriveToken[\s\S]{0,300}setTokenRefreshError\(null\)/)
  })

  it('a successful SP refresh clears the error so it cannot outlive the problem', () => {
    expect(app).toMatch(/refreshScanSPToken[\s\S]{0,300}setTokenRefreshError\(null\)/)
  })

  it('the Drive error message names the service and tells the user what to do', () => {
    expect(app).toMatch(/Drive.*session.*expired|expired.*Drive.*session/i)
    expect(app).toMatch(/Reconnect|re-sign|sign.?in/i)
  })

  it('the SP error message names the service and tells the user what to do', () => {
    expect(app).toMatch(/SharePoint.*session.*expired|expired.*SharePoint.*session/i)
    expect(app).toMatch(/Re-sign|sign.?in/i)
  })

  it('renders the banner with role="alert" so screen readers announce it', () => {
    expect(app).toMatch(/role="alert"[\s\S]{0,500}tokenRefreshError|tokenRefreshError[\s\S]{0,500}role="alert"/)
  })

  it('provides a dismiss button that clears the error', () => {
    expect(app).toMatch(/setTokenRefreshError\(null\)[\s\S]{0,200}aria-label|aria-label[\s\S]{0,200}setTokenRefreshError\(null\)/)
  })
})
