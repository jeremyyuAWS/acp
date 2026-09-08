import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement, act } from 'react'
import axe from 'axe-core'
import RemediationImpactCard from './RemediationImpactCard.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
import { getRemediationImpact, saveRemediationImpactPolicy, assignRemediationImpact } from './api.js'
vi.mock('./api.js', () => ({ getRemediationImpact: vi.fn(), saveRemediationImpactPolicy: vi.fn(), assignRemediationImpact: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const result = (policy = { rule_based: 2, ai: 1 }) => ({
  policy, active_policy: { rule_based: 0, ai: 1, revision: 4 }, open: { findings: 7, files: 3 },
  lanes: { automatic: { findings: policy.rule_based === 0 ? 0 : 4, files: 2, delta: 4 }, review: { findings: 2, files: 1, delta: -4 }, manual: { findings: 1, files: 1, delta: 0 }, blocked: { findings: 0, files: 0, delta: 0 } },
  active_lanes: { automatic: { findings: 0 }, review: { findings: 6 }, manual: { findings: 1 }, blocked: { findings: 0 } },
  file_outlook: { could_complete: { files: 1 }, human_work: { files: 2 }, blocked_incomplete: { files: 0 }, unavailable: { files: 0 } },
  files: [{ file: 'A.docx', findings: 3, automatic: 3, review: 0, manual: 0, blocked: 0, outlook: 'could_complete' }, { file: 'C.docx', findings: 2, automatic: 1, review: 0, manual: 1, blocked: 0, outlook: 'human_work' }],
  findings: [{ file: 'C.docx', lane: 'manual', primary_reason: 'human_judgment' }], integrity: { complete: true }, capabilities: { execute: true, save_future: true, assign: true, ai_automatic: false },
})
async function mount(props = {}) { const { container, root } = createTestRoot(); await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', ...props }))); return { container, root } }
const button = (container, label) => [...container.querySelectorAll('button')].find(node => node.textContent === label)
beforeEach(() => { vi.clearAllMocks(); getRemediationImpact.mockImplementation(async (_id, policy) => result(policy || undefined)); saveRemediationImpactPolicy.mockResolvedValue({}) })
afterEach(unmountAll)
describe('RemediationImpactCard', () => {
  it('shows full population, explicit sliders and file outlooks', async () => {
    const { container } = await mount()
    expect(container.textContent).toContain('7 unresolved findings across 3 files')
    expect(container.textContent).toContain('Affected-file counts overlap')
    expect(container.textContent).toContain('Each file appears in one outlook')
    expect(container.querySelectorAll('input[type=range]')).toHaveLength(2)
    expect(container.textContent).toContain('Unavailable: Validated drafts · Eligible drafts')
    expect(container.textContent).toContain('Automatic application of AI proposals is not available')
  })
  it('previews without execution and separates run, reset and future defaults', async () => {
    const onRun = vi.fn(); const { container } = await mount({ onRun })
    await act(async () => button(container, 'Review first').click())
    expect(getRemediationImpact).toHaveBeenLastCalledWith('run-1', { rule_based: 0, ai: 1 }, undefined)
    expect(onRun).not.toHaveBeenCalled()
    await act(async () => button(container, 'Eligible fixes').click())
    await act(async () => button(container, 'Save as default for future runs').click())
    expect(saveRemediationImpactPolicy).toHaveBeenCalledWith('run-1', { rule_based: 2, ai: 1 }, 4)
    expect(onRun).not.toHaveBeenCalled()
    await act(async () => button(container, 'Run remediation with these settings').click())
    expect(onRun).toHaveBeenCalledWith({ rule_based: 2, ai: 1 }, expect.objectContaining({ open: { findings: 7, files: 3 } }))
    await act(async () => button(container, 'Reset to active').click())
    expect(container.querySelector('input[type=range]').value).toBe('0')
  })
  it('keeps native accessible range semantics and live announcements', async () => {
    const { container } = await mount(); const slider = container.querySelector('input[type=range]')
    expect(container.querySelector(`label[for="${slider.id}"]`).textContent).toContain('without approval')
    slider.focus()
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(slider, '1'); slider.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(slider.step).toBe('1'); expect(slider.getAttribute('aria-valuetext')).toContain('Verified fixes')
    expect(container.querySelectorAll('[aria-live]')).toHaveLength(1)
  })
  it('drills down by category and shows all affected files', async () => {
    const { container } = await mount()
    await act(async () => button(container, 'Manual work').click())
    expect(container.querySelector('.remediation-impact__drilldown').textContent).toContain('C.docx')
    expect(container.querySelector('.remediation-impact__drilldown').textContent).not.toContain('A.docx')
    await act(async () => button(container, 'Inspect affected files').click())
    expect(container.querySelector('.remediation-impact__drilldown').textContent).toContain('A.docx')
    expect(container.textContent).toContain('human judgment')
  })
  it('filters affected files by filename and file type with a visible result count', async () => {
    getRemediationImpact.mockResolvedValue({ ...result(), files: [
      { file: 'Clinical Policy.pdf', findings: 3, automatic: 1, review: 2, manual: 0, blocked: 0, outlook: 'human_work' },
      { file: 'Clinical Training.pptx', findings: 2, automatic: 2, review: 0, manual: 0, blocked: 0, outlook: 'could_complete' },
      { file: 'Finance Policy.docx', findings: 2, automatic: 0, review: 2, manual: 0, blocked: 0, outlook: 'human_work' },
    ] })
    const { container } = await mount()
    await act(async () => button(container, 'Inspect affected files').click())
    const search = container.querySelector('input[type=search]')
    const type = container.querySelector('select')
    expect([...type.options].map(option => option.textContent)).toEqual(['All file types', 'DOCX', 'PDF', 'PPTX'])
    expect(container.textContent).toContain('3 of 3 files')

    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, 'clinical')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.textContent).toContain('2 of 3 files')
    expect(container.textContent).not.toContain('Finance Policy.docx')

    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(type, 'pdf')
      type.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(container.textContent).toContain('1 of 3 files')
    expect(container.textContent).toContain('Clinical Policy.pdf')
    expect(container.textContent).not.toContain('Clinical Training.pptx')

    await act(async () => button(container, 'Clear filters').click())
    expect(container.textContent).toContain('3 of 3 files')
  })
  it('ignores stale responses from earlier slider positions', async () => {
    const { container } = await mount(); let resolveOld
    getRemediationImpact.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    await act(async () => button(container, 'Review first').click())
    await act(async () => button(container, 'Verified fixes').click())
    await act(async () => resolveOld(result({ rule_based: 0, ai: 1 })))
    expect(container.querySelector('input[type=range]').value).toBe('1')
    expect(container.querySelector('[role=status]').textContent).toContain('4 findings eligible')
  })
  it('suppresses inconsistent counts and blocks execution', async () => {
    getRemediationImpact.mockResolvedValue({ ...result(), integrity: { complete: false } })
    const { container } = await mount({ onRun: vi.fn() })
    expect(container.textContent).toContain('could not be reconciled')
    expect(container.querySelector('table')).toBeNull()
    expect(button(container, 'Run remediation with these settings').disabled).toBe(true)
  })
  it('shows unavailable instead of zero for missing projections', async () => {
    getRemediationImpact.mockResolvedValue({ ...result(), file_outlook: {} })
    const { container } = await mount()
    expect(container.querySelector('.remediation-impact__outlooks').textContent).toContain('Not yet available')
  })
  it('does not carry an edited policy to a different assessment', async () => {
    const { container, root } = await mount()
    await act(async () => button(container, 'Review first').click())
    await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-2' })))
    expect(getRemediationImpact).toHaveBeenLastCalledWith('run-2', null, undefined)
    expect(container.querySelector('input[type=range]').value).toBe('2')
  })
  it('lets read-only users preview without running or saving', async () => {
    const { container } = await mount({ readOnly: true, onRun: vi.fn() })
    expect(button(container, 'Save as default for future runs').disabled).toBe(true)
    expect(button(container, 'Run remediation with these settings').disabled).toBe(true)
    expect(button(container, 'Review first').disabled).toBe(false)
  })
  it('handles an absent preview without inventing counts', async () => {
    getRemediationImpact.mockResolvedValue(null)
    const { container } = await mount()
    expect(container.querySelector('table')).toBeNull()
    expect(container.textContent).toContain('Counts are unavailable')
  })
  it('keeps selected file scope stable and traces findings within a file', async () => {
    const { container, root } = await mount({ scopeFiles: ['C.docx', 'A.docx'] })
    expect(getRemediationImpact).toHaveBeenLastCalledWith('run-1', null, ['A.docx', 'C.docx'])
    const calls = getRemediationImpact.mock.calls.length
    await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', scopeFiles: ['A.docx', 'C.docx'] })))
    expect(getRemediationImpact.mock.calls.length).toBe(calls)
    expect(container.textContent).toContain('Selected remediation scope')
    await act(async () => button(container, 'Inspect affected files').click())
    await act(async () => button(container, 'C.docx').click())
    expect(container.textContent).toContain('Finding paths: C.docx')
    expect(container.textContent).toContain('request an accessibility judgment')
  })
  it('assigns selected human files only after an explicit submit and server response', async () => {
    let finish
    assignRemediationImpact.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { container } = await mount({ myEmail: 'reviewer@example.com' })
    await act(async () => button(container, 'Inspect affected files').click())
    await act(async () => button(container, 'Assign human work').click())
    expect(container.querySelectorAll('input[type=checkbox]')).toHaveLength(1)
    expect(assignRemediationImpact).not.toHaveBeenCalled()
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(assignRemediationImpact).toHaveBeenCalledWith('run-1', ['C.docx'], 'reviewer@example.com', { rule_based: 2, ai: 1 })
    expect(container.textContent).toContain('Assigning…')
    expect(container.textContent).not.toContain('files assigned to')
    await act(async () => finish({ tasks_assigned: 1, findings_assigned: 1, files_assigned: 1, assignee: 'reviewer@example.com', results: [{ file: 'C.docx', status: 'assigned' }] }))
    expect(container.textContent).toContain('1 tasks covering 1 findings across 1 files assigned to reviewer@example.com')
  })
  it('keeps assignment failures explicit without changing finding totals', async () => {
    assignRemediationImpact.mockRejectedValue(new Error('Permission denied'))
    const { container } = await mount({ myEmail: 'reviewer@example.com' })
    await act(async () => button(container, 'Inspect affected files').click())
    await act(async () => button(container, 'Assign human work').click())
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(container.querySelector('[role=alert]').textContent).toContain('Permission denied')
    expect(container.textContent).toContain('7 unresolved findings across 3 files')
  })
  it('has no automated accessibility violations', async () => {
    const { container } = await mount()
    const report = await axe.run(container, { rules: { region: { enabled: false } } })
    expect(report.violations).toEqual([])
  })
})
