// Multi-tenant SharePoint (connecting a SECOND Entra tenant's SharePoint/OneDrive as a scan
// source, not just the one this deployment authenticates ACP sign-in against).
//
// getSpAuth() used to resolve exactly one (clientId, tenant) pair from /config, cached once for
// the whole session — structurally unable to reach a second tenant no matter what a user did in
// the UI. getMicrosoftTenants() now exposes every configured tenant, and getSpAuth(tenantKey)
// resolves ONE of them — omitted (every caller before this) resolves to the first, so a
// single-tenant deployment (still every deployment today) behaves exactly as before.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let configResponse

vi.mock('./api.js', () => ({
  getConfig: () => Promise.resolve(configResponse),
}))

beforeEach(() => {
  vi.resetModules()
  configResponse = { azure_client_id: 'c1', azure_tenant_id: 't1' }
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('getMicrosoftTenants', () => {
  it('returns every tenant /config reports', async () => {
    configResponse = {
      microsoft_tenants: [
        { key: 'primary', label: 'Primary', client_id: 'c1', tenant_id: 't1' },
        { key: 'tenant2', label: 'Contoso', client_id: 'c2', tenant_id: 't2' },
      ],
    }
    const { getMicrosoftTenants } = await import('./sharepointScopes.js')
    const tenants = await getMicrosoftTenants()
    expect(tenants).toHaveLength(2)
    expect(tenants.map((t) => t.key)).toEqual(['primary', 'tenant2'])
  })

  it('a single-tenant deployment reports exactly one entry', async () => {
    configResponse = {
      microsoft_tenants: [{ key: 'primary', label: 'Primary', client_id: 'c1', tenant_id: 't1' }],
    }
    const { getMicrosoftTenants } = await import('./sharepointScopes.js')
    expect(await getMicrosoftTenants()).toHaveLength(1)
  })

  it('caches after the first resolution, like the old single-pair getSpAuth did', async () => {
    configResponse = {
      microsoft_tenants: [{ key: 'primary', label: 'Primary', client_id: 'c1', tenant_id: 't1' }],
    }
    const { getMicrosoftTenants } = await import('./sharepointScopes.js')
    const first = await getMicrosoftTenants()
    configResponse = { microsoft_tenants: [{ key: 'tenant2', label: 'Contoso', client_id: 'c2', tenant_id: 't2' }] }
    const second = await getMicrosoftTenants()
    expect(second).toBe(first)   // same cached array, config change ignored until reload
  })

  it('falls back to the build-time VITE_AZURE_* pair when /config has no microsoft_tenants', async () => {
    vi.stubEnv('VITE_AZURE_CLIENT_ID', 'vite-client')
    vi.stubEnv('VITE_AZURE_TENANT_ID', 'vite-tenant')
    configResponse = {}   // no azure_client_id, no microsoft_tenants — as an unconfigured deployment
    const { getMicrosoftTenants } = await import('./sharepointScopes.js')
    const tenants = await getMicrosoftTenants()
    expect(tenants).toEqual([{ key: 'primary', label: 'Microsoft', client_id: 'vite-client', tenant_id: 'vite-tenant' }])
  })

  it('is empty when nothing is configured anywhere — the caller hides the connect button', async () => {
    configResponse = {}
    const { getMicrosoftTenants } = await import('./sharepointScopes.js')
    expect(await getMicrosoftTenants()).toEqual([])
  })
})

describe('getSpAuth(tenantKey)', () => {
  const TWO_TENANTS = {
    microsoft_tenants: [
      { key: 'primary', label: 'Primary', client_id: 'c1', tenant_id: 't1' },
      { key: 'tenant2', label: 'Contoso', client_id: 'c2', tenant_id: 't2' },
    ],
  }

  it('omitted tenantKey resolves to the FIRST configured tenant — every caller before multi-tenant', async () => {
    configResponse = TWO_TENANTS
    const { getSpAuth } = await import('./sharepointScopes.js')
    expect(await getSpAuth()).toEqual({ clientId: 'c1', tenant: 't1', key: 'primary' })
  })

  it('an explicit tenantKey resolves to THAT tenant, not the first', async () => {
    configResponse = TWO_TENANTS
    const { getSpAuth } = await import('./sharepointScopes.js')
    expect(await getSpAuth('tenant2')).toEqual({ clientId: 'c2', tenant: 't2', key: 'tenant2' })
  })

  it('an unknown tenantKey resolves to no client id, not silently the first tenant', async () => {
    // A stale key from a removed config entry must not silently sign into the wrong tenant.
    configResponse = TWO_TENANTS
    const { getSpAuth } = await import('./sharepointScopes.js')
    const auth = await getSpAuth('nope')
    expect(auth.clientId).toBe('')
  })

  it('a single-tenant deployment behaves exactly as the old single-pair getSpAuth did', async () => {
    configResponse = {
      microsoft_tenants: [{ key: 'primary', label: 'Primary', client_id: 'c1', tenant_id: 't1' }],
    }
    const { getSpAuth } = await import('./sharepointScopes.js')
    expect(await getSpAuth()).toEqual({ clientId: 'c1', tenant: 't1', key: 'primary' })
  })
})
