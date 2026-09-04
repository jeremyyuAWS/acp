import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// The Key Vault write-through is the ONE place this product accepts a key value. These assertions
// are the UI half of the guarantee the backend tests pin (tests/test_provider_key_vault_write_
// through.py): the field only exists where a vault can actually take the value, it is write-only,
// and the value never rides along with the ordinary config save.
describe('AI provider key write-through — the field is gated, write-only, and separate', () => {
  it('the API helper posts the value to the per-provider secret route and nowhere else', () => {
    const api = read('api.js')
    expect(api).toMatch(/putAiProviderSecret\s*=/)
    const fn = api.slice(api.indexOf('putAiProviderSecret'))
    expect(fn).toMatch(/\/ai\/providers\/\$\{encodeURIComponent\(provider\)\}\/secret/)
    expect(fn).toMatch(/method: 'POST'/)
    // The non-secret config PUT must not learn about the value. Asserted on the request BODY
    // rather than on the whole slice: the slice includes the comment explaining the split, and
    // "value" appears in English there — a first draft of this test failed on its own prose.
    const put = api.slice(api.indexOf('putAiProvider ='), api.indexOf('putAiProviderSecret'))
    expect(put).toMatch(/body: JSON\.stringify\(patch\)/)
    expect(put).not.toMatch(/value:/)
  })

  it('the input only renders where the deployment can store a key', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/secret_write/)                       // read from GET /ai/providers
    expect(s).toMatch(/secretWrite\.available\s*&&/)        // and it gates the field
  })

  it('the input is write-only: never prefilled from the server, cleared after every attempt', () => {
    const s = read('Settings.jsx')
    const panel = s.slice(s.indexOf('secretWrite.available &&'), s.indexOf('secretWrite.available &&') + 900)
    expect(panel).toMatch(/type="password"/)
    expect(panel).toMatch(/autoComplete="off"/)
    // value comes from local keyDraft state, never from a row the server sent
    expect(panel).toMatch(/value=\{keyDraft\[row\.provider\] \|\| ''\}/)
    expect(panel).not.toMatch(/row\.key|field\(row/)
    // cleared on BOTH paths — a live credential must not sit in a form after a failure either
    const handler = s.slice(s.indexOf('const saveKey ='), s.indexOf('const saveKey =') + 900)
    expect((handler.match(/setKeyDraft\(\(k\) => \(\{ \.\.\.k, \[row\.provider\]: '' \}\)\)/g) || []).length)
      .toBeGreaterThanOrEqual(2)
  })

  it('the key never rides along with the non-secret config save', () => {
    const s = read('Settings.jsx')
    const save = s.slice(s.indexOf('putAiProvider({'), s.indexOf('putAiProvider({') + 400)
    expect(save).not.toMatch(/keyDraft|value:/)
  })
})
