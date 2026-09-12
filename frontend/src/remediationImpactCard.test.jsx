import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement, act } from 'react'
import axe from 'axe-core'
import RemediationImpactCard from './RemediationImpactCard.jsx'
import AssessSummary from './AssessSummary.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
import { getRemediationImpact, saveRemediationImpactPolicy, assignRemediationImpact, getRemediationAIDetails } from './api.js'
vi.mock('./api.js', () => ({ getRemediationImpact: vi.fn(), saveRemediationImpactPolicy: vi.fn(), assignRemediationImpact: vi.fn(), getRemediationAIDetails: vi.fn() }))
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
const managedChoices = () => getRemediationImpact.mockImplementation(async (_id, policy) => {
  const chosen = policy || {rule_based:2,ai:1,ai_budget_usd:'25.00'}
  const resolved = chosen.cloud_input_strategy === 'automatic' ? {...chosen, ai_budget_usd:'25.00', document_wide_ai:true} : chosen
  return {...result(resolved),capabilities:{...result().capabilities,ai_budget:true}}
})
describe('RemediationImpactCard', () => {
  it('passes every findings lane to the assessment and opens blocked details', async () => {
    const data = result()
    data.open.findings = 11
    data.lanes.automatic.findings = 6
    data.lanes.review.findings = 2
    data.lanes.manual.findings = 0
    data.lanes.blocked.findings = 3
    data.files = [{ file: 'Blocked.pdf', findings: 3, blocked: 3, automatic: 0, review: 0, manual: 0 }]
    getRemediationImpact.mockResolvedValue(data)
    const renderAssessment = vi.fn(forecast => createElement('button', { onClick: forecast.onBlocked }, 'Blocked tile'))
    const { container } = await mount({ renderAssessment })
    expect(renderAssessment.mock.calls.at(-1)[0]).toMatchObject({ automatic: 6, human: 2, blocked: 3, total: 11 })
    await act(async () => button(container, 'Blocked tile').click())
    expect(container.querySelector('[role="dialog"]').textContent).toContain('Blocked.pdf')
  })

  it('keeps the start action and key counts visible while secondary plan details begin collapsed', async () => {
    const onRun = vi.fn()
    const { container } = await mount({ onRun, renderAssessment: forecast => createElement('div', { 'data-testid': 'assessment-forecast' }, `${forecast.automatic} automatic; ${forecast.human} human`) })
    const details = container.querySelector('.remediation-impact__details')
    expect(details.open).toBe(false)
    expect(details.querySelector('summary').textContent).toContain('Plan details')
    expect(details.querySelector('.remediation-impact__outlooks')).toBeTruthy()
    const start = button(container, 'Approve plan and start')
    expect(start.closest('details')).toBeNull()
    expect(start.closest('.remediation-impact__startbar')).toBeTruthy()
    expect(start.closest('.remediation-impact__startbar').textContent).toContain('4 automatic · 2 to approve · 1 manual · 0 blocked')
    expect(start.disabled).toBe(false)
    expect(container.querySelector('[data-testid="assessment-forecast"]').textContent).toBe('4 automatic; 3 human')
    expect(container.querySelector('[data-testid="assessment-forecast"]').closest('details')).toBeNull()
    await act(async () => start.click())
    expect(onRun).toHaveBeenCalledWith({ rule_based: 2, ai: 1 }, expect.objectContaining({ open: { findings: 7, files: 3 } }))
    expect(details.open).toBe(false)
    await act(async () => details.querySelector('summary').click())
    expect(details.open).toBe(true)
  })

  it('opens assessment drilldowns while Plan details remain collapsed', async () => {
    const { container } = await mount({ renderAssessment: forecast => createElement('button', { onClick: forecast.onHuman }, 'Human review tile') })
    const details = container.querySelector('.remediation-impact__details')
    await act(async () => button(container, 'Human review tile').click())
    expect(details.open).toBe(false)
    const dialog = container.querySelector('[role="dialog"]')
    expect(dialog).toBeTruthy()
    expect(dialog.closest('details')).toBeNull()
    expect(dialog.textContent).toContain('C.docx')
  })

  it('opens actual saved AI outputs from the live chart without starting remediation', async () => {
    const onRun = vi.fn()
    getRemediationImpact.mockResolvedValue({ ...result(), open: { findings: 2, files: 1 },
      findings: [{ id: 'f1', file: 'A.docx', rule_id: '1.1.1', origin: 'ai', lane: 'review', finding_count: 2 }],
      integrity: { complete: true, open_equals_lane_sum: true },
    })
    getRemediationAIDetails.mockResolvedValue({ available: true, callsAvailable: true, calls: [], items: [
      { id: 'i1', scan_id: 'run-1', file: 'A.docx', rule_id: '1.1.1', status: 'pending',
        proposals: [{ before: 'Old description', proposed_value: 'A chart of quarterly results', source: 'AI draft' }] },
    ] })
    const { container } = await mount({ onRun, scopeFiles: ['A.docx'] })
    expect(getRemediationAIDetails).not.toHaveBeenCalled()
    await act(async () => button(container, 'See findings and AI details').click())
    expect(getRemediationAIDetails).toHaveBeenCalledWith('run-1')
    expect(container.querySelector('[role=dialog]').textContent).toContain('Old description')
    expect(container.querySelector('[role=dialog]').textContent).toContain('A chart of quarterly results')
    expect(container.querySelector('[role=dialog]').textContent).toContain('Awaiting your review')
    expect(onRun).not.toHaveBeenCalled()
    expect(saveRemediationImpactPolicy).not.toHaveBeenCalled()
  })
  it('closes suggestion details when the selected scope changes', async () => {
    getRemediationAIDetails.mockResolvedValue({ available: true, items: [], calls: [], callsAvailable: true })
    const { container, root } = await mount({ scopeFiles: ['A.docx'] })
    await act(async () => button(container, 'View AI suggestions').click())
    expect(container.querySelector('[role=dialog]')).not.toBeNull()
    await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', scopeFiles: ['C.docx'] })))
    expect(container.querySelector('[role=dialog]')).toBeNull()
  })
  it('drops chart details when resetting the plan to active settings', async () => {
    getRemediationAIDetails.mockResolvedValue({ available: true, items: [], calls: [], callsAvailable: true })
    const { container } = await mount()
    await act(async () => button(container, 'View AI suggestions').click())
    expect(container.querySelector('[role=dialog]')).not.toBeNull()
    await act(async () => button(container, 'Reset to active').click())
    expect(container.querySelector('[role=dialog]')).toBeNull()
  })
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
    expect(getRemediationImpact.mock.calls.at(-1)[1]).toMatchObject({rule_based:0,ai:1})
    expect(onRun).not.toHaveBeenCalled()
    await act(async () => button(container, 'Eligible fixes').click())
    await act(async () => button(container, 'Save as default for future runs').click())
    expect(saveRemediationImpactPolicy).toHaveBeenCalledWith('run-1', { rule_based: 2, ai: 1 }, 4)
    expect(onRun).not.toHaveBeenCalled()
    await act(async () => button(container, 'Approve plan and start').click())
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
    // The COUNTS table, specifically. A bare `table` selector stood in for it while this card
    // rendered exactly one table; the mode diagram below the plan choices is also a table (it is
    // genuinely tabular — modes down, stages across) and carries no counts, so the proxy started
    // reporting it as a reconciliation failure. Assert the thing the test is actually about, and
    // then assert the stronger claim the proxy was reaching for: no digit is rendered anywhere.
    expect(container.querySelector('.remediation-impact__table-wrap')).toBeNull()
    expect(container.querySelector('.rmd__table')).toBeNull()
    expect(container.querySelector('.rmd__count')).toBeNull()
    expect(button(container, 'Approve plan and start').disabled).toBe(true)
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
    expect(button(container, 'Approve plan and start').disabled).toBe(true)
    expect(button(container, 'Review first').disabled).toBe(false)
  })
  it('handles an absent preview without inventing counts', async () => {
    getRemediationImpact.mockResolvedValue(null)
    const { container } = await mount()
    expect(container.querySelector('.remediation-impact__table-wrap')).toBeNull()
    expect(container.textContent).toContain('Counts are unavailable')
    // Same narrowing as above. The diagram numbers its pipeline stages 1..7 — ordinals, not
    // counts — so the claim to assert is that no COUNT cell rendered; those appear only where the
    // caller supplies a figure, and this mount supplies none.
    expect(container.querySelector('.rmd__count')).toBeNull()
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
    expect(container.querySelector('.remediation-file-items').textContent).toContain('C.docx')
    expect(container.textContent).toContain('request an accessibility judgment')
  })
  it('assigns selected human files only after an explicit submit and server response', async () => {
    let finish
    assignRemediationImpact.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { container } = await mount({ myEmail: 'reviewer@example.com' })
    await act(async () => button(container, 'Inspect affected files').click())
    await act(async () => button(container, 'Assign human work').click())
    expect(container.querySelectorAll('.remediation-impact__assignment input[type=checkbox]')).toHaveLength(1)
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
  it('previews guided choices without starting a run or changing AI permission implicitly', async () => {
    managedChoices()
    const onRun = vi.fn()
    const { container } = await mount({ onRun })
    const choose = async label => act(async () => [...container.querySelectorAll('.remediation-plan-choices label')].find(node => node.textContent.includes(label)).querySelector('input').click())
    await choose('Review every change')
    expect(getRemediationImpact.mock.calls.at(-1)[1]).toMatchObject({rule_based:0,ai:1})
    await choose('Local models')
    await choose('Apply rule-based fixes automatically')
    expect(getRemediationImpact.mock.calls.at(-1)[1]).toMatchObject({ rule_based: 2, ai: 1, ai_zone:'local' })
    expect(container.textContent).not.toContain('3. AI providers & budget')
    expect(onRun).not.toHaveBeenCalled()
    await act(async () => button(container, 'Approve plan and start').click())
    expect(onRun.mock.calls[0][0]).toMatchObject({rule_based:2,ai:1,ai_zone:'local'})
  })
  it('removes spending and provider questions from the plan', async () => {
    getRemediationImpact.mockImplementation(async () => ({ ...result(), providers: { text: { provider: 'anthropic', model: 'configured-model', zone: 'cloud' } } }))
    const { container } = await mount()
    const choices = container.querySelector('.remediation-plan-choices')
    expect(choices.textContent).not.toContain('configured-model')
    expect(choices.textContent).not.toContain('AI spending limit')
    expect(choices.querySelector('input[type="number"]')).toBeNull()

  })
  it('keeps assessment totals fixed beside live tiles and opens the matching right drawer', async () => {
    const renderAssessment = forecast => createElement(AssessSummary, {
      files: [{ file: 'A.docx', status: 'analysed', issues: [{ wcag: 'SC_1_3_1', severity: 'SERIOUS' }] }],
      criteria: new Set(['1.3.1']), cap: { docx: { '1.3.1': 'auto' } },
      assessment: { docx: { '1.3.1': 'auto' } }, remediationForecast: forecast,
    })
    const { container } = await mount({ renderAssessment })
    const tile = name => [...container.querySelectorAll('.assesssummary button')].find(node => node.textContent.startsWith(name))
    const historicTotal = () => [...container.querySelectorAll('.assesssummary div')].find(node => node.firstElementChild?.textContent === 'Total findings')?.textContent
    const before = historicTotal()
    expect(before).toContain('1')
    expect(container.querySelector('.remediation-impact__settings .remediation-plan-choices')).not.toBeNull()
    expect(container.querySelector('.remediation-impact__results .assesssummary')).not.toBeNull()
    expect(tile('Can be fixed automatically').textContent).toContain('4')
    tile('Can be fixed automatically').focus()
    await act(async () => tile('Can be fixed automatically').click())
    expect(container.querySelector('[role=dialog]').getAttribute('aria-label')).toBe('Auto-fix available')
    expect(container.querySelector('[role=dialog]').textContent).toContain('A.docx')
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(container.querySelector('[role=dialog]')).toBeNull()
    expect(document.activeElement).toBe(tile('Can be fixed automatically'))
    await act(async () => tile('Needs your review').click())
    expect(container.querySelector('[role=dialog]').textContent).toContain('C.docx')
    expect(container.querySelector('[role=dialog]').textContent).not.toContain('A.docx')
    await act(async () => button(container, 'C.docx').click())
    expect(container.querySelector('[role=dialog]').textContent).toContain('human judgment')
    await act(async () => button(container, '← Back to files').click())
    await act(async () => button(container, 'Close details').click())
    await act(async () => button(container, 'Review first').click())
    expect(tile('Can be fixed automatically').textContent).toContain('0')
    expect(tile('Can be fixed automatically').querySelector('.remediation-forecast-delta').textContent).toBe('−4')
    expect(historicTotal()).toBe(before)
  })
  it('compares settled budget selections even when automation levels stay the same', async () => {
    const renderAssessment = forecast => createElement('output', { 'data-forecast': true }, JSON.stringify(forecast))
    getRemediationImpact.mockResolvedValue({ ...result({ rule_based: 2, ai: 1, ai_budget_usd: '0.00' }) })
    const { container, root } = await mount({ renderAssessment })
    getRemediationImpact.mockResolvedValue({ ...result({ rule_based: 2, ai: 1, ai_budget_usd: '5.00' }),
      lanes: { automatic: { findings: 5 }, review: { findings: 1 }, manual: { findings: 1 } } })
    await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', renderAssessment, refreshKey: 1 })))
    const forecast = JSON.parse(container.querySelector('[data-forecast]').textContent)
    expect(forecast.automaticDelta).toBe(1)
    expect(forecast.humanDelta).toBe(-1)
  })
  it('opens every manual rule immediately and returns to the filtered file list with focus restored', async () => {
    getRemediationImpact.mockResolvedValue({ ...result(), files: [
      { file: 'A.docx', findings: 40, automatic: 0, review: 3, manual: 37, blocked: 0 },
      { file: 'B.pdf', findings: 1, automatic: 0, review: 0, manual: 1, blocked: 0 },
    ], findings: [
      { file: 'A.docx', lane: 'manual', rule_id: '1.1.1', plain_name: 'Describe images', finding_count: 20, primary_reason: 'ai_disabled' },
      { file: 'A.docx', lane: 'manual', rule_id: '1.3.1', plain_name: 'Mark table headers', finding_count: 17, primary_reason: 'source_editing' },
      { file: 'A.docx', lane: 'review', rule_id: '2.4.2', plain_name: 'Review document title', finding_count: 3, primary_reason: 'proposal_approval' },
      { file: 'B.pdf', lane: 'manual', plain_name: 'Other file item', finding_count: 1 },
    ] })
    const { container } = await mount()
    await act(async () => button(container, 'Inspect affected files').click())
    const search = container.querySelector('input[type=search]')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, 'A.docx')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const trigger = button(container, 'A.docx')
    await act(async () => trigger.click())
    const detail = container.querySelector('.remediation-file-items')
    expect(detail.querySelector('h3')).toBe(document.activeElement)
    expect(detail.textContent).toContain('Manual work — 37 findings')
    expect(detail.querySelectorAll('li')).toHaveLength(2)
    expect(detail.textContent).toContain('Describe images')
    expect(detail.textContent).toContain('Mark table headers')
    expect(detail.textContent).not.toContain('Other file item')
    expect(detail.textContent).not.toContain('Review document title')
    expect(search.closest('[hidden]')).not.toBeNull()
    await act(async () => button(container, 'Proposal review · 3').click())
    expect(detail.textContent).toContain('Review document title')
    await act(async () => button(container, '← Back to files').click())
    expect(container.querySelector('.remediation-file-items')).toBeNull()
    expect(search.value).toBe('A.docx')
    expect(document.activeElement).toBe(trigger)
  })
  it('has no automated accessibility violations', async () => {
    const { container } = await mount()
    const report = await axe.run(container, { rules: { region: { enabled: false } } })
    expect(report.violations).toEqual([])
  })
})


