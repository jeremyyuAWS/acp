import { afterEach, describe, expect, it } from 'vitest'
import { act, createElement } from 'react'
import WhyFindingsStayWithPeople from './WhyFindingsStayWithPeople.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

const preview = {
  contract_version: 'remediation-automation-policy-preview.v1',
  open: { findings: 5, files: 4 },
  lanes: { automatic: { findings: 1, files: 1 }, review: { findings: 2, files: 2 }, protected: { findings: 2, files: 2 } },
  reasons: [{ reason: 'missing_evidence', findings: 2, files: 1,
    criteria: [{ criterion: '1.1.1', findings: 2, files: 1 }],
    formats: [{ format: 'docx', findings: 2, files: 1 }] }],
  integrity: { open_equals_lane_sum: true, reason_is_mutually_exclusive: true,
    unknown_primary_reason: { findings: 1, files: 1 }, complete: false },
}

async function mount(value) {
  const { container, root } = createTestRoot()
  await act(async () => root.render(createElement(WhyFindingsStayWithPeople, { preview: value })))
  return container
}

describe('WhyFindingsStayWithPeople', () => {
  it('renders exact backend counts and supported WCAG/format drill-downs', async () => {
    const container = await mount(preview)
    expect(container.textContent).toContain('Why 4 findings stay with people')
    expect(container.textContent).toContain('Missing evidence')
    expect(container.textContent).toContain('2 findings across 1 file')
    expect(container.textContent).toContain('WCAG criterion')
    expect(container.textContent).toContain('1.1.1')
    expect(container.textContent).toContain('docx')
    expect(container.textContent).toContain('Reason unavailable')
  })

  it('refuses a response whose open count differs from its lanes', async () => {
    expect((await mount({ ...preview, open: { findings: 99, files: 4 } })).textContent).toBe('')
  })
})
