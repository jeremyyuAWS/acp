import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ReleaseDeliveryCard from './ReleaseDeliveryCard.jsx'
afterEach(unmountAll)
async function mount(extra = {}) {
  const { root, container } = createTestRoot()
  const props = { ready: [{file:'saved.docx'}], onPublish:vi.fn(), ...extra }
  await act(async () => root.render(createElement(ReleaseDeliveryCard, props)))
  return { container, props }
}
it('publishes only the eligible saved copies after an explicit click', async () => {
  const {container,props} = await mount()
  expect(props.onPublish).not.toHaveBeenCalled()
  await act(async () => container.querySelector('button.primary').click())
  expect(props.onPublish).toHaveBeenCalledExactlyOnceWith(['saved.docx'])
})
it.each([{readOnly:true},{loading:true},{publishing:true},{ready:[]}])('blocks publication when unavailable: %j', async extra => {
  const {container,props} = await mount(extra)
  await act(async () => container.querySelector('button.primary').click())
  expect(props.onPublish).not.toHaveBeenCalled()
})
it('requires an explicit remaining-work choice and keeps pending delivery separate from published', async () => {
  const onRemainingIssuesChange = vi.fn()
  const {container} = await mount({onRemainingIssuesChange, deliveringCount:1, publishedCount:0})
  expect(onRemainingIssuesChange).not.toHaveBeenCalled()
  await act(async () => container.querySelector('input').click())
  expect(onRemainingIssuesChange).toHaveBeenCalledWith(true)
  expect(container.textContent).toContain('1 delivering')
  expect(container.textContent).toContain('0 published')
  expect(container.querySelector('[role=status]').textContent).toContain('when confirmed')
})