it('removes spending numbers while preserving an operational pause notice', async () => {
  getRemediationImpact.mockImplementation(async () => ({...result(), ai_spending: {
    cap_units: 2500000, spent_units: 120, held_units: 200000, available_units: 2299880, blocked: true,
  }}))
  const {container} = await mount()
  const spending = container.querySelector('[aria-label="AI spending for the latest remediation run"]')
  expect(spending).toBeNull()
  expect(container.textContent).not.toContain('Limit: $2.50')
  expect(container.textContent).toContain('Some AI requests are paused')
  expect(container.textContent).toContain('7 unresolved findings across 3 files')
})

// Three default_steps, because chain_options appends fallback_2 and only THEN sets
// supported:true -- a supported catalog never comes back with two.
const generationCatalog = () => ({ version: 1, supported: true, max_steps: 3,
  default_steps: ['primary', 'fallback_1', 'fallback_2'].map((step_id, position) => ({ step_id, position, provider: 'fixture', model: `model-${position}`, enabled: true, capabilities: ['text'] })),
  models: [0, 1, 2].map(position => ({ provider: 'fixture', model: `model-${position}`, capabilities: ['text'], allowed: true, available: true })),
})




it('passes a local-only plan to execution with cloud review and fallbacks removed', async () => {
  const initial = { rule_based: 2, ai: 1, ai_budget_usd: '10.00', ai_review: { enabled: true } }
  getRemediationImpact.mockImplementation(async (_id, policy) => ({ ...result(policy || initial), capabilities: { ...result().capabilities, ai_budget: true } }))
  const onRun = vi.fn()
  const { container } = await mount({ onRun })
  const choice = [...container.querySelectorAll('label')].find(node => node.textContent.includes('Local models'))
  await act(async () => choice.querySelector('input').click())
  const expected = { rule_based: 2, ai: 1, ai_zone: 'local', ai_budget_usd: '0.00', ai_review: { enabled: false }, auto_approve_ai: false }
  expect(getRemediationImpact).toHaveBeenLastCalledWith('run-1', expected, undefined)
  await act(async () => button(container, 'Approve plan and start').click())
  expect(onRun).toHaveBeenCalledWith(expected, expect.anything())
})

