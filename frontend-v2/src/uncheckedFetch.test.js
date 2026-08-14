import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// `fetch` rejects only on a network failure. A 401, a 403, a 404 — all perfectly good responses,
// so `.json()` / `.arrayBuffer()` succeed on the error body and the code carries on as though the
// call worked. That single shape produced four separate defects in #171 and #174, and a sweep
// found more of it.
//
// Fixed here:
//
//   Three copies of the Google userinfo call. A 401 handed back Google's error body, so SignIn
//   called onSignedIn({ id: undefined }), Integrations connected the account as '', and
//   GoogleDrive cached the error object under 'gd_user' and read it back on reload. Identity is
//   the tenant key the estate scopes by. Every one of those sites ALREADY had a correct error
//   path — SignIn even renders "Could not retrieve your Google profile" — and none ever ran.
//
//   downloadUpdatedPptx. An SPA host answers a missing asset with index.html and a 200, so
//   .arrayBuffer() succeeded on HTML and the customer downloaded it named .pptx. Its sibling
//   downloadUpdatedXlsx was safe only by accident, because JSZip rejects non-zip input.
//
// COMMENT-STRIPPED, and that is not incidental. The block you are reading quotes the old code;
// so does the source these assertions run against. A substring match would find the prose and
// pass with the defect restored. That has now happened three times in this repo — twice in
// tests that were written to catch exactly what they then failed to catch.

const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

describe('googleUserInfo', () => {
  it('checks the response before trusting the body', () => {
    expect(code('googleIdentity.js')).toMatch(/if \(!r\.ok\) \{/)
  })

  it('rejects a 200 that carries no email', () => {
    // The same failure wearing a success code. email is the field every caller keys on, so
    // rejecting here means no caller has to remember to.
    expect(code('googleIdentity.js')).toMatch(/if \(!me\?\.email\) throw/)
  })

  it('says the token is the problem, not the person', () => {
    // "Try again" is the wrong instruction when the fix is re-consenting with the profile scope.
    expect(code('googleIdentity.js')).toContain('profile scope')
  })
})

describe('every userinfo caller goes through it', () => {
  for (const file of ['SignIn.jsx', 'Integrations.jsx', 'GoogleDrive.jsx']) {
    it(`${file} calls the helper and fetches nothing itself`, () => {
      const s = code(file)
      expect(s).toMatch(/await googleUserInfo\(/)
      expect(s).toContain("from './googleIdentity.js'")
      expect(s, 'a direct userinfo fetch is back').not.toContain('oauth2/v2/userinfo')
    })
  }

  it('SignIn surfaces the reason rather than a generic retry', () => {
    expect(code('SignIn.jsx')).toMatch(/setErr\(e\?\.message/)
  })

  it('Integrations no longer connects an account as the empty string', () => {
    const s = code('Integrations.jsx')
    expect(s).not.toContain('.catch(() => ({}))')
    expect(s).toMatch(/setGdError\(e\?\.message/)
  })
})

describe('the deliverable downloads', () => {
  it('check the response AND the bytes', () => {
    // .ok alone is not enough here: the failure mode is a 200 of HTML from a catch-all rewrite.
    // Both deliverables are ZIPs, so the local file header is format-level proof.
    const s = code('exportDeliverables.js')
    expect(s).toMatch(/if \(!r\.ok\) throw new Error\(`Could not load/)
    expect(s).toMatch(/sig\[0\] !== 0x50 \|\| sig\[1\] !== 0x4b/)
  })

  it('both go through loadAsset — the pptx one is the whole point', () => {
    const s = code('exportDeliverables.js')
    expect(s).toMatch(/await loadAsset\('\/exports\/method-deck\.pptx'\)/)
    expect(s).toMatch(/JSZip\.loadAsync\(await loadAsset\(url\)\)/)
    expect(s, 'an unguarded arrayBuffer fetch is back').not.toMatch(/await \(await fetch\([^)]*\)\)\.arrayBuffer\(\)/)
  })
})

describe('both SPAs', () => {
  it('carry the same googleIdentity.js and exportDeliverables.js', () => {
    for (const f of ['googleIdentity.js', 'exportDeliverables.js']) {
      const a = readFileSync(join(HERE, f), 'utf8')
      const b = readFileSync(join(HERE, '..', '..', 'frontend', 'src', f), 'utf8')
      expect(a, `${f} has diverged between the two SPAs`).toBe(b)
    }
  })
})
