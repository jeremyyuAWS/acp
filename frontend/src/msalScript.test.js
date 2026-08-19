import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const INDEX = readFileSync(join(HERE, '..', 'index.html'), 'utf8')

// SignIn.jsx loads MSAL as a global <script> and calls `new window.msal.PublicClientApplication()`
// then `await instance.initialize()`. `initialize()` is an MSAL v3 API — it does not exist in v2.
// So the script tag MUST load a v3 build, and it must load it from a CDN that actually publishes v3.
//
// The regression this guards (shipped, caused "Microsoft sign-in isn't ready yet — please refresh"
// for every user): the tag pointed at https://alcdn.msauth.net/browser/3.26.1/... — Microsoft's own
// CDN stops publishing at v2.38.1, so that v3 URL 404s, window.msal never loads, and the guard in
// SignIn.jsx fires forever. A green `vite build` does NOT catch this: the URL is a runtime fetch.
describe('the MSAL script tag loads a v3 build the button can actually use', () => {
  const tag = (INDEX.match(/<script[^>]*msal-browser[^>]*><\/script>/) || [])[0]

  it('is present exactly once', () => {
    const count = (INDEX.match(/msal-browser(\.min)?\.js/g) || []).length
    expect(count).toBe(1)
    expect(tag).toBeTruthy()
  })

  it('pins a v3 version — SignIn.jsx calls initialize(), which is v3-only', () => {
    const ver = (tag.match(/msal-browser@(\d+)\.|browser\/(\d+)\./) || [])
    const major = Number(ver[1] || ver[2])
    expect(major).toBeGreaterThanOrEqual(3)
  })

  it('is not served from alcdn.msauth.net, which never published v3 (the 404 that shipped)', () => {
    expect(tag).not.toMatch(/alcdn\.ms(ft)?auth\.net/)
  })

  it('carries an SRI hash + crossorigin — third-party auth JS on a PHI deployment is pinned by digest', () => {
    expect(tag).toMatch(/integrity="sha384-[A-Za-z0-9+/=]+"/)
    expect(tag).toMatch(/crossorigin/)
  })
})