it('requires explicit answers even when saved defaults are valid, and invalidates answers for a new scope', async () => {
    managedChoices()
  const onRun = vi.fn()
  const { container, root } = await mount({ onRun, requireAnswers: true, releaseAnswered: false, scopeFiles: ['A.docx'] })
  const start = () => button(container, 'Approve plan and start')
  expect(start()).toBeUndefined()
  expect(button(container, 'Next').disabled).toBe(true)
  expect([...container.querySelectorAll('.remediation-plan-choices input[type=radio]')].some(node => node.checked)).toBe(false)
  const choice = text => [...container.querySelectorAll('label')].find(node => node.textContent.includes(text)).querySelector('input')
  await act(async () => choice('Apply rule-based fixes automatically').click())
  await act(async () => button(container, 'Next').click())
  await act(async () => choice('Local models').click())
  await act(async () => button(container, 'Next').click())
  expect(start().disabled).toBe(true)
  await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', onRun, requireAnswers: true, releaseAnswered: true, scopeFiles: ['A.docx'] })))
  expect(start().disabled).toBe(false)
  await act(async () => start().click())
  expect(onRun).toHaveBeenCalledOnce()
  expect(onRun.mock.calls[0][0]).toMatchObject({ rule_based: 2, ai: 1, ai_zone:'local' })
  await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', onRun, requireAnswers: true, releaseAnswered: true, scopeFiles: ['C.docx'] })))
  expect(start()).toBeUndefined()
  expect(button(container, 'Next').disabled).toBe(true)
})

