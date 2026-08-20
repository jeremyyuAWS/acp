/**
 * R5, rendered — the approval queue's five refusals.
 *
 *   · it renders nothing before the queue has loaded, never "0 drafts awaiting approval";
 *   · it shows the draft ITSELF, because a reviewer who cannot see the change cannot approve it;
 *   · it offers no Approve button on a row with no draft;
 *   · it offers no bulk approve, ever;
 *   · approving an unedited draft sends null rather than re-sending text nobody changed, and
 *     approving an edited one is flagged as edited.
 *
 * DOM assertions under vitest. The preview server's vite root is the shared checkout whatever
 * worktree it runs from, so a browser check of these changes would exercise code without them.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationApprovals from './RemediationApprovals.jsx'

afterEach(unmountAll)

const row = (over = {}) => ({
  id: 'q1', scan_id: 's', file: 'a.docx', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1, page: 2, ...over,
})
const DRAFT = 'Bar chart: quarterly revenue rising from £4.1m to £5.8m.'
const drafted = (over = {}) => row({
  proposals: [{ proposed_value: DRAFT, before: 'image, no alt text',
                rationale: 'read from the chart axes' }],
  ...over,
})

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(RemediationApprovals, props)) })
  return container
}

const text = (c) => c.textContent.replace(/\s+/g, ' ')
const buttons = (c) => [...c.querySelectorAll('button')].map((b) => b.textContent.trim())
const click = async (c, label) => {
  const b = [...c.querySelectorAll('button')].find((x) => x.textContent.trim() === label)
  await act(async () => { b.click() })
}

describe('nothing, rather than an empty queue', () => {
  it('renders nothing before the queue has loaded', async () => {
    expect((await mount({ items: null })).textContent).toBe('')
    expect((await mount({ items: undefined })).textContent).toBe('')
  })

  it('says the queue is really empty when it really is', async () => {
    const c = await mount({ items: [] })
    expect(text(c)).toContain('No draft is waiting for a decision')
  })
})

describe('the draft is on the row', () => {
  it('shows the model’s actual words, in full', async () => {
    const c = await mount({ items: [drafted()], onApprove: () => {} })
    expect(text(c)).toContain(DRAFT)
  })

  it('shows the passage the fix would replace, and where it is', async () => {
    const c = await mount({ items: [drafted()], onApprove: () => {} })
    const t = text(c)
    expect(t).toContain('now: image, no alt text')
    expect(t).toContain('1.1.1 Non-text Content')
    expect(t).toContain('a.docx')
    expect(t).toContain('page 2')
  })

  it('says how many values one Approve press would accept', async () => {
    const c = await mount({
      items: [drafted({ proposals: [{ proposed_value: 'one' }, { proposed_value: 'two' },
                                    { proposed_value: 'three' }] })],
      onApprove: () => {},
    })
    expect(text(c)).toContain('This row carries 3 drafts')
    expect(text(c)).toContain('Approving accepts all 3')
  })
})

describe('a row with no draft gets no Approve button', () => {
  it('separates them and says nothing was generated', async () => {
    const c = await mount({ items: [row({ id: 'none' })], onApprove: () => {} })
    const t = text(c)
    expect(t).toContain('1 finding in this queue with no draft')
    expect(t).toContain('nothing to approve')
    expect(buttons(c)).toEqual([])
  })

  it('offers approval for the drafted row only when both are present', async () => {
    const c = await mount({ items: [drafted({ id: 'yes' }), row({ id: 'no', rule_id: '1.4.3' })],
                            onApprove: () => {} })
    expect(buttons(c)).toEqual(['Approve', 'Edit'])
  })
})

describe('there is no bulk approve', () => {
  it('offers one control set per row and no all-at-once action', async () => {
    const c = await mount({ items: [drafted({ id: 'a' }), drafted({ id: 'b', file: 'b.docx' })],
                            onApprove: () => {} })
    expect(buttons(c)).toEqual(['Approve', 'Edit', 'Approve', 'Edit'])
    expect(text(c)).not.toMatch(/approve all/i)
    expect(text(c)).toContain('there is no bulk approve')
  })

  it('states that a draft is never applied without an explicit approval', async () => {
    const c = await mount({ items: [drafted()], onApprove: () => {} })
    const t = text(c)
    expect(t).toContain('A draft is never applied without an explicit approval')
    expect(t).toContain('an AI draft is advice, not automation')
  })
})

describe('approving says exactly what the reviewer did', () => {
  it('sends null for an untouched draft, and does not flag it as edited', async () => {
    const calls = []
    const c = await mount({ items: [drafted()], onApprove: (...a) => calls.push(a) })
    await click(c, 'Approve')
    expect(calls).toEqual([['q1', null, { edited: false }]])
  })

  it('sends the reviewer’s wording and flags it as edited', async () => {
    const calls = []
    const c = await mount({ items: [drafted()], onApprove: (...a) => calls.push(a) })
    await click(c, 'Edit')
    const ta = c.querySelector('textarea')
    expect(ta.value).toBe(DRAFT)
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
      setter.call(ta, 'A person wrote this instead.')
      ta.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click(c, 'Approve my wording')
    expect(calls).toEqual([['q1', 'A person wrote this instead.', { edited: true }]])
  })

  it('does not claim an edit when the reviewer opened the box and changed nothing', async () => {
    const calls = []
    const c = await mount({ items: [drafted()], onApprove: (...a) => calls.push(a) })
    await click(c, 'Edit')
    await click(c, 'Approve my wording')
    // `edited` is the only honest signal anyone has about how good the drafts are. Opening the box
    // must not corrupt it.
    expect(calls).toEqual([['q1', null, { edited: false }]])
  })

  it('renders no Reject control unless the parent can perform it', async () => {
    const c = await mount({ items: [drafted()], onApprove: () => {} })
    expect(buttons(c)).not.toContain('Reject')
    const c2 = await mount({ items: [drafted()], onApprove: () => {}, onReject: () => {} })
    expect(buttons(c2)).toContain('Reject')
  })

  it('disables a row’s controls while its decision is being written', async () => {
    const c = await mount({ items: [drafted()], onApprove: () => {}, busyId: 'q1' })
    expect([...c.querySelectorAll('button')].every((b) => b.disabled)).toBe(true)
    expect(text(c)).toContain('writing…')
  })
})

describe('the queue’s own arithmetic is printed', () => {
  it('shows the three-way split and its total', async () => {
    const c = await mount({
      items: [drafted({ id: 'a' }), row({ id: 'b' }), drafted({ id: 'c', status: 'approved' })],
      onApprove: () => {},
    })
    expect(text(c)).toContain('1 awaiting approval + 1 with no draft + 1 already decided = 3 queue items')
  })
})
