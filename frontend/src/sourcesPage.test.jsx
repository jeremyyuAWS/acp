/**
 * The Sources page (formerly the Integrations tab) — DOM-level, mounting the real component.
 *
 * What it guards, top to bottom:
 *   - a CONNECTED SOURCES section with a status card that shows the TRUTHFUL count line
 *     ("{discovered} in Drive · {lastScanFiles} in last scan") and exactly ONE dominant health state;
 *   - the page-level "New scan" button routes through `onScan` (App's `requestScan`) — NOT a
 *     local dialog. The scope/behavior review modal is now app-level (ScanReviewModal, rendered by
 *     App), shared by every scan entry point, so the Sources tab no longer owns one. This guards
 *     that Integrations does not re-introduce its own modal and simply calls onScan.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (see CLAUDE.md), so a browser check would exercise code that does not
 * contain this change. Everything here mounts the component and asserts against the rendered DOM.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

// Integrations reads getConfig; the wizard nested in the modal reads getSettings/updateSettings;
// the Scanned-locations row reads getScanLocations and writes setScanLocations. A partial mock of
// a module the component imports FROM does not fail at import — it fails at first call, inside a
// useEffect, as eleven unrelated assertions.
vi.mock('./api.js', () => ({
  getConfig: vi.fn(async () => ({ google_client_id: null })),
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: {} })),
  setScanLocations: vi.fn(async (source, folders) => ({ ok: true, source, folders })),
  listFolders: vi.fn(async () => ({ folders: [] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
}))

const { default: Integrations, sourceManagementDestination } = await import('./Integrations.jsx')

const DRIVE_BACKEND = { id: '_gdrive', type: 'google_drive', name: 'My Drive',
  user: 'alex@example.com', files: 50 }

// A source with a clean recent history → Healthy; the run's post-filter files drive the count line.
const HEALTHY_SCANS = [
  { id: 'r1', source: 'drive', completed_at: '2026-08-10T12:00:00Z', files: 44, error: 0, avg_score: 88 },
]
// A source with file-access errors in recent scans → Needs attention.
const DEGRADED_SCANS = [
  { id: 'r1', source: 'drive', completed_at: '2026-08-10T12:00:00Z', files: 40, error: 9, avg_score: 70 },
]

function baseProps(over = {}) {
  return {
    sources: [DRIVE_BACKEND],
    files: [],
    scans: HEALTHY_SCANS,
    onScan: vi.fn(),
    busy: false,
    hasDriveToken: true,
    hasSPToken: false,
    onConnect: vi.fn(),
    deepScan: true, setDeepScan: vi.fn(),
    queuedScan: false, setQueuedScan: vi.fn(),
    excludeRemediated: true, setExcludeRemediated: vi.fn(),
    incremental: true, setIncremental: vi.fn(),
    ...over,
  }
}

async function mount(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(Integrations, props)) })
  // Flush the getConfig/getSettings effects.
  await act(async () => { await Promise.resolve() })
  return container
}
const click = async (el) => { await act(async () => { el.click() }); await act(async () => { await Promise.resolve() }) }
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))

describe('the Sources page', () => {
  it('renders the page header with a New scan button', async () => {
    const c = await mount(baseProps())
    expect(c.textContent).toMatch(/Content Sources/)
    expect(c.textContent).toMatch(/Manage the locations ACP scans and monitors/)
    expect(btn(c, /New scan/)).toBeTruthy()
  })

  it('shows a CONNECTED SOURCES section with a status card', async () => {
    const c = await mount(baseProps())
    expect(c.textContent).toMatch(/CONNECTED SOURCES \(1\)/)
    const card = c.querySelector('.srccard--on')
    expect(card).toBeTruthy()
    expect(card.textContent).toMatch(/Google Drive/)
    expect(card.textContent).toMatch(/alex@example\.com/)
  })

  it('shows the truthful "{discovered} in Drive · {lastScan} in last scan" count line', async () => {
    const c = await mount(baseProps())
    const count = c.querySelector('.srccard-count')
    expect(count).toBeTruthy()
    expect(count.textContent).toMatch(/50 in Drive/)
    expect(count.textContent).toMatch(/44 in last scan/)
  })

  it('omits the "in last scan" half when the source has never completed a scan', async () => {
    const c = await mount(baseProps({ scans: [] }))
    const count = c.querySelector('.srccard-count')
    expect(count.textContent).toMatch(/50 in Drive/)
    expect(count.textContent).not.toMatch(/in last scan/)
    // And the health state falls back to "Not yet scanned".
    expect(c.querySelector('.srccard--on').textContent).toMatch(/Not yet scanned/)
  })

  it('shows exactly one dominant health state — Healthy for a clean history', async () => {
    const c = await mount(baseProps())
    const health = c.querySelectorAll('.srccard--on .srccard-health')
    expect(health.length).toBe(1)
    expect(health[0].textContent).toMatch(/Healthy/)
  })

  it('shows "Needs attention" with a file-access sub-line when recent scans errored', async () => {
    const c = await mount(baseProps({ scans: DEGRADED_SCANS }))
    const health = c.querySelectorAll('.srccard--on .srccard-health')
    expect(health.length).toBe(1)
    expect(health[0].textContent).toMatch(/Needs attention/)
    expect(c.querySelector('.srccard-health-sub').textContent).toMatch(/9 files couldn’t be accessed/)
  })

  it('keeps read-only out of the status line, in a Connection details reveal instead', async () => {
    const c = await mount(baseProps())
    const card = c.querySelector('.srccard--on')
    // Not in the health pill.
    expect(card.querySelector('.srccard-health').textContent).not.toMatch(/read-only/)
    const details = card.querySelector('.srccard-conn')
    expect(details.querySelector('summary').textContent).toMatch(/Connection details/)
    expect(details.textContent).toMatch(/read-only/)
  })

  it('links a connected card to the real provider without replacing ACP management', async () => {
    const c = await mount(baseProps())
    const card = c.querySelector('.srccard--on')
    const provider = card.querySelector('a[aria-label="Open Google Drive in a new tab"]')
    expect(provider?.getAttribute('href')).toBe('https://drive.google.com/drive/my-drive')
    expect(provider?.getAttribute('target')).toBe('_blank')
    expect(provider?.getAttribute('rel')).toContain('noopener')
    expect(btn(card, /^Manage$/)).toBeTruthy()
  })

  it('prefers an exact saved SharePoint URL and rejects unsafe connector URLs', () => {
    expect(sourceManagementDestination({ type: 'sharepoint', web_url: 'https://movate.sharepoint.com/sites/ACP' }))
      .toEqual({ url: 'https://movate.sharepoint.com/sites/ACP', label: 'Open SharePoint' })
    expect(sourceManagementDestination({ type: 'onedrive', web_url: 'javascript:alert(1)' }))
      .toEqual({ url: 'https://www.microsoft365.com/launch/onedrive', label: 'Open OneDrive' })
  })

  it('lists OneDrive under AVAILABLE SOURCES and the future connectors as a muted line', async () => {
    const c = await mount(baseProps())
    expect(c.textContent).toMatch(/AVAILABLE SOURCES/)
    expect(btn(c, /Connect Microsoft/)).toBeTruthy()
    const soon = c.querySelector('.intsoon-line')
    expect(soon.textContent).toMatch(/More sources coming soon/)
    expect(soon.textContent).toMatch(/SharePoint/)
    // The future connectors are NOT rendered as big cards.
    expect(c.querySelector('.soonchip')).toBeNull()
  })
})

describe('the New scan buttons route through the app-level gate (onScan), not a local modal', () => {
  const dialog = (c) => c.querySelector('[role="dialog"]')

  it('the page-level New scan button calls onScan("all") — every connected source', async () => {
    const props = baseProps()
    const c = await mount(props)
    await click(btn(c, /New scan/))
    expect(props.onScan).toHaveBeenCalledWith('all')
  })

  it('a connected card\'s New scan button calls onScan for that source ("drive")', async () => {
    const props = baseProps()
    const c = await mount(props)
    const card = c.querySelector('.srccard--on')
    await click([...card.querySelectorAll('button')].find((b) => /New scan/.test(b.textContent)))
    expect(props.onScan).toHaveBeenCalledWith('drive')
  })

  it('does NOT render its own scan-review dialog — the modal is app-level now', async () => {
    const c = await mount(baseProps())
    expect(dialog(c)).toBeNull()
    await click(btn(c, /New scan/))
    // Clicking still opens no local dialog; App renders the shared ScanReviewModal instead.
    expect(dialog(c)).toBeNull()
    // And the scan-behavior toggles no longer live on this page.
    expect(c.textContent).not.toMatch(/Scan behavior/)
    expect([...c.querySelectorAll('[role="switch"]')].length).toBe(0)
  })
})
