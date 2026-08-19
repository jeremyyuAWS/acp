import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: RemediationInbox } = await import('./RemediationInbox.jsx')

// Filenames are prefixed a-/b- so the document sort (alphabetical by file, then id) yields a
// stable order for the interaction assertions below. Workflow stages under the top tabs:
//   id1 autoApplied       → Needs review (an unconfirmed auto-fix — the reviewer confirms the change)
//   id2 hasProposal       → Needs review (a fresh AI draft, untouched)
//   id3 manual (no draft) → Manual fixes (needs a human to hand-edit)
const QUEUE = [
  { id: 1, file: 'a-brief.docx', title: 'DOCX · Heading contrast is too low', page: 1, severity: 'SERIOUS', autoApplied: true, before: '#D9D9D9', after: '#2F6FED' },
  { id: 2, file: 'a-brief.docx', title: 'DOCX · Image needs alt text', page: 3, severity: 'CRITICAL', hasProposal: true, after: 'A bar chart of revenue' },
  { id: 3, file: 'b-policy.pdf', title: 'PDF · Scanned page, no text', rule_id: '1.1.1', severity: 'SERIOUS' },
]

let container, root
// The workspace layout + pane sizes persist in localStorage; clear it so each test starts from the
// Stacked default rather than inheriting a previous test's choice.
beforeEach(() => { try { localStorage.clear() } catch {} ;({ container, root } = createTestRoot()) })

