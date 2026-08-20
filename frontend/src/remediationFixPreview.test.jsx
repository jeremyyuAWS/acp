import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationFixPreview from './RemediationFixPreview.jsx'

// R4 at the DOM level. The claims under test are the ones that would mislead a reviewer into
// approving something: what the fix mode says, whether the "after" value is real, what the screen
// promises about the customer's drive, and that no decision control appears without a handler
// behind it.

afterEach(unmountAll)

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(RemediationFixPreview, props)) })
  return container
}

const DRAFT = {
  id: 1, file: 'Q3-plan.docx', type: 'docx', rule_id: 'SC_1_1_1', severity: 'SERIOUS', page: 4,
  after: 'Bar chart of Q3 revenue by region',
}
const AUTO_UNDRAFTED = { id: 2, file: 'Q3-plan.docx', type: 'docx', rule_id: 'SC_1_3_1' }

describe('RemediationFixPreview — the four sections', () => {
  it('leads with the plain-language problem and puts the rule identifier below it', async () => {
    const c = await mount({ finding: DRAFT })
    const t = c.textContent
    expect(t).toContain('Problem')
    expect(t).toContain('1.1.1 · Non-text Content')
    expect(t).toContain('SERIOUS')
    expect(t).toContain('Q3-plan.docx')
    expect(t).toContain('Page 4')
    // The rule data is one level down, in a closed disclosure — not on the surface.
    const tech = c.querySelector('details.fixpreview-technical')
    expect(tech).toBeTruthy()
    expect(tech.open).toBe(false)
    expect(tech.textContent).toContain('SC_1_1_1')
  })

  it('renders the evidence through GroundedBeforeAfter rather than a fifth before/after', async () => {
    const c = await mount({ finding: DRAFT })
    expect(c.textContent).toContain('Evidence')
    // GroundedBeforeAfter's own markup — the alt-text branch for a 1.1.1 finding.
    expect(c.querySelector('.ba-evidence')).toBeTruthy()
    expect(c.textContent).toContain('Alt text — after')
  })

  it('states the fix mode explicitly, and what decided it', async () => {
    const c = await mount({ finding: DRAFT })
    expect(c.querySelector('.fixmode-ai-draft')).toBeTruthy()
    expect(c.textContent).toContain('AI draft — review wording')
    expect(c.querySelector('.fixpreview-basis').textContent).toMatch(/drafted value/)
    expect(c.querySelector('.fixpreview-value').textContent).toBe('Bar chart of Q3 revenue by region')
  })

  it('an automatic fix with no computed value says so instead of showing an empty box', async () => {
    const c = await mount({ finding: { ...AUTO_UNDRAFTED, autoApplied: true } })
    expect(c.querySelector('.fixmode-automatic')).toBeTruthy()
    expect(c.querySelector('.fixpreview-value')).toBeNull()
    expect(c.querySelector('.fixpreview-novalue').textContent)
      .toMatch(/computed from the document when the fix runs/)
  })

  it('a guided fix gets the source-application steps, not an approve control', async () => {
    const c = await mount({ finding: AUTO_UNDRAFTED, onApprove: vi.fn() })
    expect(c.querySelector('.fixmode-guided')).toBeTruthy()
    const steps = c.querySelector('.fixpreview-steps')
    expect(steps).toBeTruthy()
    expect(steps.textContent).toContain('macOS')
    expect(steps.textContent).toContain('Windows')
    // onApprove is wired but this mode has no wording to approve, so no primary action renders.
    expect(c.querySelector('.fixpreview-primary')).toBeNull()
  })
})

