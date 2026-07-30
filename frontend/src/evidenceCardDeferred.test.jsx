// A DEFERRED alt-text row (evidence thumbnails, no AI draft) must send one value per image.
//
// This is the case PR 62 left on the picker: the reviewer described one image and approved all
// nineteen. The card now renders one editor per evidence image and sends a positional
// approved_values list — index i is evidence image i — which the server writes onto evidence[i].
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const deferred = {
  id: 7, scan_id: 's1', file: 'deck.pptx', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 3,
  evidence: [
    { locator: 'ppt/slides/slide1.xml#rId2', thumb: PNG },
    { locator: 'ppt/slides/slide2.xml#rId3', thumb: PNG },
    { locator: 'ppt/slides/slide3.xml#rId4', thumb: PNG },
  ],
}

let container, root, onAct
const mount = async (item = deferred) => {
  onAct = vi.fn().mockResolvedValue(undefined)
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct, editable: true })) })
}
const inputs = () => [...container.querySelectorAll('.evcard-rec-input')]
const type = async (el, v) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
  await act(async () => { setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
const clickText = async (text) => {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text))
  await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

beforeEach(() => { suggestFix.mockReset() })

describe('EvidenceCard — approving a deferred row', () => {
  it('renders one editor per evidence image', async () => {
    await mount()
    expect(inputs()).toHaveLength(3)
  })

  it('sends the per-image values positionally on approve', async () => {
    await mount()
    await type(inputs()[0], 'a nurse')
    await type(inputs()[2], 'the logo')          // middle left blank on purpose
    await clickText('Approve')
    const [, status, , , opts] = onAct.mock.calls[0]
    expect(status).toBe('approved')
    expect(opts.approvedValues).toEqual(['a nurse', '', 'the logo'])
  })

  it('sends no values on reject — and a reject captures WHY (feedback intelligence)', async () => {
    await mount()
    await type(inputs()[0], 'a nurse')
    // Two-step: Reject opens the reason chips (nothing recorded yet)…
    await clickText('Reject')
    expect(onAct).not.toHaveBeenCalled()
    // …and picking a reason submits the rejection carrying it.
    await clickText('Too vague')
    const [, status, , , opts] = onAct.mock.calls[0]
    expect(status).toBe('rejected')
    expect(opts.approvedValues).toBeNull()
    expect(opts.rejectReason).toBe('too_vague')
  })
})
