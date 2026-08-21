import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))

// The Entra client/tenant are served from /config at runtime so a deployment (or each customer's
// tenant) is set with an env var and no rebuild. These pin that the runtime value WINS over the
// build-time VITE_AZURE_* fallback, and that a missing/failed /config degrades to the fallback
// rather than throwing — the connect button must never crash the sign-in screen.

describe('getSpAuth prefers runtime /config over the build-time fallback', () => {
  beforeEach(() => vi.resetModules())  // getSpAuth caches its result; reset per case

  it('returns the runtime azure_client_id / azure_tenant_id from /config', async () => {
    // A backend that predates multi-tenant SharePoint (or a rollout-order accident) sends only
    // the singular pair, no microsoft_tenants — getMicrosoftTenants' legacy fallback covers it.
    vi.doMock('./api.js', () => ({ getConfig: () => Promise.resolve({ azure_client_id: 'runtime-cid', azure_tenant_id: 'runtime-tid' }) }))
    const { getSpAuth } = await import('./sharepointScopes.js')
    expect(await getSpAuth()).toEqual({ clientId: 'runtime-cid', tenant: 'runtime-tid', key: 'primary' })
  })

  it('falls back to the build-time value (and tenant "common") when /config carries neither', async () => {
    vi.doMock('./api.js', () => ({ getConfig: () => Promise.resolve({}) }))
    const { getSpAuth } = await import('./sharepointScopes.js')
    // No VITE_AZURE_* in the test env → empty client id, tenant defaults to 'common'.
    expect(await getSpAuth()).toEqual({ clientId: '', tenant: 'common', key: null })
  })

  it('does not throw when /config is unreachable — degrades to the fallback', async () => {
    vi.doMock('./api.js', () => ({ getConfig: () => Promise.reject(new Error('offline')) }))
    const { getSpAuth } = await import('./sharepointScopes.js')
    expect((await getSpAuth()).tenant).toBe('common')
  })
})

describe('the login screen offers Microsoft sign-in only when SharePoint is configured', () => {
  const SRC = readFileSync(join(HERE, 'SignIn.jsx'), 'utf8')
  it('has a Microsoft sign-in handler and button', () => {
    expect(SRC).toMatch(/const signInWithMicrosoft = async/)
    expect(SRC).toMatch(/Sign in with Microsoft/)
  })
  it('gates the button on a configured Entra client id (runtime or build-time)', () => {
    // The button renders only when /config (or VITE) supplies an azure client id, so it never
    // appears inert on a deployment that hasn't been pointed at a tenant.
    expect(SRC).toMatch(/cfg\.azure_client_id \|\| import\.meta\.env\.VITE_AZURE_CLIENT_ID/)
  })
})
