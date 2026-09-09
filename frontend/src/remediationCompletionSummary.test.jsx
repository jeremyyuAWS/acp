import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Summary from './RemediationCompletionSummary.jsx'
afterEach(unmountAll)
async function mount(snapshot, view) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<Summary snapshot={snapshot} view={view} reviewHref="/?tab=remediate&mode=review" releaseHref="/?tab=publish" />))
  return container
}
it('stays absent while processing', async () => { expect((await mount({ terminal: false })).textContent).toBe('') })
it('separates verified changes, review items, retained charges, and undelivered copies', async () => {
  const c = await mount({ terminal: true, fixes: { verified: 12 }, review: { items: 3 }, documents: { failed: 0 }, delivery: { awaiting_release: 2 } }, { available: true, spending: { spent_units: 120000, held_units: 30000, blocked: true } })
  expect(c.textContent).toContain('Verified changes · all origins12')
  expect(c.textContent).toContain('Review items · not findings3')
  expect(c.textContent).toContain('$0.12')
  expect(c.textContent).toContain('$0.03 remains reserved')
  expect(c.textContent).toContain('2 corrected copies awaiting Release')
  expect([...c.querySelectorAll('a')].map(a => a.textContent)).toEqual(['Open Review', 'Inspect Release'])
})
it('never turns unknown or invalidated evidence into zero or a completion claim', async () => {
  const c = await mount({ terminal: true, state: 'cancelled', fixes: { verified: 20 }, review: { items: 10 }, delivery: { awaiting_release: 4 }, integrity: { ok: false, affected: ['fixes', 'review', 'delivery'] } })
  expect(c.textContent).toContain('Run stopped')
  expect(c.textContent).toContain('Unavailable')
  expect(c.querySelector('a')).toBeNull()
  expect(c.textContent).not.toContain('Automatic processing finished')
})

it('does not call a fully charged budget breach an unsettled reservation', async () => {
  const c = await mount({ terminal: true }, { available: true, spending: { spent_units: 2000000, held_units: 0, blocked: true } })
  expect(c.textContent).toContain('Further AI spending is on hold')
  expect(c.textContent).not.toContain('remains reserved')
  expect(c.textContent).not.toContain('not settled')
})
