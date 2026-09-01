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
// two-panel default rather than inheriting a previous test's choice.
beforeEach(() => { try { localStorage.clear() } catch {} ;({ container, root } = createTestRoot()) })

// Interaction tests use a deterministic document sort so the queue order is stable;
// the priority-default ordering (critical-first) is covered by remediationInboxModel.test.js.
const render = async (props) => { await act(async () => { root.render(createElement(RemediationInbox, { initialSort: 'document', onOpenWord: () => {}, onRecheck: () => {}, ...props })) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const detailHeading = () => container.querySelector('h3')?.textContent

describe('RemediationInbox — workflow-status queue', () => {

  // ── A decision is not made until it is SAVED (PRD §5.8) ──────────────────────────────────────
  // The failure mode these cover is specific and was real: `onDecide` was fire-and-forget, so a
  // server refusal still auto-advanced the reviewer, and the only signal was a banner rendered
  // outside this component. A reviewer working the queue at speed would never see it.

  it('does NOT advance when the decision fails to save, and says so where they pressed', async () => {
    const seen = []
    await render({ queue: QUEUE, decisions: {},
      onDecide: (f, d) => { seen.push([f.id, d.state]); return Promise.reject(new Error('The server rejected it.')) } })
    expect(detailHeading()).toBe('Heading contrast is too low')     // id1
    await click(btnByText('Approve & next \u2192'))
    expect(seen).toEqual([[1, 'accepted']])
    // Still on the SAME finding — the queue did not move on.
    expect(detailHeading()).toBe('Heading contrast is too low')
    // …and the failure is stated inline, in an alert, next to the buttons that failed.
    const alert = container.querySelector('[role=alert]')
    expect(alert).toBeTruthy()
    expect(alert.textContent).toContain('Not saved.')
    expect(alert.textContent).toContain('The server rejected it.')
    expect(alert.textContent).toContain('still waiting for your decision')
    // The decision controls are live again so the reviewer can retry.
    expect(btnByText('Approve & next \u2192').disabled).toBe(false)
  })

  it('advances and shows no error when the decision saves', async () => {
    await render({ queue: QUEUE, decisions: {}, onDecide: () => Promise.resolve() })
    await click(btnByText('Approve & next \u2192'))
    expect(detailHeading()).toBe('Image needs alt text')            // moved to id2
    expect(container.querySelector('[role=alert]')).toBeNull()
  })

  it('clears a failed decision\u2019s error when the reviewer moves to another finding', async () => {
    await render({ queue: QUEUE, decisions: {}, onDecide: () => Promise.reject(new Error('nope')) })
    await click(btnByText('Approve & next \u2192'))
    expect(container.querySelector('[role=alert]')).toBeTruthy()
    await click(btnByText('Image needs alt text'))
    // The message belonged to that decision, not to the page.
    expect(container.querySelector('[role=alert]')).toBeNull()
  })

  // ── Batch decisions are scoped and named (PRD §6) ────────────────────────────────────────────

  it('names the criterion and the exact number of OTHER findings a batch would cover', async () => {
    // Two unresolved 1.1.1 findings in actionable lanes, plus a manual one that must NOT be swept in.
    const q = [
      { id: 10, file: 'a.docx', title: 'DOCX \u00b7 Image needs alt text', rule_id: '1.1.1', hasProposal: true, after: 'A chart' },
      { id: 11, file: 'b.docx', title: 'DOCX \u00b7 Image needs alt text', rule_id: '1.1.1', hasProposal: true, after: 'A photo' },
      { id: 12, file: 'c.pdf', title: 'PDF \u00b7 Scanned page, no text', rule_id: '1.1.1' },   // manual — excluded
    ]
    await render({ queue: q, decisions: {} })
    const batch = btnByText('Approve this decision for')
    expect(batch).toBeTruthy()
    // ONE other actionable finding, not two — the manual one is not batchable.
    expect(batch.textContent).toContain('Approve this decision for 1 other WCAG 1.1.1 finding')
    expect(container.textContent).toContain('manual, blocked and already-decided findings are excluded')
  })

  it('offers no global \u201capprove all AI drafts\u201d control anywhere', async () => {
    await render({ queue: QUEUE, decisions: {} })
    const labels = [...container.querySelectorAll('button')].map((b) => b.textContent.trim())
    // Every batch control must name its scope; none may sweep the whole queue.
    expect(labels.some((l) => /^Approve all\b/i.test(l))).toBe(false)
    expect(labels.some((l) => /approve all (ai )?drafts/i.test(l))).toBe(false)
    expect(labels.some((l) => /^(Approve|Accept) everything/i.test(l))).toBe(false)
  })

  it('reports a partial batch failure instead of claiming the whole cluster landed', async () => {
    const q = [
      { id: 20, file: 'a.docx', title: 'DOCX \u00b7 Image needs alt text', rule_id: '1.1.1', hasProposal: true, after: 'A chart' },
      { id: 21, file: 'b.docx', title: 'DOCX \u00b7 Image needs alt text', rule_id: '1.1.1', hasProposal: true, after: 'A photo' },
    ]
    // The second write is refused; the first succeeds.
    await render({ queue: q, decisions: {},
      onDecide: (f) => (f.id === 21 ? Promise.reject(new Error('conflict')) : Promise.resolve()) })
    await click(btnByText('Approve this decision for'))
    const alert = container.querySelector('[role=alert]')
    expect(alert).toBeTruthy()
    expect(alert.textContent).toContain('1 of 2 saved')
    expect(alert.textContent).toContain('1 could not be saved')
    // Selection sits on the finding that failed, not past the whole cluster.
    expect(detailHeading()).toBe('Image needs alt text')
  })

  // ── Narrow viewports show one panel at a time (PRD §12) ──────────────────────────────────────

  it('at a narrow width shows the queue OR the finding, with a way back', async () => {
    // jsdom has no matchMedia; stub one that reports narrow so the component takes that branch.
    const real = window.matchMedia
    window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
    try {
      await render({ queue: QUEUE, decisions: {} })
      const rinbox = () => container.querySelector('.rinbox')
      const queuePane = () => container.querySelector('.rinbox-queuepane')
      const workspace = () => container.querySelector('.rinbox-workspace')
      expect(rinbox().getAttribute('data-narrow')).toBe('queue')
      // Both panels are never squeezed side by side. The review side stays MOUNTED (so the
      // selection and any unsaved edit survive the trip) but is `hidden`, which takes it out of
      // the accessibility tree and the tab order rather than merely shrinking it.
      expect(queuePane().hidden).toBe(false)
      expect(workspace().hidden).toBe(true)
      // No resizer either — there is nothing on screen to resize against.
      expect([...container.querySelectorAll('[role=separator]')]
        .some((n) => n.getAttribute('aria-label') === 'Resize the inbox')).toBe(false)
      await click(btnByText('Image needs alt text'))          // choosing a finding navigates to it
      expect(rinbox().getAttribute('data-narrow')).toBe('detail')
      expect(queuePane().hidden).toBe(true)
      expect(workspace().hidden).toBe(false)
      expect(detailHeading()).toBe('Image needs alt text')
      const back = btnByText('Back to queue')
      expect(back).toBeTruthy()
      await click(back)
      expect(rinbox().getAttribute('data-narrow')).toBe('queue')
      // The preview toggle is not offered — a third pane cannot help where two do not fit.
      expect(btnByText('Full document preview')).toBeFalsy()
    } finally {
      if (real) window.matchMedia = real; else delete window.matchMedia
    }
  })
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
    await click(btnByText('Approve & next \u2192'))
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
    expect(btnByText('Reject \u2192 manual')).toBeTruthy()          // the specific outcome
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

  // ── The default workspace is TWO panels; the document preview is opened on demand ──
  const previewToggle = () => [...container.querySelectorAll('button')]
    .find((b) => b.textContent.trim().replace(/^\u2715\s*/, '') === 'Full document preview')
  const placeBtn = (label) => [...container.querySelectorAll('[role=group][aria-label="Preview placement"] button')]
    .find((b) => b.textContent.trim() === label)
  const rinbox = () => container.querySelector('.rinbox')
  const sep = (label) => [...container.querySelectorAll('[role=separator]')].find((s) => s.getAttribute('aria-label') === label)

  it('defaults to a two-panel workspace — queue and review, with no third preview pane', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // 'focus' is the preview being CLOSED. The reviewer gets the queue and the review canvas and
    // nothing to configure before they can make a decision.
    expect(rinbox().getAttribute('data-layout')).toBe('focus')
    expect(container.textContent).toContain('Guided remediation')
    expect(container.textContent).not.toContain('Document preview')
    // No layout picker in the default view — one toggle, not three modes to choose between.
    expect(container.querySelector('[role=group][aria-label="Workspace layout"]')).toBeNull()
    expect(previewToggle()).toBeTruthy()
    expect(previewToggle().getAttribute('aria-pressed')).toBe('false')
  })

  it('"Full document preview" opens the third pane on demand and closes it again', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(previewToggle())
    expect(container.textContent).toContain('Document preview')
    expect(previewToggle().getAttribute('aria-pressed')).toBe('true')
    expect(rinbox().getAttribute('data-layout')).toBe('split')
    await click(previewToggle())
    expect(container.textContent).not.toContain('Document preview')
    expect(rinbox().getAttribute('data-layout')).toBe('focus')
  })

  it('opening the full preview preserves the selected finding and an unsaved edit', async () => {
    // PRD §8/§16: the preview is a disclosure, not a context switch. The guided column keeps its
    // place in the element tree across the toggle, so React reconciles rather than remounting it.
    await render({ queue: QUEUE, decisions: {} })
    await click(btnByText('Image needs alt text'))
    const ta = container.querySelector('textarea[aria-label="Edit the proposed fix"]')
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    await act(async () => { setValue.call(ta, 'A reviewer wrote this'); ta.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(previewToggle())            // open the full preview mid-decision
    expect(detailHeading()).toBe('Image needs alt text')
    expect(container.querySelector('textarea[aria-label="Edit the proposed fix"]').value).toBe('A reviewer wrote this')
    await click(previewToggle())            // and back
    expect(detailHeading()).toBe('Image needs alt text')
    expect(container.querySelector('textarea[aria-label="Edit the proposed fix"]').value).toBe('A reviewer wrote this')
  })

  it('the opened preview can be placed beside or below, and keeps a keyboard-operable divider', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(previewToggle())
    expect(sep('Resize the document preview').getAttribute('aria-orientation')).toBe('vertical')
    await click(placeBtn('Stacked'))
    expect(rinbox().getAttribute('data-layout')).toBe('stacked')
    expect(sep('Resize the document preview').getAttribute('aria-orientation')).toBe('horizontal')
    // The guided detail can outgrow its pane (status summary, audit trail) and must scroll inside it
    // rather than painting over the preview.
    const guided = container.querySelector('.rinbox-guided-scroll')
    expect(guided.style.overflowY).toBe('auto')
    expect(guided.style.overflowX).toBe('hidden')
  })

  it('persists the preview choice and restores it on the next mount', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await click(previewToggle())
    await click(placeBtn('Stacked'))
    expect(localStorage.getItem('acp.remediate.layout')).toBe('stacked')
    // A fresh mount (no initialLayout prop) reads the stored preference. Await the teardown — it is
    // async, and a floating unmount rips the DOM out from under the next test.
    await unmountAll()
    ;({ container, root } = createTestRoot())
    await render({ queue: QUEUE, decisions: {} })
    expect(rinbox().getAttribute('data-layout')).toBe('stacked')
    // Reopening after closing returns to the placement the reviewer last used, not the default.
    await click(previewToggle())
    expect(rinbox().getAttribute('data-layout')).toBe('focus')
    await click(previewToggle())
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

  // ── "Assigned to me" filter (#417 backend: per-file assignee) ──
  const hasBtn = (t) => [...container.querySelectorAll('button')].some((b) => b.textContent.includes(t))

  it('shows the "Assigned to me" control only when a signed-in reviewer + assign action are wired', async () => {
    await render({ queue: QUEUE, decisions: {} })                    // no myEmail / onAssign → dead control avoided
    expect(hasBtn('Assigned to me')).toBe(false)
    await render({ queue: QUEUE, decisions: {}, myEmail: 'me@x.com', onAssign: () => {} })
    expect(hasBtn('Assigned to me')).toBe(true)
  })

  it('assigns the selected document to the reviewer via onAssign(file, myEmail)', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, myEmail: 'me@x.com', onAssign: (f, e) => calls.push([f, e]) })
    // Default selection is id1 (a-brief.docx), unassigned → the chip offers "+ Assign to me".
    await click(btnByText('Assign to me'))
    expect(calls).toEqual([['a-brief.docx', 'me@x.com']])
  })

  it('"Assigned to me" narrows the queue to documents assigned to the reviewer', async () => {
    const Q = [
      { id: 1, file: 'a.docx', title: 'DOCX · Alpha', hasProposal: true, after: 'x' },   // needs-review, assigned
      { id: 2, file: 'b.docx', title: 'DOCX · Beta', hasProposal: true, after: 'y' },     // needs-review, NOT assigned
    ]
    await render({ queue: Q, decisions: {}, myEmail: 'me@x.com', assignees: { 'a.docx': 'me@x.com' }, onAssign: () => {} })
    let rows = [...container.querySelectorAll('.rinbox-row')].map((r) => r.textContent)
    expect(rows.some((t) => t.includes('Alpha'))).toBe(true)
    expect(rows.some((t) => t.includes('Beta'))).toBe(true)
    await click(btnByText('Assigned to me'))                          // "Assigned to me (1)"
    rows = [...container.querySelectorAll('.rinbox-row')].map((r) => r.textContent)
    expect(rows.some((t) => t.includes('Alpha'))).toBe(true)          // assigned → stays
    expect(rows.some((t) => t.includes('Beta'))).toBe(false)          // unassigned → filtered out
  })

  it('shows an honest empty state when nothing in view is assigned to the reviewer', async () => {
    await render({ queue: QUEUE, decisions: {}, myEmail: 'me@x.com', assignees: {}, onAssign: () => {} })
    await click(btnByText('Assigned to me'))
    expect(container.textContent).toContain('Nothing in this view is assigned to you')
    expect(btnByText('Show all')).toBeTruthy()
  })

  // ── Keyboard + screen-reader accessibility of the review queue ──
  const liveRegion = () => container.querySelector('[aria-live="polite"]')
  const queueList = () => container.querySelector('[aria-label^="Findings"]')
  const key = async (el, k) => { await act(async () => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true })) }) }

  it('announces the selected finding and its N-of-M place in a polite live region', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // Needs review holds id1 (auto-fix) + id2 (AI draft); document sort → id1 first.
    expect(liveRegion().getAttribute('role')).toBe('status')
    expect(liveRegion().textContent).toContain('Finding 1 of 2')
    expect(liveRegion().textContent).toContain('Heading contrast is too low')
    expect(liveRegion().textContent).toContain('a-brief.docx')
  })

  it('uses a roving tabindex — only the selected row is a Tab stop', async () => {
    await render({ queue: QUEUE, decisions: {} })
    const rows = [...container.querySelectorAll('.rinbox-row')]
    expect(rows.find((r) => r.getAttribute('aria-current') === 'true').tabIndex).toBe(0)
    expect(rows.find((r) => r.getAttribute('aria-current') !== 'true').tabIndex).toBe(-1)
  })

  it('ArrowDown moves the selection to the next finding and re-announces it', async () => {
    await render({ queue: QUEUE, decisions: {} })
    expect(detailHeading()).toBe('Heading contrast is too low')       // id1
    await key(queueList(), 'ArrowDown')
    expect(detailHeading()).toBe('Image needs alt text')              // id2
    expect(liveRegion().textContent).toContain('Finding 2 of 2')
  })

  it('keyboard navigation (j/k) moves focus to the newly-selected row', async () => {
    await render({ queue: QUEUE, decisions: {} })
    await key(queueList(), 'j')                                        // vim-style down
    const focused = container.querySelector('[aria-current="true"]')
    expect(document.activeElement).toBe(focused)
    expect(focused.textContent).toContain('Image needs alt text')     // advanced to id2
  })

  // ── Adaptive evidence per finding type (alt text, metadata) in the decision pane ──
  it('shows alt-text evidence (old → new alt) for a 1.1.1 finding', async () => {
    await render({ queue: [{ id: 1, file: 'a.docx', title: 'DOCX · Image needs alt text', rule_id: '1.1.1', hasProposal: true, before: '', after: 'A bar chart of Q3 revenue' }], decisions: {} })
    expect(container.textContent).toContain('Alt text — before')
    expect(container.textContent).toContain('(no alt text)')          // the missing alt IS the defect
    expect(container.textContent).toContain('Alt text — after')
    expect(container.textContent).toContain('A bar chart of Q3 revenue')
  })

  it('shows a metadata before/after for a document-title (2.4.2) finding', async () => {
    await render({ queue: [{ id: 1, file: 'a.docx', title: 'DOCX · Document has no title', rule_id: '2.4.2', hasProposal: true, before: null, after: 'Q3 Report' }], decisions: {} })
    expect(container.textContent).toContain('Document title — before')
    expect(container.textContent).toContain('(not set)')
    expect(container.textContent).toContain('Document title — after')
    expect(container.textContent).toContain('Q3 Report')
  })

  it('shows a numbered reading-order sequence for a 1.3.2 finding', async () => {
    await render({ queue: [{ id: 1, file: 'a.docx', title: 'DOCX · Meaningful sequence', rule_id: '1.3.2', hasProposal: true, after: 'x',
      proposals: [{ seq: 1, text: 'Pull quote at the top' }, { seq: 2, text: 'Sidebar callout' }] }], decisions: {} })
    const ol = container.querySelector('ol')
    expect(ol).toBeTruthy()                                     // a real ordered list, not the generic note
    expect(ol.querySelectorAll('li').length).toBe(2)
    expect(ol.textContent).toContain('Pull quote at the top')
    expect(ol.textContent).toContain('Sidebar callout')
  })
})
