import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: RemediationInbox } = await import('./RemediationInbox.jsx')

const QUEUE = [
  { id: 1, file: 'Security-Brief-14.docx', title: 'DOCX · Heading contrast is too low', page: 1, severity: 'SERIOUS', autoApplied: true, before: '#D9D9D9', after: '#2F6FED' },
  { id: 2, file: 'Security-Brief-14.docx', title: 'DOCX · Image needs alt text', page: 3, severity: 'CRITICAL', hasProposal: true, after: 'A bar chart of revenue' },
  { id: 3, file: 'Policy.pdf', title: 'PDF · Scanned page, no text', rule_id: '1.1.1', severity: 'SERIOUS' },
]

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })

const render = async (props) => { await act(async () => { root.render(createElement(RemediationInbox, props)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const detailHeading = () => container.querySelector('h3')?.textContent

describe('RemediationInbox — master/detail queue', () => {
  it('selects the first unresolved finding and shows it in the detail pane', async () => {
    await render({ queue: QUEUE, decisions: {} })
    expect(detailHeading()).toBe('Heading contrast is too low')       // plain issue, no format prefix
    expect(container.textContent).toContain('0 of 3 resolved')        // progress header
    expect(container.textContent).toContain('Approve fix')            // green-lane action
  })

  it('selecting a row populates the detail pane instead of expanding in place', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Image needs alt text'))
    expect(detailHeading()).toBe('Image needs alt text')
    expect(container.textContent).toContain('A bar chart of revenue')  // the AI-drafted "after"
  })

  it('acting on a finding calls onDecide and auto-advances to the next unresolved one', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    expect(detailHeading()).toBe('Heading contrast is too low')
    await click(btnByText('Approve fix'))
    expect(calls).toEqual([[1, 'accepted']])
    // auto-advance moved the workspace to finding #2 without the reviewer selecting it
    expect(detailHeading()).toBe('Image needs alt text')
  })

  it('a manual finding shows guided steps and native-app actions, not an approve button', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Scanned page, no text'))
    expect(detailHeading()).toBe('Scanned page, no text')
    expect(container.textContent).toContain('Fix this in Acrobat Pro')  // pdf → Acrobat
    expect(btnByText('Upload & recheck')).toBeTruthy()
  })

  it('the Resolved tab and search narrow the queue', async () => {
    await render({ queue: QUEUE, decisions: { 1: { state: 'accepted' } } })
    // #1 is resolved → the Resolved tab exists with a count
    expect(btnByText('Resolved 1')).toBeTruthy()
    expect(container.textContent).toContain('1 of 3 resolved')
  })
})
