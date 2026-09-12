import { act, useEffect } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import WaterfallVisualDrawer from './WaterfallVisualDrawer.jsx'
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const click = async el => act(async () => el.click())
it('mounts only selected content, retains tabs across stages, resets across account/run', async () => {
  const mounted = vi.fn(), unmounted = vi.fn()
  function Attempts() {
    useEffect(() => { mounted(); return unmounted }, [])
    return <p>Recorded attempts</p>
  }
  const { root, container } = createTestRoot()
  const render = async (identity, stageTitle) => act(async () => root.render(<WaterfallVisualDrawer
    identity={identity} stageTitle={stageTitle} onClose={() => {}} overview={<p>Overview content</p>}
    attempts={<Attempts />} evidence={<p>Evidence content</p>} />))
  await render('owner/run1', 'Fallback 1')
  expect(mounted).not.toHaveBeenCalled()
  await click([...container.querySelectorAll('[role=tab]')].find(tab => tab.textContent === 'Attempts'))
  expect(mounted).toHaveBeenCalledTimes(1)
  expect(container.querySelectorAll('[role=tabpanel]')).toHaveLength(1)
  await render('owner/run1', 'Fallback 2')
  expect(container.textContent).toContain('Recorded attempts')
  await render('another-owner/run2', 'Fallback 2')
  expect(container.textContent).toContain('Overview content')
  expect(unmounted).toHaveBeenCalledTimes(1)
})
it('supports arrows, Home, End with linked panels', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<WaterfallVisualDrawer identity="run" onClose={() => {}} />))
  const tabs = [...container.querySelectorAll('[role=tab]')]
  const key = async (index, key) => act(async () => tabs[index].dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })))
  await key(0, 'ArrowLeft')
  expect(tabs[3].getAttribute('aria-selected')).toBe('true')
  expect(document.activeElement).toBe(tabs[3])
  expect(container.querySelector('[role=tabpanel]').getAttribute('aria-labelledby')).toBe(tabs[3].id)
  await key(3, 'Home')
  expect(tabs[0].getAttribute('aria-selected')).toBe('true')
  await key(0, 'End')
  expect(tabs[3].getAttribute('tabindex')).toBe('0')
})
it('opens attempt in same drawer with exact model identity and Escape close', async () => {
  const onClose = vi.fn()
  const { root, container } = createTestRoot()
  await act(async () => root.render(<WaterfallVisualDrawer identity="run" stageTitle="Fallback 2"
    provider="Recorded provider" model="exact-historical-model-id" status="Recorded" onClose={onClose}
    overview={({ selectTab }) => <button onClick={() => selectTab('Attempts')}>Open attempt</button>}
    attempts={<p>Saved attempt details</p>} />))
  await click([...container.querySelectorAll('button')].find(el => el.textContent === 'Open attempt'))
  expect(container.querySelectorAll('[role=dialog]')).toHaveLength(1)
  expect(container.textContent).toContain('Saved attempt details')
  expect(container.textContent).toContain('exact-historical-model-id')
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('opens Changes lazily and preserves the tab when another model is selected', async () => {
  const mounted = vi.fn()
  function Changes() { useEffect(() => { mounted() }, []); return <p>Before and proposed change</p> }
  const { root, container } = createTestRoot()
  const render = async stageTitle => act(async () => root.render(<WaterfallVisualDrawer identity="owner/run" stageTitle={stageTitle} onClose={() => {}} changes={<Changes />} />))
  await render('Primary')
  expect(mounted).not.toHaveBeenCalled()
  await click([...container.querySelectorAll('[role=tab]')].find(tab => tab.textContent === 'Changes'))
  expect(container.textContent).toContain('Before and proposed change')
  await render('Fallback')
  expect(container.querySelector('[role=tab][aria-selected=true]').textContent).toBe('Changes')
  expect(mounted).toHaveBeenCalledTimes(1)
})