// Interaction tests use a deterministic document sort so the queue order is stable;
// the priority-default ordering (critical-first) is covered by remediationInboxModel.test.js.
const render = async (props) => { await act(async () => { root.render(createElement(RemediationInbox, { initialSort: 'document', onOpenWord: () => {}, onRecheck: () => {}, ...props })) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const detailHeading = () => container.querySelector('h3')?.textContent

describe('RemediationInbox — workflow-status queue', () => {
  it('opens on Needs review and shows its first item', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // Needs review holds the unconfirmed auto-fix (id1) and the AI draft (id2); the manual finding
    // (id3) is in Manual fixes. Document sort → id1 first.
    expect(detailHeading()).toBe('Heading contrast is too low')
    expect(container.textContent).toContain('Needs review 2')         // id1 (auto) + id2 (AI draft)
    expect(container.textContent).toContain('Manual fixes 1')         // id3, manual-from-start
    expect(container.textContent).toContain('0 of 3 reviewed')        // progress is a separate lens
  })

  it('partitions findings across the workflow tabs by pipeline stage', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // Manual fixes holds only the manual-from-start finding; the needs-review items are not there.
    await click(btnByText('Manual fixes'))
    expect(detailHeading()).toBe('Scanned page, no text')
  })

  it('selecting a row populates the detail pane instead of expanding in place', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Image needs alt text'))   // id2, in the default Needs review tab
    expect(detailHeading()).toBe('Image needs alt text')
  })

  it('a queue row leads with the issue, shows the SC number as a compact pill, and the lane state quiet', async () => {
    await render({ queue: [{ id: 1, file: 'Clinical-Newsletter-79.docx', title: 'DOCX · Contrast minimum', page: 2, rule_id: '1.4.3', autoApplied: true }], decisions: {} })
    const row = container.querySelector('.rinbox-row')
    expect(row.textContent).toContain('Contrast minimum')             // the issue is the dominant text
    expect(row.textContent).toContain('1.4.3')                        // the compact WCAG pill
    expect(row.textContent).toContain('Automatic fix')                // the lane state, quiet
    expect(row.textContent).not.toContain('Review automatic fix')     // the loud repeated pill is gone
  })

  it('acting on a finding calls onDecide and auto-advances to the next unresolved one', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    await click(btnByText('Image needs alt text'))                   // id2, apply lane
    expect(detailHeading()).toBe('Image needs alt text')
    await click(btnByText('Apply fix'))
    expect(calls).toEqual([[2, 'accepted']])
    // auto-advance moved the workspace to the next unresolved needs-review finding without a click
    expect(detailHeading()).toBe('Heading contrast is too low')      // id1, the remaining auto-fix
  })

  it('a manual finding shows guided steps and native-app actions, not an approve button', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Manual fixes'))                          // id3 lives in Manual fixes now
    await click(btnByText('Scanned page, no text'))
    expect(detailHeading()).toBe('Scanned page, no text')
    expect(container.textContent).toContain('Fix this in Acrobat Pro')  // pdf → Acrobat
    expect(btnByText('Upload & recheck')).toBeTruthy()
  })

  it('an approved finding moves to Awaiting validation; a rejected one to Completed', async () => {
    await render({ queue: QUEUE, decisions: { 2: { state: 'accepted' }, 3: { state: 'rejected' } } })
    expect(container.textContent).toContain('Awaiting validation 1') // id2 (approved), not yet re-scanned
    expect(container.textContent).toContain('Completed 1')           // id3 (rejected → terminal)
    expect(container.textContent).toContain('2 of 3 reviewed')       // id2 + id3 reviewed (id1 auto-fix still needs review)
  })

  it('marks a finding "Not applicable" (out of scope), resolving it without a fix', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push(d) })
    await click(btnByText('Image needs alt text'))               // id2
    await click(btnByText('Not applicable'))
    expect(calls[0].state).toBe('not_applicable')
  })

  it('lets the reviewer edit the AI draft and applies their version (Save edited fix)', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push(d) })
    await click(btnByText('Image needs alt text'))               // id2, apply lane, carries `after`
    expect(detailHeading()).toBe('Image needs alt text')
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
    await click(btnByText('Image needs alt text'))               // id2, apply lane, unresolved
    expect(detailHeading()).toBe('Image needs alt text')
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
    await click(btnByText('Awaiting validation'))                 // where the saved fix now sits
    await click(btnByText('Image needs alt text'))
    expect(container.textContent).toContain('Re-scan')
    expect(container.textContent).toContain('Certified')
  })

  it('Split renders the document preview as a dedicated third pane (three-pane mockup layout)', async () => {
    await render({ queue: QUEUE, decisions: {}, initialLayout: 'split' })
    // Three panes: Remediation Inbox · Guided remediation · Document preview. The finding is reviewed
    // in the guided centre column; the preview lives in its own right-hand pane, NOT folded into an
    // Evidence section of the workspace.
    expect(detailHeading()).toBe('Heading contrast is too low')
    expect(container.textContent).toContain('Guided remediation')
    expect(container.textContent).toContain('Document preview')
    // the preview (its mode tabs) renders — now in the third pane
    const tabLabels = [...container.querySelectorAll('[role=tab]')].map((b) => b.textContent.trim())
    expect(tabLabels).toContain('Visual')
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

  // ── Workspace layout controls: Split / Stacked / Focus + resizable dividers ──
  const layoutBtn = (label) => [...container.querySelectorAll('[role=group][aria-label="Workspace layout"] button')]
    .find((b) => b.textContent.trim() === label)
  const rinbox = () => container.querySelector('.rinbox')
  const sep = (label) => [...container.querySelectorAll('[role=separator]')].find((s) => s.getAttribute('aria-label') === label)

  it('offers a Split / Stacked / Focus layout toggle, defaulting to Stacked (the two-column workspace)', async () => {
    await render({ queue: QUEUE, decisions: {} })
    expect(layoutBtn('Split')).toBeTruthy()
    expect(layoutBtn('Stacked')).toBeTruthy()
    expect(layoutBtn('Focus')).toBeTruthy()
    // Opens in the two-column Stacked workspace — queue beside one column that stacks the guided pane
    // above the document preview. Reviewers can switch to Split/Focus; the choice persists.
    expect(rinbox().getAttribute('data-layout')).toBe('stacked')
    expect(layoutBtn('Stacked').getAttribute('aria-pressed')).toBe('true')
    // Stacked still shows both the guided pane and the document preview, one above the other.
    expect(container.textContent).toContain('Guided remediation')
    expect(container.textContent).toContain('Document preview')
  })

  it('Focus hides the document preview; switching back to Split restores it', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(layoutBtn('Focus'))
    expect(rinbox().getAttribute('data-layout')).toBe('focus')
    expect(container.textContent).not.toContain('Document preview')  // preview pane removed
    expect(container.textContent).toContain('Guided remediation')    // the fix still has the workspace
    await click(layoutBtn('Split'))
    expect(container.textContent).toContain('Document preview')
  })

  it('Stacked keeps both panes and exposes a horizontal resize between them', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(layoutBtn('Stacked'))
    expect(rinbox().getAttribute('data-layout')).toBe('stacked')
    expect(container.textContent).toContain('Guided remediation')
    expect(container.textContent).toContain('Document preview')
    // In Split the preview divider is vertical; in Stacked it is horizontal.
    expect(sep('Resize the document preview').getAttribute('aria-orientation')).toBe('horizontal')
  })

  it('persists the layout choice and restores it on the next mount', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(layoutBtn('Stacked'))
    expect(localStorage.getItem('acp.remediate.layout')).toBe('stacked')
    // A fresh mount (no initialLayout prop) reads the stored preference. Await the teardown — it is
    // async, and a floating unmount rips the DOM out from under the next test.
    await unmountAll()
    ;({ container, root } = createTestRoot())
    await render({ queue: QUEUE, decisions: {} })
    expect(rinbox().getAttribute('data-layout')).toBe('stacked')
  })

  it('dividers are keyboard-resizable (role=separator, Arrow keys change the split)', async () => {
    await render({ queue: QUEUE, decisions: {} })
    const d = sep('Resize the inbox')
    expect(d.getAttribute('aria-orientation')).toBe('vertical')
    const before = Number(d.getAttribute('aria-valuenow'))     // 28 by default
    await act(async () => { d.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    const after = Number(sep('Resize the inbox').getAttribute('aria-valuenow'))
    expect(after).toBeGreaterThan(before)
    // …and the widened inbox width is persisted.
    expect(Number(localStorage.getItem('acp.remediate.leftW'))).toBeGreaterThan(before)
  })
})