describe('RemediationFixPreview — what applying it does (ADR 0010)', () => {
  const NEVER = /nothing is written to your drive/i

  it('with the drive mirror ON it names the folder the copy is written into', async () => {
    const c = await mount({ finding: DRAFT, driveMirror: { enabled: true, folder: 'Remediated' } })
    const t = c.textContent
    expect(t).toContain('The original document is not modified.')
    expect(c.querySelector('.fixpreview-dest-drive').textContent)
      .toMatch(/copy is also written to the “Remediated” folder in the source drive/)
    expect(t).not.toMatch(NEVER)
  })

  it('with the setting UNREAD it makes no claim about the drive at all', async () => {
    const c = await mount({ finding: DRAFT })      // driveMirror defaults to null = not read
    const t = c.textContent
    expect(c.querySelector('.fixpreview-dest-drive')).toBeNull()
    expect(t).not.toMatch(NEVER)
    expect(t).not.toMatch(/source drive/)
    expect(t).toMatch(/depends on a platform setting that has not been read yet/)
  })

  it('only with the mirror explicitly OFF does it say the source drive is untouched', async () => {
    const c = await mount({ finding: DRAFT, driveMirror: { enabled: false, folder: 'Remediated' } })
    expect(c.querySelector('.fixpreview-dest-drive').textContent)
      .toMatch(/source drive is not written to/)
  })

  it('a blocked finding gets no destination section — nothing is going to be applied', async () => {
    const c = await mount({
      finding: { ...DRAFT, status: 'blocked' },
      driveMirror: { enabled: true, folder: 'Remediated' },
    })
    expect(c.querySelector('.fixmode-blocked')).toBeTruthy()
    expect(c.textContent).not.toContain('What applying it does')
    expect(c.querySelector('.fixpreview-dest')).toBeNull()
  })
})

describe('RemediationFixPreview — decision controls', () => {
  it('renders no controls at all when the parent wires no handlers', async () => {
    const c = await mount({ finding: DRAFT })
    expect(c.textContent).not.toContain('Decision')
    expect(c.querySelectorAll('button').length).toBe(0)
  })

  it('names the action for the mode, and never offers a generic Approve/Reject pair', async () => {
    const onApprove = vi.fn()
    const c = await mount({ finding: DRAFT, onApprove, onNotApplicable: vi.fn() })
    const labels = [...c.querySelectorAll('button')].map((b) => b.textContent)
    expect(labels).toContain('Approve this wording')
    expect(labels).toContain('Not applicable')
    expect(labels).not.toContain('Approve')
    expect(labels).not.toContain('Reject')
    await act(async () => { c.querySelector('.fixpreview-primary').click() })
    expect(onApprove).toHaveBeenCalled()
  })

  it('an automatic fix gets Apply, a hand-authored one gets Mark resolved manually', async () => {
    const auto = await mount({ finding: { ...AUTO_UNDRAFTED, autoApplied: true }, onApply: vi.fn() })
    expect(auto.querySelector('.fixpreview-primary').textContent).toBe('Apply fix')

    const manual = await mount({
      finding: { id: 3, file: 'a.docx', type: 'docx', rule_id: 'SC_2_1_1' },
      onMarkResolved: vi.fn(),
    })
    expect(manual.querySelector('.fixmode-human')).toBeTruthy()
    expect(manual.querySelector('.fixpreview-primary').textContent).toBe('Mark resolved manually')
  })

  it('a blocked finding is offered no primary action', async () => {
    const c = await mount({
      finding: { ...DRAFT, status: 'blocked' },
      onApply: vi.fn(), onApprove: vi.fn(), onMarkResolved: vi.fn(),
    })
    expect(c.querySelector('.fixpreview-primary')).toBeNull()
  })
})

describe('RemediationFixPreview — applied and verified are separate facts', () => {
  it('a drafted fix claims neither', async () => {
    const c = await mount({ finding: DRAFT })
    expect(c.querySelector('.fixpreview-applied')).toBeNull()
    expect(c.querySelector('.fixpreview-verified')).toBeNull()
  })

  it('an applied fix says written, and does NOT say the re-scan confirmed it', async () => {
    const c = await mount({ finding: { ...DRAFT, autoApplied: true } })
    expect(c.querySelector('.fixpreview-applied').textContent).toMatch(/Written to the corrected copy/)
    expect(c.querySelector('.fixpreview-verified')).toBeNull()
  })

  it('only a verified finding claims the re-scan confirmed it', async () => {
    const c = await mount({ finding: { ...DRAFT, status: 'verified' } })
    expect(c.querySelector('.fixpreview-verified').textContent).toMatch(/Re-scan confirmed it cleared/)
  })
})

describe('RemediationFixPreview — no finding', () => {
  it('is an empty state, not a blank fix card', async () => {
    const c = await mount({ finding: null })
    expect(c.querySelector('.fixpreview-empty')).toBeTruthy()
    expect(c.textContent).toMatch(/Select a finding/)
    expect(c.querySelectorAll('button').length).toBe(0)
  })
})
