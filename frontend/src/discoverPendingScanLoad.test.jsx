/**
 * The live 2026-08-30 report: a just-logged-in user, whose workspace already has a scan, sees
 * Discover open on "0 documents discovered", "0 could not be read", "BY FILE TYPE · Total 0", and
 * "No documents yet — run a scan from Sources." — because App.jsx's initial-load effect hasn't
 * resolved `run` yet (GET /scans/{id} is still the one genuinely heavy call), and every count on
 * this screen reads `files: []`/`scope: null` (App.jsx's own not-loaded-yet fallback, indistin-
 * guishable from a real empty scan to estateSummary()'s `Array.isArray` guard) as a measured zero.
 *
 * `pendingScanLoad` (App.jsx: `!run && !!overviewPreview` — bootstrap's cached snapshot already
 * confirmed a scan exists) is the signal that tells Discover to show a plain "loading" line
 * instead of asserting anything about the estate. See Discover.jsx's own comment at the header
 * line for the full trace.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

let container, root
afterEach(unmountAll)

const render = async (props = {}) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'Google Drive' }], files: [], busy: false, onScan: () => {},
      onAdvance: () => {}, run: null, scanId: null, scope: null, ...props,
    }))
  })
  for (let k = 0; k < 4; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return container
}
const text = () => container.textContent

describe('Discover while the scan payload is still loading (pendingScanLoad)', () => {
  it('shows a loading line instead of the estate header when pendingScanLoad is true', async () => {
    const c = await render({ pendingScanLoad: true })
    expect(text()).toContain('Loading your inventory…')
    expect(text()).not.toMatch(/\bdocuments\b\s*discovered across/)
  })

  it('suppresses "Loading your inventory…" once a freshly-started scan is already busy — the queued card covers that window instead', async () => {
    // Live 2026-08-30: clicking "Re-scan" sets busy true and starts polling `progress` well before
    // App.jsx's own `run` re-fetch resolves, so pendingScanLoad and a freshly-started scan are NOT
    // mutually exclusive. Without this the placeholder and the queued ProcessingStatusPanel below
    // rendered at once, contradicting each other ("loading" beside "waiting for a worker").
    const c = await render({ pendingScanLoad: true, busy: true })
    expect(text()).not.toContain('Loading your inventory…')
  })

  it('does not render DISCOVERY RESULTS or its zero-valued tiles when pendingScanLoad is true', async () => {
    const c = await render({ pendingScanLoad: true })
    expect(c.querySelector('#discover-inventory-table')).toBeFalsy()
    expect(text()).not.toContain('DISCOVERY RESULTS')
    expect(text()).not.toContain('BY FILE TYPE')
  })

  it('does not render "No documents yet" when pendingScanLoad is true', async () => {
    const c = await render({ pendingScanLoad: true })
    expect(text()).not.toContain('No documents yet')
  })

  it('suppresses the results table even if files happens to be non-empty while pendingScanLoad is true', async () => {
    // Defensive: the contract is "trust the prop, not files.length" — pendingScanLoad is only
    // ever true in a window where files really is [], but the suppression itself must not be
    // re-derived from files.length, or a future caller passing both correctly could silently
    // stop being protected.
    const FILES = [{ file: 'a.docx', type: 'DOCX', tags: [], issues: [], department: 'Clinical', sourceName: 'Drive' }]
    const c = await render({ pendingScanLoad: true, files: FILES })
    expect(c.querySelector('#discover-inventory-table')).toBeFalsy()
  })

  it('renders the ordinary genuinely-empty-workspace screen when pendingScanLoad is false (default)', async () => {
    // Baseline/contrast: with the prop at its default (unset callers are unaffected), the
    // pre-existing "no scan at all yet" behavior is unchanged.
    const c = await render()
    expect(text()).not.toContain('Loading your inventory…')
    expect(text()).toContain('No documents yet')
  })

  it('shows the real DISCOVERY RESULTS numbers, not the loading line, once run/files have arrived', async () => {
    const scope = { inventory: { discovered: 1 } }
    const FILES = [{ file: 'a.docx', type: 'DOCX', tags: [], issues: [], department: 'Clinical', sourceName: 'Drive' }]
    const c = await render({ pendingScanLoad: false, files: FILES,
                              run: { id: 's1', status: 'discovered', discovered_at: '2026-08-30T00:00:00Z' },
                              scope, scanId: 's1' })
    expect(text()).not.toContain('Loading your inventory…')
    expect(text()).not.toContain('No documents yet')
    expect(text()).toContain('DISCOVERY RESULTS')
    expect(text()).toContain('1file discovered')
  })
})
