import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)
const { default: RemediationTransform } = await import('./RemediationTransform.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(RemediationTransform, props)) }) }

// Lanes: hasProposal → apply (not applied yet), autoApplied → review (applied + re-scanned).
const PROPOSED = { id: 1, file: 'a.docx', hasProposal: true, before: '2.4:1 contrast', after: 'Darken to #595959' }
const AUTO = { id: 2, file: 'a.docx', autoApplied: true, before: '#D9D9D9', after: '#2F6FED' }

describe('RemediationTransform — Found → Proposed → Verified', () => {
  it('renders nothing when there is no proposed value (caller falls back to text)', async () => {
    await render({ finding: { id: 3, file: 'a.docx' } })
    expect(container.textContent.trim()).toBe('')
  })

  it('shows the found value, the proposed change, and all three stage labels', async () => {
    await render({ finding: PROPOSED })
    expect(container.textContent).toContain('Issue found')
    expect(container.textContent).toContain('2.4:1 contrast')
    expect(container.textContent).toContain('Proposed fix')
    expect(container.textContent).toContain('Darken to #595959')
  })

  it('is HONEST about the result: an un-applied AI draft "Passes on re-scan", not a fabricated pass', async () => {
    await render({ finding: PROPOSED })
    expect(container.textContent).toContain('Expected result')
    expect(container.textContent).toContain('Passes on re-scan')
    expect(container.textContent).not.toContain('Verified result')
  })

  it('an applied auto-fix reads Verified · Pass', async () => {
    await render({ finding: AUTO })
    expect(container.textContent).toContain('Verified result')
    expect(container.textContent).toContain('Pass')
    expect(container.textContent).not.toContain('Passes on re-scan')
  })

  it('a resolved proposal also reads Verified (a decision applied it)', async () => {
    await render({ finding: PROPOSED, decisions: { 1: { state: 'accepted' } } })
    expect(container.textContent).toContain('Verified result')
  })

  it('falls back to "Flagged" when there is no before value', async () => {
    await render({ finding: { id: 4, file: 'a.docx', hasProposal: true, after: 'Alt text' } })
    expect(container.textContent).toContain('Flagged')
    expect(container.textContent).toContain('Alt text')
  })
})
