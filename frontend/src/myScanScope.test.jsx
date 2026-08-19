/**
 * The per-user scan-scope override editor (ADR 0035 stage 2, the user-facing surface).
 *
 * The one property that makes this safe for PHI is that an override may only WIDEN — a personal
 * setting can never skip a check the organization required. The backend enforces it (the union in
 * active_scope); this editor MAKES IT VISIBLE by rendering the owner-mandated pairs as locked-on in
 * the grid, so the user can only ever add. These tests assert that visible contract: owner pairs are
 * locked (checked + disabled), the user's picks are additions, and save routes to PUT (widen) vs
 * DELETE (fall back to the org default) correctly.
 *
 * DOM-level, not browser-level (this repo's preview server roots at the shared checkout — see CLAUDE.md).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const apiMock = { get: null, put: null, clear: null }
vi.mock('./api.js', () => ({
  getMyScope: (...a) => apiMock.get(...a),
  putMyScope: (...a) => apiMock.put(...a),
  clearMyScope: (...a) => apiMock.clear(...a),
}))

const { default: MyScanScope } = await import('./MyScanScope.jsx')

async function render({ owner = '', mine = '' } = {}) {
  apiMock.get = vi.fn(async () => ({ owner_default: owner, scan_scope: mine }))
  apiMock.put = vi.fn(async (payload) => ({ scan_scope: typeof payload === 'string' ? payload : JSON.stringify(payload) }))
  apiMock.clear = vi.fn(async () => ({ scan_scope: '' }))
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(MyScanScope)) })
  return container
}

const click = async (el) => { await act(async () => { el.click() }) }
const cell = (c, sc, fmt) => [...c.querySelectorAll('input[type="checkbox"]')]
  .find((e) => { const l = e.getAttribute('aria-label') || ''; return l.includes(sc) && l.includes(fmt) })
const radio = (c, text) => [...c.querySelectorAll('label')]
  .find((l) => l.textContent.includes(text))?.querySelector('input')
const saveBtn = (c) => [...c.querySelectorAll('button')].find((b) => /Save my scope/.test(b.textContent))
const status = (c) => c.querySelector('[role="status"]')?.textContent || ''


describe('when the org already assesses everything', () => {
  it('says a personal override can add nothing, and shows no grid', async () => {
    const c = await render({ owner: '' })                 // owner = no restriction
    expect(c.textContent).toMatch(/nothing a personal override can add/i)
    expect(c.querySelector('table')).toBeFalsy()
  })
})

describe('the owner default is a locked floor', () => {
  it('renders owner-mandated pairs checked AND disabled; the user can add others', async () => {
    // owner mandates 1.4.3×docx; the user has added 1.4.3×pdf.
    const c = await render({ owner: '{"1.4.3": ["docx"]}', mine: '{"1.4.3": ["pdf"]}' })
    const ownerBox = cell(c, '1.4.3', 'DOCX')
    const userBox = cell(c, '1.4.3', 'PDF')
    expect(ownerBox.checked).toBe(true)
    expect(ownerBox.disabled).toBe(true)                  // locked — cannot be removed
    expect(userBox.checked).toBe(true)
    expect(userBox.disabled).toBe(false)                  // the user's own addition, editable
  })
})

describe('saving', () => {
  it('widen mode PUTs only the additions (owner pairs are not resent)', async () => {
    const c = await render({ owner: '{"1.4.3": ["docx"]}', mine: '' })  // no personal override yet
    await click(radio(c, 'Also assess additional'))       // switch to widen
    await click(cell(c, '1.4.3', 'PDF'))                   // add 1.4.3×pdf
    await click(saveBtn(c))
    expect(apiMock.put).toHaveBeenCalledWith({ '1.4.3': ['pdf'] })
    expect(apiMock.clear).not.toHaveBeenCalled()
    expect(status(c)).toMatch(/beyond the organization default/i)
  })

  it('choosing the org default DELETEs the override rather than storing a value', async () => {
    const c = await render({ owner: '{"1.4.3": ["docx"]}', mine: '{"1.4.3": ["pdf"]}' })
    await click(radio(c, 'Use the organization default'))
    await click(saveBtn(c))
    expect(apiMock.clear).toHaveBeenCalled()
    expect(apiMock.put).not.toHaveBeenCalled()
    expect(status(c)).toMatch(/use the organization default/i)
  })

  it('adopts the SERVER echo — a widen with no additions clears instead of storing {}', async () => {
    const c = await render({ owner: '{"1.4.3": ["docx"]}', mine: '{"1.4.3": ["pdf"]}' })
    await click(cell(c, '1.4.3', 'PDF'))                   // remove the only addition
    await click(saveBtn(c))
    expect(apiMock.clear).toHaveBeenCalled()               // empty additions => clear, never PUT {}
    expect(apiMock.put).not.toHaveBeenCalled()
  })
})
