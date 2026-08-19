import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: RemediationInbox } = await import('./RemediationInbox.jsx')

// Filenames are prefixed a-/b- so the document sort (alphabetical by file, then id) yields a
// stable order for the interaction assertions below. Workflow stages under the top tabs:
//   id1 autoApplied       → Ready to validate (the fix is in, awaiting the reviewer)
//   id2 hasProposal       → Inbox (a fresh AI draft, untouched)
//   id3 manual (no draft) → Inbox (fresh, needs a human)
const QUEUE = [
  { id: 1, file: 'a-brief.docx', title: 'DOCX · Heading contrast is too low', page: 1, severity: 'SERIOUS', autoApplied: true, before: '#D9D9D9', after: '#2F6FED' },
  { id: 2, file: 'a-brief.docx', title: 'DOCX · Image needs alt text', page: 3, severity: 'CRITICAL', hasProposal: true, after: 'A bar chart of revenue' },
  { id: 3, file: 'b-policy.pdf', title: 'PDF · Scanned page, no text', rule_id: '1.1.1', severity: 'SERIOUS' },
]

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })

// Interaction tests use a deterministic document sort so the queue order is stable;
// the priority-default ordering (critical-first) is covered by remediationInboxModel.test.js.
const render = async (props) => { await act(async () => { root.render(createElement(RemediationInbox, { initialSort: 'document', onOpenWord: () => {}, onRecheck: () => {}, ...props })) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const detailHeading = () => container.querySelector('h3')?.textContent

describe('RemediationInbox — workflow-status queue', () => {
  it('opens on the Inbox and shows its first untouched finding', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // The auto-applied fix (id1) has moved on to Ready to validate, so the Inbox opens on id2.
    expect(detailHeading()).toBe('Image needs alt text')
    expect(container.textContent).toContain('Inbox 2')                // id2 + id3 untouched
    expect(container.textContent).toContain('Ready to validate 1')    // id1, the applied auto-fix
    expect(container.textContent).toContain('0 of 3 resolved')        // progress is a separate lens
  })

  it('partitions findings across the workflow tabs by pipeline stage', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // Ready to validate holds only the auto-applied fix; the inbox items are not there.
    await click(btnByText('Ready to validate'))
    expect(detailHeading()).toBe('Heading contrast is too low')
  })

  it('selecting a row populates the detail pane instead of expanding in place', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Scanned page, no text'))
    expect(detailHeading()).toBe('Scanned page, no text')
  })

  it('acting on a finding calls onDecide and auto-advances to the next unresolved one', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    expect(detailHeading()).toBe('Image needs alt text')             // id2, apply lane
    await click(btnByText('Apply fix'))
    expect(calls).toEqual([[2, 'accepted']])
    // auto-advance moved the workspace to the next unresolved inbox finding without a click
    expect(detailHeading()).toBe('Scanned page, no text')
  })

  it('a manual finding shows guided steps and native-app actions, not an approve button', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Scanned page, no text'))
    expect(detailHeading()).toBe('Scanned page, no text')
    expect(container.textContent).toContain('Fix this in Acrobat Pro')  // pdf → Acrobat
    expect(btnByText('Upload & recheck')).toBeTruthy()
  })

  it('an approved finding moves to Ready to validate; a rejected one to Done', async () => {
    await render({ queue: QUEUE, decisions: { 2: { state: 'accepted' }, 3: { state: 'rejected' } } })
    expect(container.textContent).toContain('Ready to validate 2')     // id1 (auto) + id2 (approved)
    expect(container.textContent).toContain('Done 1')                  // id3 (rejected → resolved)
    expect(container.textContent).toContain('2 of 3 resolved')         // progress agrees
  })

  it('lets the reviewer edit the AI draft and applies their version (Save edited fix)', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push(d) })
    expect(detailHeading()).toBe('Image needs alt text')          // id2, apply lane, carries `after`
    const ta = container.querySelector('textarea[aria-label="Edit the proposed fix"]')
    expect(ta).toBeTruthy()
    // Edit through the native setter so React's controlled onChange fires.
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    await act(async () => { setValue.call(ta, 'A revenue bar chart, 2021–2025'); ta.dispatchEvent(new Event('input', { bubbles: true })) })
    // Editing flips the primary action to "Save edited fix" and carries the edited value.
    await click(btnByText('Save edited fix'))
    expect(calls[0].state).toBe('accepted')
    expect(calls[0].value).toBe('A revenue bar chart, 2021–2025')
  })

  it('offers specific decision actions (no bare "Reject") and hides verification until a fix is saved', async () => {
    await render({ queue: QUEUE, decisions: {} })
    expect(detailHeading()).toBe('Image needs alt text')          // id2, apply lane, unresolved
    expect(btnByText('Reject & handle manually')).toBeTruthy()    // the specific outcome
    expect(btnByText('Defer')).toBeTruthy()
    // The ambiguous bare "Reject" button is gone.
    const bareReject = [...container.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Reject')
    expect(bareReject).toBe(false)
    // Verification (Written → Re-scan → Certified) is not shown before the decision is saved.
    expect(container.textContent).not.toContain('Re-scan')
  })

  it('shows the verification path (Written → Re-scan → Certified) once a finding is saved', async () => {
    await render({ queue: QUEUE, decisions: { 2: { state: 'accepted' } } })
    await click(btnByText('Ready to validate'))                   // where the saved fix now sits
    await click(btnByText('Image needs alt text'))
    expect(container.textContent).toContain('Re-scan')
    expect(container.textContent).toContain('Certified')
  })

  it('folds the document preview into the workspace as an Evidence section (no separate third pane)', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // The single workspace column carries the issue heading AND the preview (its mode tabs), stacked
    // as Problem → Evidence → How to fix. The old always-mounted third preview pane — and its
    // "Select a finding to see it in the document" empty state — is gone.
    expect(detailHeading()).toBe('Image needs alt text')
    expect(container.textContent).toContain('Evidence')
    const tabLabels = [...container.querySelectorAll('[role=tab]')].map((b) => b.textContent.trim())
    expect(tabLabels).toContain('Visual')
    expect(container.textContent).not.toContain('Select a finding to see it in the document')
  })

  it('search narrows the queue within the current tab', async () => {
    await render({ queue: QUEUE, decisions: {} })
    const input = container.querySelector('input[type=search]')
    // Drive the controlled input through the native value setter so React's onChange fires.
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    await act(async () => { setValue.call(input, 'alt text'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    const rows = [...container.querySelectorAll('.rinbox-row')]
    expect(rows.some((r) => r.textContent.includes('Image needs alt text'))).toBe(true)
    expect(rows.some((r) => r.textContent.includes('Scanned page'))).toBe(false)
  })
})
