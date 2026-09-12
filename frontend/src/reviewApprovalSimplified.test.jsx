import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { createTestRoot, unmountAll } from './testRoots.js'
import Inbox from './RemediationInbox.jsx'
afterEach(unmountAll)
const ready = (id, extra = {}) => ({ id, file: `${id}.docx`, ruleId: '1.1.1', title: 'Image description', kind: 'ai-draft', aiAssisted: true, hasProposal: true, after: 'A useful image description', _raw: { decision_version: 1, source_revision: 'source', proposal_snapshot_ids: [`proposal-${id}`] }, ...extra })
const click = async button => act(async () => button.click())
async function mount(props) {
 const { root, container } = createTestRoot()
 const render = async next => act(async () => root.render(createElement(Inbox, { scanId: 'scan', initialTab: 'needs-review', ...props, ...next })))
 await render()
 return { root, container, render, button: label => [...container.querySelectorAll('button')].find(b => b.textContent === label) }
}
it('uses one scan action and distinguishes similar findings from ready fixes', async () => {
 const queue = Array.from({ length: 20 }, (_, i) => ready(`a${i}`, i ? { _raw: {} } : {}))
 const onDecide = vi.fn().mockResolvedValue()
 const v = await mount({ queue, onDecide, autoApprove: false, onOpenPlan: vi.fn() })
 expect(v.button('Apply all ready fixes (1)')).toBeTruthy()
 expect(v.container.textContent).not.toContain('Select matching proposals')
 expect(v.container.textContent).not.toContain('Bulk approve ready proposals')
 expect(v.container.textContent).toContain('Auto-apply AI fixes: Off')
 await click(v.container.querySelector('.rinbox-row'))
 expect(v.container.textContent).toContain('20 similar findings · 1 ready to apply')
 expect(v.button('Apply this fix')).toBeTruthy()
 expect(v.button('Needs manual work')).toBeTruthy()
 await click(v.button('Apply all ready fixes (1)'))
 expect(onDecide).toHaveBeenCalledTimes(1)
 expect(onDecide.mock.calls[0][0].id).toBe('a0')
 expect(onDecide.mock.calls[0][1].expectedVersion).toBe(1)
})
it('freezes a whole-scan action and never adds later proposals or duplicates busy writes', async () => {
 let finish
 const onDecide = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValue()
 const queue = [ready('a'), ready('b')]
 const v = await mount({ queue, onDecide })
 await click(v.button('Apply all ready fixes (2)'))
 expect(onDecide).toHaveBeenCalledTimes(1)
 expect(v.button('Apply all ready fixes (2)').disabled).toBe(true)
 await v.render({ queue: [...queue, ready('c')] })
 await act(async () => finish())
 expect(onDecide.mock.calls.map(([finding]) => finding.id)).toEqual(['a', 'b'])
})
it('retains the old approval controls deliberately without enabling them in the live app', () => {
 const source = readFileSync('src/RemediationInbox.jsx', 'utf8')
 expect(source).toContain('legacyApprovalControls = false')
 expect(source).toContain('Retired matching approval panel')
 expect(readFileSync('src/Remediate.jsx', 'utf8')).not.toMatch(/legacyApprovalControls=/)
})
