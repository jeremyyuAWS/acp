import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import FileCoverage from './FileCoverage.jsx'
import RemediationProgressSummary from './RemediationProgressSummary.jsx'
import WorkflowOutcomeTiles from './WorkflowOutcomeTiles.jsx'

let root, container
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); vi.useRealTimers(); vi.unstubAllGlobals() })
async function mount(content) { container = document.createElement('div'); document.body.append(container); root = createRoot(container); await act(async () => root.render(content)) }
const delta = selector => container.querySelector(`${selector} .kpi-update-delta`)
const expectDelta = (selector, value, tone) => {
  expect(delta(selector)?.textContent).toBe(value)
  expect(delta(selector)?.classList.contains(`kpi-update-delta--${tone}`)).toBe(true)
  expect(container.querySelector(`${selector} .kpi-counter-value--activity`)).not.toBeNull()
}
function reducedMotion() { vi.useFakeTimers(); vi.stubGlobal('matchMedia', () => ({ matches: true })) }

it('shows green processed increases and queue decreases while preserving the saved baseline', async () => {
  reducedMotion()
  const baseline = { withFindings: 147, processed: 0, remaining: 147 }
  await mount(<FileCoverage evidence={{ counts: baseline, baseline }} animate />)
  expect(container.querySelector('.kpi-update-delta')).toBeNull()
  await act(async () => root.render(<FileCoverage evidence={{ counts: { withFindings: 147, processed: 1, remaining: 146 }, baseline }} animate />))
  expectDelta('.coverage-verified', '+1', 'positive')
  expectDelta('.coverage-processing', '−1', 'positive')
  expect(delta('.coverage-attention')).toBeNull()
  expect(container.textContent).toContain('Since start: +1')
  expect(container.textContent).toContain('Since start: −1')
  await act(async () => vi.advanceTimersByTime(2001))
  expect(container.querySelector('.kpi-update-delta')).toBeNull()
  expect(container.textContent).toContain('Since start: +1')
})

it('does not mark a growing attention queue or work beginning as completed repairs', async () => {
  reducedMotion()
  await mount(<RemediationProgressSummary documents={[]} animate />)
  await act(async () => root.render(<RemediationProgressSummary documents={[{ progressState: 'processing' }, { progressState: 'attention' }]} animate />))
  expectDelta('.progress-processing', '+1', 'neutral')
  expectDelta('.progress-attention', '+1', 'warning')
  await act(async () => root.render(<RemediationProgressSummary documents={[{ progressState: 'verified' }, { progressState: 'ready' }]} animate />))
  expectDelta('.progress-attention', '−1', 'positive')
  expectDelta('.progress-verified', '+1', 'positive')
  expectDelta('.progress-ready', '+1', 'positive')
})

it('animates finding queue drainage and verified fixes without celebrating excluded findings', async () => {
  reducedMotion()
  await mount(<WorkflowOutcomeTiles stage="remediate" executionId="run" domain={{ total: 3, buckets: { awaiting_recorded_outcome: 3 } }} />)
  await act(async () => root.render(<WorkflowOutcomeTiles stage="remediate" executionId="run" domain={{ total: 3, buckets: { awaiting_recorded_outcome: 1, resolved_verified: 1, excluded: 1 } }} />))
  expectDelta('.tone-blue', '−2', 'positive')
  expectDelta('.tone-green', '+1', 'positive')
  expectDelta('.tone-gray', '+1', 'neutral')
})

it('rewards delivered files and drained publication queues while leaving skipped files neutral', async () => {
  reducedMotion()
  await mount(<WorkflowOutcomeTiles stage="release" executionId="run" domain={{ total: 2, buckets: { waiting: 2 } }} />)
  await act(async () => root.render(<WorkflowOutcomeTiles stage="release" executionId="run" domain={{ total: 2, buckets: { published: 1, skipped: 1 } }} />))
  expectDelta('.tone-blue', '−2', 'positive')
  expectDelta('.tone-green', '+1', 'positive')
  expectDelta('.tone-gray', '+1', 'neutral')
})
