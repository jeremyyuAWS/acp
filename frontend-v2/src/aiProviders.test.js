import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('AI Providers settings — the key is never entered in the UI (ADR 0019 §6)', () => {
  it('the API helpers target /ai/providers and send only a secret reference', () => {
    const api = read('api.js')
    expect(api).toMatch(/getAiProviders\s*=/)
    expect(api).toMatch(/putAiProvider\s*=/)
    expect(api).toMatch(/\/ai\/providers/)
    // putAiProvider must forward key_secret_ref, never a raw key/api_key field
    const put = api.slice(api.indexOf('putAiProvider'))
    expect(put).toMatch(/key_secret_ref|JSON\.stringify\(patch\)/)
  })

  it('the panel sends key_secret_ref, never a key value, and states the key is not entered here', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/AIProvidersPanel/)
    // the payload built in save() carries key_secret_ref and no api_key/key field
    const save = s.slice(s.indexOf('putAiProvider({'), s.indexOf('putAiProvider({') + 400)
    expect(save).toMatch(/key_secret_ref:/)
    expect(save).not.toMatch(/\bapi_key\b/)
    expect(save).not.toMatch(/[^_]\bkey:/)          // no bare `key:` field in the payload
    // explicit user-facing guarantee + a present/absent indicator, never the value
    expect(s).toMatch(/key is never entered here/i)
    expect(s).toMatch(/key_present/)
    expect(s).toMatch(/reference name/i)
  })

  it('marks only the wired adapter as ready and keeps the rest config-only', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/ADAPTER_READY\s*=\s*new Set\(\['azure_openai'\]\)/)
    expect(s).toMatch(/adapter coming/i)
  })
})
