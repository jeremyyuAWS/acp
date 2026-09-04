import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

// The reviewer's DECISION experience: the redesigned guided pane (decision-first ordering, grounded
// before/after, obvious auto-fix approve/reject) and the copy-bug fix in the preview. Kept in its own
// file so it doesn't collide with RemediationInbox.test.jsx. Rendered WITHOUT a scanId — the
// deterministic, API-free path the inbox tests already rely on.
const { default: RemediationInbox } = await import('./RemediationInbox.jsx')
const { default: RemediationPreview } = await import('./RemediationPreview.jsx')

let container, root
beforeEach(() => { try { localStorage.clear() } catch {} ;({ container, root } = createTestRoot()) })
const renderInbox = async (props) => { await act(async () => { root.render(createElement(RemediationInbox, { initialSort: 'document', onOpenWord: () => {}, ...props })) }) }
const renderPreview = async (props) => { await act(async () => { root.render(createElement(RemediationPreview, props)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const tab = (label) => [...container.querySelectorAll('[role=tab]')].find((b) => b.textContent.trim() === label)

// A docx contrast finding (1.4.3) with NO geometry — no page, locator or thumb. The colours match the
// worked example: #EEEEEE→#767676 is ~1.2:1 → ~4.5:1 on white.
const CONTRAST_APPLY = {
  id: 1, file: 'brief.docx', title: 'DOCX · Heading contrast is too low', rule_id: '1.4.3',
  hasProposal: true, before: '#EEEEEE on #FFFFFF', after: '#767676',
}
const CONTRAST_AUTO = { ...CONTRAST_APPLY, id: 2, hasProposal: false, autoApplied: true }

describe('Preview — the "invisible structure/metadata" copy bug is fixed', () => {
  it('a VISUAL finding with no geometry is NOT labelled "structure or metadata"', async () => {
    await renderPreview({ finding: CONTRAST_APPLY })   // 1.4.3, no page/locator/thumb, no scan
    expect(container.textContent).not.toContain('structure or metadata')
    // It says something honest about lacking coordinates instead.
    expect(container.textContent).toContain('can’t pinpoint this on the page')
    // …and does NOT offer a Structure mode for a visible finding.
    expect(tab('Structure')).toBeFalsy()
  })

  it('a genuinely STRUCTURAL finding keeps its structure framing', async () => {
    await renderPreview({ finding: { id: 9, file: 'annual-report.docx', rule_id: '2.4.2', after: 'Annual Report 2026' } })
    expect(container.textContent).toContain('structure or metadata')
    expect(tab('Structure')).toBeTruthy()
  })

  it('surfaces grounded contrast swatches (real colours + computed ratios) for the contrast finding', async () => {
    await renderPreview({ finding: CONTRAST_APPLY })
    expect(container.textContent).toContain('The quick brown fox')  // the affected text, at each colour
    expect(container.textContent).toContain('#EEEEEE')
    expect(container.textContent).toContain('#767676')
    expect(container.textContent).toContain('1.2:1')
    expect(container.textContent).toContain('4.5:1')
    expect(container.textContent).toContain('Fails')                // before, from the real ratio
    expect(container.textContent).toContain('Passes')               // after
  })
})

describe('Guided pane — decision-first ordering + grounded evidence', () => {
  it('keeps the decision actions directly after the detail instead of pinning them below empty space', async () => {
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: {} })
    const detail = container.querySelector('.remediation-detail')
    const content = container.querySelector('.remediation-detail-content')
    const actions = container.querySelector('.remediation-detail-actions')
    expect(detail).toBeTruthy()
    expect(content?.nextElementSibling).toBe(actions)
    expect(detail.style.height).toBe('')
    expect(content.style.flex).toBe('')
    expect(content.style.overflowY).toBe('')
  })

  it('orders the pane Your task → Current / Proposed → Why this matters, with evidence collapsed', async () => {
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: {} })
    const text = container.textContent
    const iTask = text.indexOf('Your task')
    const iCurrent = text.indexOf('Current')
    const iWhy = text.indexOf('Why this matters')
    expect(iTask).toBeGreaterThan(-1)
    expect(iCurrent).toBeGreaterThan(iTask)
    expect(iWhy).toBeGreaterThan(iCurrent)
    const evDetails = [...container.querySelectorAll('details')]
      .find((d) => d.querySelector('summary')?.textContent.includes('Detection'))
    expect(evDetails).toBeTruthy()
    expect(evDetails.open).toBe(false)
    expect(text).not.toContain('Issue found')
  })

  it('the task line is plain, imperative and criterion-aware (a contrast decision)', async () => {
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: {} })
    expect(container.textContent).toContain('Review ACP’s contrast fix')      // criterion-aware
    expect(container.textContent).toContain('apply it')                        // imperative, apply lane
  })

  it('shows full-width current/proposed rows and a plain change sentence with the real values', async () => {
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: {} })
    expect(container.querySelector('.remediation-comparison')).toBeTruthy()
    expect(container.textContent).toContain('Current')
    expect(container.textContent).toContain('Proposed')
    expect(container.textContent).toContain('Text color changed from #EEEEEE to #767676')
    expect(container.textContent).toContain('Contrast increased from 1.2:1 to 4.5:1')
    expect(container.textContent).toContain('No text or layout changed')
  })
})

describe('Guided pane — preserves the #412/#415 behaviours', () => {
  it('keeps the editable draft (Save edited fix) on an AI-drafted fix', async () => {
    const calls = []
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: {}, onDecide: (f, d) => calls.push(d) })
    const ta = container.querySelector('textarea[aria-label="Edit the proposed fix"]')
    expect(ta).toBeTruthy()
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    await act(async () => { setValue.call(ta, '#595959'); ta.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(btnByText('Save edited fix'))
    expect(calls[0].state).toBe('accepted')
    expect(calls[0].value).toBe('#595959')
  })

  it('hides verification until saved, then shows Written → Re-scan → Certified', async () => {
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: {} })
    expect(container.textContent).not.toContain('Re-scan')                    // capital-R only after save
    await unmountAll(); ({ container, root } = createTestRoot())
    await renderInbox({ queue: [CONTRAST_APPLY], decisions: { 1: { state: 'accepted' } } })
    await click(btnByText('Awaiting verification'))
    await click(btnByText('Heading contrast is too low'))
    expect(container.textContent).toContain('Re-scan')
    expect(container.textContent).toContain('Certified')
  })
})

describe('Guided pane — auto-fix rows get an obvious, honestly-labelled decision', () => {
  it('offers "Approve & next" and a "This looks wrong" flag (no editable draft)', async () => {
    const calls = []
    // An UNacknowledged auto-fix awaits the reviewer's confirmation, so it sits in Needs review (the
    // default tab) — not Awaiting validation — and is selected on open.
    await renderInbox({ queue: [CONTRAST_AUTO], decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    expect(btnByText('Approve & next \u2192')).toBeTruthy()
    expect(btnByText('This looks wrong')).toBeTruthy()
    // The change is already applied — there is no edit-and-apply draft for it.
    expect(container.querySelector('textarea[aria-label="Edit the proposed fix"]')).toBeNull()
    await click(btnByText('Approve & next \u2192'))
    expect(calls).toContainEqual([2, 'accepted'])
  })

  it('the "This looks wrong" flag routes through onDecide as a rejection', async () => {
    const calls = []
    await renderInbox({ queue: [CONTRAST_AUTO], decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    await click(btnByText('This looks wrong'))
    expect(calls).toContainEqual([2, 'rejected'])
  })
})
