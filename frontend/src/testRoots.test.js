import { describe, it, expect, afterEach } from 'vitest'
import { createElement, useEffect, useState } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll, _trackedCount } from './testRoots.js'

// The teardown helper the suite's afterEach hooks depend on. If it silently tracked nothing, or
// unmounted only the last root, every file using it would go back to leaving trees standing —
// and the symptom (a passing suite exiting non-zero, occasionally) would not point here.

afterEach(unmountAll)

const Thing = ({ label = 'x' }) => createElement('p', { className: 'thing' }, label)

// A component whose effect resolves a promise into setState — the shape that keeps work in the
// scheduler after the last assertion, and the reason unmounting matters at all.
function Async() {
  const [v, setV] = useState('pending')
  useEffect(() => {
    let live = true
    Promise.resolve('resolved').then((r) => { if (live) setV(r) })
    return () => { live = false }
  }, [])
  return createElement('p', { className: 'async' }, v)
}

describe('createTestRoot / unmountAll', () => {
  it('mounts into the document and tears the tree back out', async () => {
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Thing, { label: 'hello' })) })
    expect(document.querySelectorAll('.thing').length).toBe(1)
    expect(container.textContent).toBe('hello')

    await unmountAll()
    expect(document.querySelectorAll('.thing').length).toBe(0)
    expect(container.isConnected).toBe(false)      // the container leaves the document too
  })

  it('unmounts EVERY root, not just the last one', async () => {
    // The trap in a hand-written afterEach: a file that mounts twice keeps one `root` variable,
    // so the earlier tree is never torn down and nothing in the test output says so.
    for (const label of ['a', 'b', 'c']) {
      const { root } = createTestRoot()
      await act(async () => { root.render(createElement(Thing, { label })) })
    }
    expect(document.querySelectorAll('.thing').length).toBe(3)
    expect(_trackedCount()).toBe(3)

    await unmountAll()
    expect(document.querySelectorAll('.thing').length).toBe(0)
    expect(_trackedCount()).toBe(0)
  })

  it('stops tracking a root once it is unmounted, so a second call is a no-op', async () => {
    const { root } = createTestRoot()
    await act(async () => { root.render(createElement(Thing)) })
    await unmountAll()
    await expect(unmountAll()).resolves.toBeUndefined()   // must not double-unmount and throw
    expect(_trackedCount()).toBe(0)
  })

  it('tears down a component with a pending async effect — the case this exists for', async () => {
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(Async)) })
    await act(async () => { await Promise.resolve() })
    expect(container.querySelector('.async').textContent).toBe('resolved')

    await unmountAll()
    expect(document.querySelectorAll('.async').length).toBe(0)
  })

  it('leaves nothing tracked between tests, so files cannot leak into each other', () => {
    expect(_trackedCount()).toBe(0)
  })
})