it('starts cloud plans with explicit choices without an extra confirmation or expanded approval permissions', async () => {
    managedChoices()
  const onRun = vi.fn()
  const { container } = await mount({ onRun, requireAnswers: true })
  const choice = text => [...container.querySelectorAll('label')].find(node => node.textContent.includes(text)).querySelector('input')
  await act(async () => choice('Apply rule-based fixes automatically').click())
  await act(async () => button(container, 'Next').click())
  await act(async () => choice('Local + cloud models').click())
  await act(async () => button(container, 'Next').click())
  expect(container.textContent).not.toContain('I confirm the AI providers')
  expect([...container.querySelectorAll('.remediation-plan-choices input[type=checkbox]')].filter(node => !node.closest('[hidden]'))).toHaveLength(0)
  expect(button(container, 'Approve plan and start').disabled).toBe(false)
  await act(async () => button(container, 'Approve plan and start').click())
  expect(onRun.mock.calls[0][0]).toMatchObject({auto_approve_ai:false,cloud_input_strategy:'automatic',document_wide_ai:true,ai_budget_usd:'25.00'})
})

it('shows three bottom dots, prevents skipping, and preserves answers through Back and dot navigation', async () => {
    managedChoices()
  const { container } = await mount({ requireAnswers: true })
  const dots = () => [...container.querySelectorAll('.plan-wizard-dots button')]
  const choice = text => [...container.querySelectorAll('label')].find(n => n.textContent.includes(text)).querySelector('input')
  expect(dots()).toHaveLength(3)
  expect(dots()[0].getAttribute('aria-current')).toBe('step')
  expect(dots()[2].disabled).toBe(true)
  await act(async () => choice('Review every change').click())
  await act(async () => button(container, 'Next').click())
  expect(dots()[1].getAttribute('aria-current')).toBe('step')
  expect(button(container, 'Next').disabled).toBe(true)
  expect(choice('Review every change').closest('fieldset').hidden).toBe(true)
  await act(async () => choice('Local models').click())
  await act(async () => button(container, 'Next').click())
  expect(dots()[2].getAttribute('aria-current')).toBe('step')
  expect(container.querySelector('.plan-step-heading').textContent).toContain('Publishing')
  await act(async () => button(container, 'Back').click())
  expect(choice('Local models').checked).toBe(true)
  await act(async () => dots()[0].click())
  expect(choice('Review every change').checked).toBe(true)
  await act(async () => dots()[2].click())
  expect(button(container, 'Approve plan and start')).toBeTruthy()
})

