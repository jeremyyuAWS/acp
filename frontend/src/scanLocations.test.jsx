/**
 * Choosing which folders a source scans — and never losing the boundary while doing it.
 *
 * scanScope.js opens with the incident this feature could re-create: on 2026-07-30 a one-folder
 * scan reporting 1 and a whole-Drive scan reporting 8 rendered identically, six seconds apart,
 * and read as an estate that had lost seven documents. The fix was that a count is never shown
 * without the boundary it counts.
 *
 * A NEW NARROWING MODE GETS TO RE-INTRODUCE THAT FOR FREE unless it teaches the scope helpers
 * about itself. Two shapes here are exactly that hazard:
 *
 *   · several chosen Drive folders — kind 'folder', but `folder_name` is not the whole story
 *   · a chosen OneDrive folder — kind 'sharepoint' with NO `site`, which is what isNarrowScope
 *     keyed off for that source. Before this it returned false, so the ⚠ and the boundary line
 *     both disappeared on a genuinely narrowed scan.
 *
 * DOM-level rather than browser-level: this repo's preview server runs vite rooted at the SHARED
 * checkout whatever worktree you are in (CLAUDE.md), so a browser check would exercise code that
 * does not contain this change and pass.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { isNarrowScope, scopeLabel, scopeSentence, scopeChip } from './scanScope.js'

afterEach(unmountAll)

describe('the boundary survives multi-folder narrowing', () => {
  const twoDriveFolders = {
    kind: 'folder', kept: 12, truncated: false,
    folders: [{ id: 'hr', name: 'HR' }, { id: 'fin', name: 'Finance' }],
  }

  it('still counts as narrow', () => {
    expect(isNarrowScope(twoDriveFolders)).toBe(true)
  })

  it('names the folders rather than counting them', () => {
    // "in 2 Drive folders" answers "how many boundaries", not "which parts of my estate" —
    // substituting a number for a boundary is the original defect in miniature.
    const label = scopeLabel(twoDriveFolders)
    expect(label).toContain('HR')
    expect(label).toContain('Finance')
  })

  it('still says the rest of the Drive was not scanned', () => {
    expect(scopeSentence(twoDriveFolders, 12)).toContain('not scanned')
  })

  it('a single chosen folder is unchanged', () => {
    const one = { kind: 'folder', folder_name: 'HR', kept: 3, truncated: false }
    expect(scopeLabel(one)).toBe('in the Drive folder “HR”')
    expect(isNarrowScope(one)).toBe(true)
  })
})

describe('a chosen OneDrive folder — the case with no site to key off', () => {
  const oneDriveFolder = {
    kind: 'sharepoint', site: null, kept: 5, truncated: false,
    folders: [{ id: 'b!d/01A', name: 'Policies' }],
  }

  it('is narrow, although it has no site', () => {
    // The whole point. `site` is null here, so every pre-existing narrowness test misses it.
    expect(isNarrowScope(oneDriveFolder)).toBe(true)
  })

  it('does not claim to have covered OneDrive', () => {
    const label = scopeLabel(oneDriveFolder)
    expect(label).toContain('Policies')
    expect(label).not.toBe('across your OneDrive')
  })

  it('says other folders were not scanned', () => {
    expect(scopeSentence(oneDriveFolder, 5)).toContain('not scanned')
  })

  it('gets a chip, so it is spottable next to other scans', () => {
    expect(scopeChip(oneDriveFolder)).toMatchObject({ narrow: true })
  })

  it('an unnarrowed OneDrive scan is still described as the whole of it', () => {
    // The other direction: a caveat that fires on everything stops being read.
    const whole = { kind: 'sharepoint', site: null, kept: 40, truncated: false }
    expect(scopeLabel(whole)).toBe('across your OneDrive')
    expect(isNarrowScope(whole)).toBe(false)
  })
})

// ── the Sources card ─────────────────────────────────────────────────────────────────────────

vi.mock('./api.js', () => ({
  getConfig: vi.fn(async () => ({ google_client_id: null })),
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: { drive: [{ id: 'hr', name: 'HR' }] } })),
  setScanLocations: vi.fn(async (source, folders) => ({ ok: true, source, folders })),
  listFolders: vi.fn(async () => ({ folders: [] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
}))

const { default: Integrations } = await import('./Integrations.jsx')

const props = {
  sources: [{ id: '_gdrive', type: 'google_drive', name: 'My Drive',
              user: 'alex@example.com', files: 50 }],
  files: [], scans: [{ id: 'r1', source: 'drive', completed_at: '2026-08-10T12:00:00Z',
                       files: 44, error: 0, avg_score: 88 }],
  onScan: vi.fn(), busy: false, hasDriveToken: true, hasSPToken: false,
  onConnect: vi.fn(), onOpenAssess: vi.fn(),
}

async function mount() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(Integrations, props)) })
  return container
}

describe('the Sources card carries the location control', () => {
  it('shows the chosen folders on the card', async () => {
    // The page's subtitle already promised this ("Manage the locations ACP scans and monitors")
    // while offering no way to choose one — the picker existed, on the Discover tab, reachable
    // only after a scan had already read the whole estate.
    const c = await mount()
    expect(c.textContent).toContain('HR')
    expect(c.textContent).toContain('Scans:')
  })

  it('offers an Edit control', async () => {
    const c = await mount()
    const edit = [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Edit')
    expect(edit, 'no Edit control on the source card').toBeTruthy()
  })

  it('opens the picker from the card', async () => {
    const c = await mount()
    const edit = [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Edit')
    await act(async () => { edit.click() })
    const dlg = document.querySelector('[role="dialog"]')
    expect(dlg, 'Edit did not open a picker').toBeTruthy()
    expect(dlg.getAttribute('aria-label')).toContain('Folders to scan')
  })
})
