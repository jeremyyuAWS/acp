import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// #156 and #157 shipped GET /sharepoint/sites and POST /sharepoint/upload, and neither had a
// client — zero references in api.js. Site enumeration and server-side write-back existed and
// no person could invoke them. These are the clients, and these pin the three things about them
// that are easy to get wrong and invisible when wrong.

const HERE = dirname(fileURLToPath(import.meta.url))
const API = () => readFileSync(join(HERE, 'api.js'), 'utf8')

describe('the SharePoint routes have clients', () => {
  it('all three exist', () => {
    const s = API()
    expect(s).toMatch(/export const listSharePointSites/)
    expect(s).toMatch(/export const listSharePointDrives/)
    expect(s).toMatch(/export const uploadToSharePoint/)
  })

  it('they hit the routes that actually shipped', () => {
    const s = API()
    expect(s).toContain('/sharepoint/sites?q=')
    expect(s).toMatch(/\/sharepoint\/sites\/\$\{siteId\}\/drives/)
    expect(s).toContain('/sharepoint/upload')
  })

  it('the token rides on headers(), the same one the scan path uses', () => {
    // The route reads X-SP-Token, which headers() already sends. Rolling a second header here
    // would let the picker list sites the SCAN token cannot read — the exact dishonesty
    // api/routes/sharepoint.py was written to avoid.
    const s = API()
    const block = s.slice(s.indexOf('listSharePointSites'), s.indexOf('queueHitlVerify'))
    expect(block).toMatch(/headers: headers\(\)/)
    expect(block).not.toMatch(/'X-SP-Token'/)
  })
})

describe('the site id is not encoded', () => {
  it('drives are fetched with the raw compound id', () => {
    // A Graph site id is `contoso.sharepoint.com,<guid>,<guid>`. The route declares
    // {site_id:path} precisely so the commas survive; encodeURIComponent would send %2C and the
    // server would look up a site that does not exist, with a 404 that names nothing useful.
    const s = API()
    const line = s.split('\n').find((l) => l.includes('/sharepoint/sites/${siteId}/drives'))
    expect(line, 'the drives client is missing').toBeTruthy()
    expect(line).not.toMatch(/encodeURIComponent\(siteId\)/)
  })
})

describe('the upload refuses to guess', () => {
  it('rejects without a drive id rather than defaulting', () => {
    // Writing to the wrong drive does not error — it SUCCEEDS, into somebody else's library,
    // because item ids are unique only within a drive. A default here would be silent
    // cross-library writes.
    const s = API()
    expect(s).toMatch(/if \(!driveId\)/)
    expect(s).toMatch(/only unique within its drive/)
  })

  it('does not set Content-Type on the multipart body', () => {
    // The browser sets multipart/form-data WITH the boundary. Setting it by hand omits the
    // boundary and the server cannot parse the body — a failure that reads as a server bug.
    const s = API()
    const block = s.slice(s.indexOf('uploadToSharePoint'), s.indexOf('queueHitlVerify'))
    expect(block).toMatch(/new FormData\(\)/)
    expect(block).not.toMatch(/'Content-Type':/)
  })
})

describe('SIM does not fabricate a tenant', () => {
  it('all three reject in SIM with a reason', () => {
    // A fake site list is the one thing a demo viewer could act on and find missing.
    // "Policies (9,870 files)" that does not exist is worse than an empty state that explains
    // itself — and unlike the estate view, there is no real synthetic corpus to derive from.
    const s = API()
    expect(s).toMatch(/SIM build — no SharePoint tenant to enumerate/)
    // Three clients, three call sites. Counting >= 4 was my own off-by-one: the definition
    // reads `const SP_SIM = () =>` and does not match /SP_SIM\(\)/, so it never contributed.
    const block = s.slice(s.indexOf('const SP_SIM'), s.indexOf('queueHitlVerify'))
    expect((block.match(/SP_SIM\(\)/g) || []).length).toBe(3)
  })
})