it.each(['any', 'local'])('automatic release previews and submits AI application for %s, and removing it revokes approval', async zone => {
  const initial = { rule_based: 0, ai: 1, ai_zone: zone, ai_budget_usd: '0.00', auto_approve_ai: false }
  getRemediationImpact.mockImplementation(async (_id, policy) => result(policy || initial))
  const onRun = vi.fn()
  const { container, root } = await mount({ onRun, automaticRelease: true })
  expect(getRemediationImpact.mock.calls.at(-1)[1]).toMatchObject({ rule_based: 2, auto_approve_ai: true, ai_zone: zone, ai_budget_usd: '0.00' })
  await act(async () => button(container, 'Approve plan and start').click())
  expect(onRun.mock.calls[0][0]).toMatchObject({ rule_based: 2, auto_approve_ai: true, ai_zone: zone })
  await act(async () => root.render(createElement(RemediationImpactCard, { runId: 'run-1', onRun, automaticRelease: false })))
  expect(getRemediationImpact.mock.calls.at(-1)[1].auto_approve_ai).toBe(false)
})

it.each(['Local + cloud models', 'Local models'])('settles automatic publishing with canonical review settings for %s', async modelChoice => {
  const reviewDefaults = { enabled:false, mode:'review_all', minimum_reliability:null,
    max_review_attempts:1, review_model:'strong', permitted_families:[], evaluation_versions:{} }
  let reads = 0
  getRemediationImpact.mockImplementation(async (_id, policy) => {
    // Bound a broken polling cycle so the regression fails rather than hanging.
    if (++reads > 8) throw new Error('Repeated identical plan requests')
    const chosen = policy || { rule_based:2, ai:1, ai_budget_usd:'25.00' }
    const canonical = { ...chosen, ...(chosen.ai_review ? {ai_review:{...reviewDefaults,...chosen.ai_review}} : {}),
      ...(chosen.cloud_input_strategy === 'automatic' ? { ai_budget_usd:'25.00', document_wide_ai:true } : {}) }
    return {...result(canonical),capabilities:{...result().capabilities,ai_budget:true}}
  })
  const onRun = vi.fn()
  const scopeFiles = ['A.docx']
  const props = {runId:'run-1',onRun,requireAnswers:true,scopeFiles,releaseAnswered:false}
  const {container,root} = await mount(props)
  const choice = text => [...container.querySelectorAll('label')].find(node => node.textContent.includes(text)).querySelector('input')
  await act(async()=>choice('Apply rule-based fixes automatically').click())
  await act(async()=>button(container,'Next').click())
  await act(async()=>choice(modelChoice).click())
  await act(async()=>button(container,'Next').click())
  expect(button(container,'Approve plan and start').disabled).toBe(true)
  await act(async()=>root.render(createElement(RemediationImpactCard,{...props,releaseAnswered:true,automaticRelease:true})))
  const start = button(container,'Approve plan and start')
  expect(start.disabled).toBe(false)
  expect(reads).toBeLessThanOrEqual(5)
  expect(onRun).not.toHaveBeenCalled()
  const settledReads = reads
  await act(async()=>root.render(createElement(RemediationImpactCard,{...props,releaseAnswered:true,automaticRelease:true})))
  expect(reads).toBe(settledReads)
  await act(async()=>start.click())
  expect(onRun).toHaveBeenCalledOnce()
  expect(onRun.mock.calls[0][0]).toMatchObject({rule_based:2,auto_approve_ai:true,ai_review:{enabled:false}})
  expect(onRun.mock.calls[0][1].policy).toMatchObject(onRun.mock.calls[0][0])
  expect(getRemediationImpact.mock.calls.at(-1)[2]).toEqual(scopeFiles)
})

