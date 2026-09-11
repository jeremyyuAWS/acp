import { afterEach, expect, it } from 'vitest'
import { createElement, act, useState } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import useIdentity from './useAcceptedRemediationIdentity.js'
import Summary from './AcceptedRemediationPlanSummary.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
function Harness({ scanId = 'scan', snapshot, initialLaunch, releaseState }) {
  const [launch, setLaunch] = useState(initialLaunch)
  const { batchId, authorization } = useIdentity({ scanId, snapshot, launch, clearLaunch: setLaunch, releaseState })
  return createElement('div', null,
    createElement('output', null, batchId || 'none'),
    createElement(Summary, { policy: { ai: 0, rule_based: 2 }, authorization }))
}
async function mount(props) {
  const { container, root } = createTestRoot()
  const render = async update => act(async () => root.render(createElement(Harness, update)))
  await render(props)
  return { container, render }
}
it('keeps the just-accepted batch until confirmed, then follows newer streamed executions', async () => {
  const props = { initialLaunch: { scanId: 'scan', batchId: 'new' }, snapshot: { scan_id: 'scan', batch_id: 'old' } }
  const { container, render } = await mount(props)
  expect(container.querySelector('output').textContent).toBe('new')
  await render({ ...props, snapshot: { scan_id: 'scan', batch_id: 'new' } })
  expect(container.querySelector('output').textContent).toBe('new')
  await render({ ...props, snapshot: { scan_id: 'scan', batch_id: 'external-later' } })
  expect(container.querySelector('output').textContent).toBe('external-later')
})
it.each([undefined, 'other-run'])('does not show publication consent from an unbound or different run: %s', async run_id => {
  const { container } = await mount({ snapshot: { scan_id: 'scan', batch_id: 'current' }, releaseState: { scanId: 'scan', authorization: { run_id, allow_remaining_issues: true } } })
  expect(container.textContent).not.toContain('Publish automatically')
  expect(container.textContent).toContain('Not recorded')
})
it('shows consent bound to this exact scan and execution', async () => {
  const { container } = await mount({ snapshot: { scan_id: 'scan', batch_id: 'current' }, releaseState: { scanId: 'scan', authorization: { run_id: 'current', allow_remaining_issues: true } } })
  expect(container.textContent).toContain('Publish automatically')
})
it('ignores stale launch and snapshot after scan switches, including no scan', async () => {
  const props = { scanId: 'other', initialLaunch: { scanId: 'scan', batchId: 'new' }, snapshot: { scan_id: 'scan', batch_id: 'old' } }
  const { container, render } = await mount(props)
  expect(container.querySelector('output').textContent).toBe('none')
  await render({ ...props, scanId: null })
  expect(container.querySelector('output').textContent).toBe('none')
})

it.each([
  [{ runId: 'current', authorization: null }, true],
  [{ runId: 'current' }, false],
  [{ runId: 'other', authorization: null }, false],
  [{ authorization: null }, false],
])('shows manual publishing only for confirmed absence on this execution: %j', async (state, known) => {
  const { container } = await mount({ snapshot: { scan_id: 'scan', batch_id: 'current' }, releaseState: { scanId: 'scan', ...state } })
  expect(container.textContent.includes('Review in Release before publishing')).toBe(known)
  expect(container.textContent).not.toContain('Publish automatically')
})
