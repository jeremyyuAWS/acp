// The Discover completion card's "See what's changed since your last scan of this source" link
// (DiscoverCompleteSummary → Discover → App.jsx → Integrations) is only as good as its wiring:
// Discover doesn't know about source objects, only the raw `run.source` string, so the actual
// matching happens inside Integrations via sourceOps.sourceKeys() — the SAME lookup SourceDrawer's
// own data (runsForSource/filesForSource) already relies on. These tests exercise that wiring
// directly against Integrations, not against the button click in Discover (covered separately in
// discoverSourceRedirect.test.jsx) — a wrong key match here would silently open the wrong drawer,
// or none at all, regardless of how correctly Discover computed the key.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', () => ({
  getConfig: vi.fn(() => Promise.resolve({})),
  listFolders: vi.fn(() => Promise.resolve([])),
  listSpFolders: vi.fn(() => Promise.resolve([])),
  getScanLocations: vi.fn(() => Promise.resolve({ locations: {} })),
  setScanLocations: vi.fn(() => Promise.resolve({})),
  listDispositionPolicies: vi.fn(() => Promise.resolve([])),
  getInventoryDiff: vi.fn(() => Promise.resolve(null)),
  previewDispositionPolicy: vi.fn(() => Promise.resolve(null)),
  listDispositionApprovals: vi.fn(() => Promise.resolve([])),
  approveDisposition: vi.fn(() => Promise.resolve({})),
  rejectDisposition: vi.fn(() => Promise.resolve({})),
  listDispositionAudit: vi.fn(() => Promise.resolve([])),
}))
vi.mock('./sim.js', () => ({ SIM: false }))
vi.mock('./googleIdentity.js', () => ({ googleUserInfo: vi.fn() }))
vi.mock('./sharepointScopes.js', () => ({
  SP_SCOPES: [],
  getMicrosoftTenants: vi.fn(() => Promise.resolve([])),
}))
vi.mock('./msalClient.js', () => ({
  signInForScopes: vi.fn(),
  MsalNotReady: class MsalNotReady extends Error {},
  MsalNotConfigured: class MsalNotConfigured extends Error {},
}))
vi.mock('./authErrors.js', () => ({ friendlyAuthError: (e) => e?.message || 'auth error' }))

const { default: Integrations } = await import('./Integrations.jsx')

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

const SOURCES = [
  { id: 'local', type: 'local', name: 'Local' },
  { id: 'drive', type: 'google_drive', name: 'Google Drive' },
]

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(Integrations, { sources: SOURCES, files: [], scans: [], onScan: () => {},
      busy: false, hasDriveToken: false, hasSPToken: false, onConnect: () => {}, ...props }))
  })
  return container
}

describe('a source-history redirect into Integrations', () => {
  it('opens SourceDrawer for the matching source, on its Activity tab', async () => {
    const onHandled = vi.fn()
    const c = await mount({ openSourceKey: 'drive', onOpenSourceHandled: onHandled })
    expect([...c.querySelectorAll('button[role="tab"]')].map((b) => b.textContent))
      .toEqual(['Overview', 'Scope', 'Rules', 'Activity'])
    const active = [...c.querySelectorAll('button[role="tab"]')].find((b) => b.textContent === 'Activity')
    expect(active.getAttribute('aria-selected')).toBe('true')
    expect(onHandled).toHaveBeenCalledTimes(1)
  })

  it('matches via sourceKeys (type as well as id)', async () => {
    // 'google_drive' is SOURCES[1].type, not its id — sourceKeys() must fold both in, or this
    // redirect only ever works for sources whose scan-source string happens to equal their id.
    const c = await mount({ openSourceKey: 'google_drive' })
    const active = [...c.querySelectorAll('button[role="tab"]')].find((b) => b.textContent === 'Activity')
    expect(active.getAttribute('aria-selected')).toBe('true')
  })

  it('does nothing when the key matches no source — never opens the wrong drawer', async () => {
    const onHandled = vi.fn()
    const c = await mount({ openSourceKey: 'all', onOpenSourceHandled: onHandled })
    expect(c.querySelector('[role="tab"]')).toBeNull()
    expect(onHandled).toHaveBeenCalledTimes(1)
  })

  it('is a no-op when no redirect is pending', async () => {
    const c = await mount({ openSourceKey: null })
    expect(c.querySelector('[role="tab"]')).toBeNull()
  })
})