it('preserves managed cloud budget omission when publishing is answered before the model preview returns', async () => {
  let resolveCloud
  const normalize = policy => ({...policy,ai_review:{enabled:false,mode:'review_all',minimum_reliability:null,
    max_review_attempts:1,review_model:'strong',permitted_families:[],evaluation_versions:{},...policy.ai_review},
    ...(policy.cloud_input_strategy === 'automatic' ? {ai_budget_usd:policy.ai_budget_usd ?? '25.00',document_wide_ai:true} : {})})
  getRemediationImpact.mockImplementation((_id,policy) => {
    const chosen = policy || {rule_based:2,ai:1,ai_budget_usd:'25.00'}
    const response = {...result(normalize(chosen)),capabilities:{...result().capabilities,ai_budget:true}}
    if (chosen.cloud_input_strategy === 'automatic' && !chosen.auto_approve_ai && !resolveCloud) {
      return new Promise(resolve => {resolveCloud=()=>resolve(response)})
    }
    return Promise.resolve(response)
  })
  const onRun = vi.fn()
  const props={runId:'run-1',onRun,requireAnswers:true,releaseAnswered:false,scopeFiles:['A.docx']}
  const {container,root}=await mount(props)
  const choice = text => [...container.querySelectorAll('label')].find(node=>node.textContent.includes(text)).querySelector('input')
  await act(async()=>choice('Apply rule-based fixes automatically').click())
  await act(async()=>button(container,'Next').click())
  await act(async()=>choice('Local + cloud models').click())
  await act(async()=>button(container,'Next').click())
  await act(async()=>root.render(createElement(RemediationImpactCard,{...props,releaseAnswered:true,automaticRelease:true})))
  const automaticRequests=getRemediationImpact.mock.calls.map(call=>call[1]).filter(policy=>policy?.cloud_input_strategy==='automatic')
  expect(automaticRequests.every(policy=>policy.ai_budget_usd===undefined || policy.ai_budget_usd==='25.00')).toBe(true)
  const reads=getRemediationImpact.mock.calls.length
  await act(async()=>resolveCloud())
  expect(getRemediationImpact).toHaveBeenCalledTimes(reads)
  expect(button(container,'Approve plan and start').disabled).toBe(false)
  expect(onRun).not.toHaveBeenCalled()
  await act(async()=>button(container,'Approve plan and start').click())
  expect(onRun.mock.calls[0][0]).toMatchObject({ai_budget_usd:'25.00',auto_approve_ai:true,cloud_input_strategy:'automatic'})
})

