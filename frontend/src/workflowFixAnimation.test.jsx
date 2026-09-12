import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Card from './WorkflowStageActivityCard.jsx'
afterEach(() => { unmountAll(); vi.useRealTimers() })
const snapshot = (verified, execution_id = 'run') => ({stage:'remediate',execution_id,state:'processing_complete',
  domain_reconciliation:{total:30,accounted:30,exact:true,buckets:{resolved_verified:verified,awaiting_review:30-verified}}})
it('shows green +fix feedback in the visible workflow card and clears it without replaying another run', async () => {
  vi.useFakeTimers()
  const {container,root}=createTestRoot()
  await act(async()=>root.render(<Card snapshot={snapshot(11)} />))
  expect(container.querySelector('.kpi-update-delta')).toBeNull()
  await act(async()=>root.render(<Card snapshot={snapshot(13)} />))
  expect(container.querySelector('.finding-outcome-kpis__verified .kpi-update-delta').textContent).toBe('+2')
  expect(container.querySelector('.tone-pink .kpi-update-delta').textContent).toBe('−2')
  await act(async()=>vi.advanceTimersByTime(2001))
  expect(container.querySelector('.kpi-update-delta')).toBeNull()
  await act(async()=>root.render(<Card snapshot={snapshot(20,'new')} />))
  expect(container.querySelector('.kpi-update-delta')).toBeNull()
})
