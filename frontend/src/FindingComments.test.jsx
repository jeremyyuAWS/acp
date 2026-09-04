import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// R18 · Comments on a finding — the per-finding discussion thread rendered in the remediation
// detail pane. Pins: oldest-first rendering, the "(you)" mark, the honest empty state, and that
// posting sends the finding_key + body and appends the returned row without a refetch.

let thread          // what getFindingComments resolves to
let posted          // captures the (scanId, payload) of the last addFindingComment call

vi.mock('./api.js', () => ({
  getMe: () => Promise.resolve({ email: 'jeremy@acp.io' }),
  getFindingComments: () => Promise.resolve(thread),
  findingKeyOf: (f) => [f.file || '', f.rule_id || f.ruleId || '', f.location || ''].join('||'),
  addFindingComment: (scanId, payload) => {
    posted = { scanId, payload }
    return Promise.resolve({ id: 'new1', ts: '2026-08-20T18:00:00Z',
                             author: 'jeremy@acp.io', body: payload.body,
                             file: payload.file, rule_id: payload.ruleId })
  },
}))

const { default: FindingComments } = await import('./FindingComments.jsx')

const FINDING = { file: 'deck.pptx', rule_id: '1.1.1', location: 'slide3', id: 42 }

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(FindingComments, { scanId: 's1', finding: FINDING, ...props }))
  })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const setValue = async (el, val) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
  await act(async () => { setter.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })) })
}
const btn = () => [...container.querySelectorAll('button')].find((b) => b.textContent.includes('Post'))

beforeEach(() => { thread = []; posted = undefined })
afterEach(unmountAll)

describe('FindingComments', () => {
  it('announces the comments loading state without calling an empty thread', async () => {
    thread = new Promise(() => {})
    const c = await mount()
    const status = c.querySelector('[role="status"]')
    expect(status?.getAttribute('aria-live')).toBe('polite')
    expect(status?.textContent).toBe('Loading comments…')
    expect(c.textContent).not.toContain('No comments yet')
  })

  it('announces a failed thread read as an error', async () => {
    thread = Promise.reject(new Error('offline'))
    const c = await mount()
    expect(c.querySelector('[role="alert"]')?.textContent).toMatch(/could not be loaded: offline/i)
    expect(c.textContent).not.toContain('No comments yet')
  })

  it('renders the thread oldest-first and marks the current user', async () => {
    thread = [
      { id: 'a', ts: '2026-08-20T10:00:00Z', author: 'jeremy@acp.io', body: 'decorative?' },
      { id: 'b', ts: '2026-08-20T11:00:00Z', author: 'deva@acp.io', body: 'carries numbers' },
    ]
    const c = await mount()
    const items = [...c.querySelectorAll('li.finding-comment')]
    expect(items.length).toBe(2)
    expect(items[0].textContent).toContain('decorative?')      // oldest first
    expect(items[1].textContent).toContain('carries numbers')
    expect(items[0].textContent).toContain('(you)')            // jeremy is me
    expect(items[1].textContent).not.toContain('(you)')        // deva is not
  })

  it('shows an honest empty state that is not "uncontested"', async () => {
    thread = []
    const c = await mount()
    expect(c.textContent).toContain('No comments yet')
    expect(c.textContent).toContain('not the same as the finding being')
    expect(c.querySelectorAll('li.finding-comment').length).toBe(0)
  })

  it('disables Post until there is text', async () => {
    const c = await mount()
    expect(btn().disabled).toBe(true)
    await setValue(c.querySelector('textarea'), 'a real note')
    expect(btn().disabled).toBe(false)
  })

  it('posts the finding_key + body and appends the row without refetch', async () => {
    const c = await mount()
    await setValue(c.querySelector('textarea'), '  needs a person  ')
    await click(btn())
    await act(async () => { await Promise.resolve() })
    // trimmed body, correct anchoring
    expect(posted.scanId).toBe('s1')
    expect(posted.payload.body).toBe('needs a person')
    expect(posted.payload.findingKey).toBe('deck.pptx||1.1.1||slide3')
    expect(posted.payload.file).toBe('deck.pptx')
    expect(posted.payload.ruleId).toBe('1.1.1')
    // appended and the box cleared
    expect(c.querySelectorAll('li.finding-comment').length).toBe(1)
    expect(c.textContent).toContain('needs a person')
    expect(c.querySelector('textarea').value).toBe('')
  })

  it('renders nothing without a finding', async () => {
    const c = await mount({ finding: null })
    expect(c.textContent).toBe('')
  })
})
