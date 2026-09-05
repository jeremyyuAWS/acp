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

  it('has a separate default-off assessment policy API and immutable-scan disclosure', () => {
    const api = read('api.js')
    const s = read('Settings.jsx')
    expect(api).toMatch(/getSecondOpinionPolicy\s*=/)
    expect(api).toMatch(/putSecondOpinionPolicy\s*=/)
    expect(api).toMatch(/\/ai\/second-opinion-policy/)
    expect(api).toMatch(/enabled: false/)
    expect(s).toMatch(/copied into each new scan/i)
    expect(s).toMatch(/already running/i)
    expect(s).toMatch(/1\.3\.5 Identify Input Purpose/)
  })

  it('the panel sends key_secret_ref, never a key value, and states the key is not entered here', () => {
    const s = read('Settings.jsx')
    expect(s).toMatch(/AIProvidersPanel/)
    // the payload built in save() carries key_secret_ref and no api_key/key field
    const save = s.slice(s.indexOf('putAiProvider({'), s.indexOf('putAiProvider({') + 400)
    expect(save).toMatch(/key_secret_ref:/)
    expect(save).not.toMatch(/\bapi_key\b/)
    expect(save).not.toMatch(/[^_]\bkey:/)          // no bare `key:` field in the payload
    // explicit user-facing guarantee + a present/absent indicator, never the value.
    //
    // This used to assert the sentence "the key is never entered here". That stopped being true
    // when the Key Vault write-through shipped — and the test kept passing anyway, because the
    // sentence still existed in a COMMENT above the panel. The load-bearing property was never
    // "no key is typed"; it is "no key value reaches the database", which the assertions above
    // (the config PUT carries only key_secret_ref) and below pin directly.
    expect(s).toMatch(/never reaches the database/i)
    expect(s).toMatch(/key_present/)
    expect(s).toMatch(/reference name/i)
  })

  it('marks exactly the providers the backend can build, and keeps the rest config-only', () => {
    // WHY THIS DERIVES THE LIST INSTEAD OF PINNING IT. This assertion used to read
    // `new Set(['azure_openai'])` — a literal copy of the state the UI was in. providers.py then
    // shipped working OpenAI and Anthropic adapters, wired into _adapter_for,
    // cloud_vision_provider() and active_vision_provider(), and this test went on passing while
    // the Settings page disabled the enable switch for both. The gate was the only thing between
    // a finished adapter and an admin, and the test that should have caught it was pinning the
    // gate rather than the fact behind it.
    //
    // So: read the backend's own table of which providers have an adapter, and require the UI to
    // agree. A new adapter now fails this until the UI offers it; a UI that offers one the backend
    // cannot build fails it too — the direction that would arm an escalation which silently never
    // fires. The backend enforces its own half independently (PUT /ai/providers refuses to enable
    // a provider it cannot build), so this is agreement between two guards, not one guard trusted
    // in two places.
    const s = read('Settings.jsx')
    const py = readFileSync(join(here, '..', '..', 'api', 'providers.py'), 'utf8')
    const table = py.slice(py.indexOf('_REQUIRED_FIELDS = {'), py.indexOf('def activation_readiness'))
    const backend = [...table.matchAll(/^\s*"([a-z_]+)":\s*\(/gm)].map((m) => m[1]).sort()
    expect(backend.length).toBeGreaterThan(0)          // the slice found the table at all

    const set = s.slice(s.indexOf('ADAPTER_READY = new Set('))
    const ui = [...set.slice(0, set.indexOf(')')).matchAll(/'([a-z_]+)'/g)].map((m) => m[1]).sort()
    expect(ui).toEqual(backend)

    // The catalogue still lists providers with no adapter, and still says so rather than
    // offering a switch that would do nothing.
    expect(s).toMatch(/adapter coming/i)
    expect(s).toMatch(/PROVIDER_LABELS/)
  })

  it('offers a connection test that sends no customer document, and says so where it is pressed', () => {
    const s = read('Settings.jsx')
    const api = read('api.js')
    expect(s).toMatch(/TestConnection/)
    expect(api).toMatch(/testAiProvider\s*=/)
    expect(api).toMatch(/\/ai\/providers\/test/)

    // The request body carries a provider NAME and nothing else — no key, no document, no scan.
    const call = api.slice(api.indexOf('testAiProvider'), api.indexOf('testAiProvider') + 700)
    expect(call).toMatch(/JSON\.stringify\(\{ provider \}\)/)
    expect(call).not.toMatch(/\bapi_key\b|[^_]\bkey:/)

    // The guarantee is on the control itself, not in a paragraph somewhere else on the page:
    // "what did I just send them?" is asked at the moment of pressing.
    const btn = s.slice(s.indexOf('export function TestConnection'))
    expect(btn.slice(0, btn.indexOf('</span>'))).toMatch(/never one of your documents/i)
  })
})
