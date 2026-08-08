/**
 * Unticking a file type on the first screen must also stop Discover LISTING that type.
 *
 * One fact lives in two stores. `scan_scope` (server) decides what is ASSESSED; the
 * `mova_filetypes` localStorage config decides what Discover shows — Discover.jsx filters its
 * inventory on `fileTypeConfig[f.type] !== false`. ScanSetup wrote only the first, so unticking
 * PDF scoped the assessment and left every PDF in the inventory. Reported from a live estate:
 * two PDFs still listed after the file-type filter excluded them.
 *
 * FileTypeConfig.jsx's own header records this exact failure once already — "Two stores for one
 * fact is what made this panel lie in the first place: it claimed to exclude types from
 * remediation while only hiding rows in Discover". ScanSetup reintroduced the other half of it,
 * which is why the guard belongs in a test rather than in a comment.
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)
beforeEach(() => localStorage.clear())

const settingsMock = { get: null, put: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => settingsMock.get(...a),
  updateSettings: (...a) => settingsMock.put(...a),
}))

const { default: ScanSetup } = await import('./ScanSetup.jsx')
const { loadFileTypeConfig } = await import('./FileTypeConfig.jsx')

async function render() {
  settingsMock.get = vi.fn(async () => ({ scan_scope: '' }))
  settingsMock.put = vi.fn(async () => ({}))
  const onFileTypeChange = vi.fn()
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanSetup, { onScan: vi.fn(), busy: false, onFileTypeChange }))
  })
  return { c: container, onFileTypeChange }
}

const click = async (el) => { await act(async () => { el.click() }) }
const chip = (c, fmt) => [...c.querySelectorAll('button')]
  .find((b) => new RegExp(`\\b${fmt}\\b`, 'i').test(b.textContent))
const saveBtn = (c) => [...c.querySelectorAll('button')].find((b) => /Save scope only/.test(b.textContent))


describe('the two file-type stores stay in step', () => {
  it('writes the Discover view config, not only scan_scope', async () => {
    const { c } = await render()
    await click(chip(c, 'PDF'))
    await click(saveBtn(c))

    // the server axis
    expect(settingsMock.put).toHaveBeenCalled()
    // ...and the one Discover actually filters on
    expect(loadFileTypeConfig().pdf, 'pdf still listed in Discover after being unticked').toBe(false)
    expect(loadFileTypeConfig().docx, 'docx wrongly excluded').toBe(true)
  })

  it('tells the app, so the inventory updates without a reload', async () => {
    const { c, onFileTypeChange } = await render()
    await click(chip(c, 'PDF'))
    await click(saveBtn(c))
    expect(onFileTypeChange).toHaveBeenCalled()
    expect(onFileTypeChange.mock.calls.at(-1)[0].pdf).toBe(false)
  })

  it('leaves types it does not offer alone', async () => {
    // html/video/audio have no scan_scope axis and are never shown by ScanSetup. Writing the
    // four it knows about as a whole object would silently discard a choice made in Settings.
    localStorage.setItem('mova_filetypes', JSON.stringify({ html: false, video: false }))
    const { c } = await render()
    await click(chip(c, 'PDF'))
    await click(saveBtn(c))

    const cfg = loadFileTypeConfig()
    expect(cfg.html, 'an unrelated type was overwritten').toBe(false)
    expect(cfg.video, 'an unrelated type was overwritten').toBe(false)
    expect(cfg.pdf).toBe(false)
  })

  it('does not touch either store when the save is refused', async () => {
    // Empty scope is refused with a reason. Writing the view config anyway would hide files
    // from an inventory whose assessment scope never changed.
    const { c, onFileTypeChange } = await render()
    for (const f of ['DOCX', 'XLSX', 'PPTX', 'PDF']) await click(chip(c, f))
    await click(saveBtn(c))

    expect(settingsMock.put).not.toHaveBeenCalled()
    expect(onFileTypeChange).not.toHaveBeenCalled()
    expect(localStorage.getItem('mova_filetypes')).toBeNull()
  })
})