it('explains an incomplete assessment and keeps starting disabled', async()=>{
  getRemediationImpact.mockImplementation(async (_id,policy)=>({...result(policy || undefined),integrity:{complete:false}}))
  const onRun=vi.fn()
  const {container}=await mount({onRun,requireAnswers:true})
  expect(container.textContent).toContain('The assessment preview is incomplete. Refresh or reassess the selected documents.')
  expect(onRun).not.toHaveBeenCalled()
})


it.each(['Local models'])('clears document-wide consent when choosing %s', async label => {
  const initial = { rule_based: 2, ai: 1, ai_zone: 'any', ai_budget_usd: '1.00', document_wide_ai: true, document_wide_input_mode: 'native_pdf', document_wide_model_profile: 'native-pdf-quality.v1' }
  getRemediationImpact.mockImplementation(async (_id, policy) => ({ ...result(policy || initial), capabilities: { ...result().capabilities, ai_budget: true } }))
  const { container } = await mount()
  const option = [...container.querySelectorAll('label')].find(node => node.querySelector('strong')?.textContent === label)
  await act(async () => option.querySelector('input').click())
  expect(getRemediationImpact.mock.calls.at(-1)[1].document_wide_ai).toBe(false)
  expect(getRemediationImpact.mock.calls.at(-1)[1]).not.toHaveProperty('document_wide_input_mode')
  expect(getRemediationImpact.mock.calls.at(-1)[1]).not.toHaveProperty('document_wide_model_profile')
})
