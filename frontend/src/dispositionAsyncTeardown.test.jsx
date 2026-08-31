/**
 * DispositionRules must not write state from a request that outlived its mount, and must not let
 * a slow request overwrite a faster newer one.
 *
 * THE REPORTED FAILURE, on #1068's CI run 33346024704:
 *
 *     ReferenceError: window is not defined
 *      ❯ getCurrentEventPriority react-dom.development.js:10993:22
 *      ❯ dispatchSetState        react-dom.development.js:16648:14
 *      ❯ src/DispositionRules.jsx:636:19
 *     This error originated in "src/discoverNavLiveIndicator.test.jsx"
 *
 * 417 files and 5211 tests PASSED and the job still exited 1, because vitest counts an unhandled
 * rejection at the RUN level. The PR it failed on was backend-only — five files, no frontend —
 * and main was green on the identical frontend content, so the trigger is scheduling: whichever
 * test file happens to be running when the promise lands wears the failure.
 *
 * WHY IT NEEDS A REAL REPRODUCTION, not a mock of one. Calling a setter on an unmounted React 18
 * root is a silent no-op — it does not warn and it does not throw. The crash only appears once the
 * ENVIRONMENT is gone, when React reaches for `window` and finds nothing. So these tests remove
 * `window` for exactly the moment the promise settles, which is the condition vitest creates at
 * teardown, and restore it immediately. That is reproducing the failure, not suppressing it: no
 * global rejection handler is installed, no error is swallowed, and every existing assertion in
 * the suite stands.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act, StrictMode } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const listDispositionPolicies = vi.fn()
const listDispositionConflicts = vi.fn()

vi.mock('./api.js', () => ({
  listDispositionPolicies: (...a) => listDispositionPolicies(...a),
  listDispositionConflicts: (...a) => listDispositionConflicts(...a),
  createDispositionPolicy: vi.fn(() => Promise.resolve({ policy_id: 'p9' })),
  setDispositionPolicyEnabled: vi.fn(() => Promise.resolve({})),
  previewDispositionPolicy: vi.fn(() => Promise.resolve({ would_match: 0 })),
  updateDispositionPolicy: vi.fn(() => Promise.resolve({})),
  previewDispositionDraft: vi.fn(() => Promise.resolve({ would_match: 0 })),
  deleteDispositionPolicy: vi.fn(() => Promise.resolve({})),
  reorderDispositionPolicies: vi.fn(() => Promise.resolve({})),
}))

const { default: DispositionRules, useRequestGate } = await import('./DispositionRules.jsx')

/** A promise whose settlement this test controls, so "late" is a fact rather than a race. */
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const rule = (name) => ({
  policy_id: `id-${name}`, name, action: 'archive', enabled: true,
  match: '[]', action_config: '{}', requires_approval: false,
})

/**
 * Reproduce the post-teardown environment for the duration of `fn`.
 *
 * jsdom's `window` is not configurable enough to delete outright, so it is replaced by an
 * accessor that throws the SAME ReferenceError React would hit after vitest disposes the
 * environment. Restored in a finally, so nothing leaks into another test.
 */
async function withEnvironmentGone(fn) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    get() { throw new ReferenceError('window is not defined') },
  })
  try {
    return await fn()
  } finally {
    if (original) Object.defineProperty(globalThis, 'window', original)
    else delete globalThis.window
  }
}

/** Record unhandled rejections without suppressing them — no preventDefault, nothing swallowed. */
function watchUnhandled() {
  const seen = []
  const onNode = (reason) => seen.push(reason)
  process.on('unhandledRejection', onNode)
  return { seen, stop: () => process.off('unhandledRejection', onNode) }
}

let root, container
const mount = async (el) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(el) })
}
const flush = async (n = 4) => {
  for (let k = 0; k < n; k++) await act(async () => { await Promise.resolve() })
}

beforeEach(() => {
  listDispositionPolicies.mockReset()
  listDispositionConflicts.mockReset()
})
afterEach(() => { unmountAll() })

describe('DispositionRules async teardown', () => {
  it('a late REJECTION after unmount does not reach React — the reported crash', async () => {
    const d = deferred()
    listDispositionPolicies.mockReturnValue(d.promise)
    await mount(createElement(DispositionRules, { embedded: true }))
    await flush()

    await act(async () => { root.unmount() })

    const watch = watchUnhandled()
    try {
      await withEnvironmentGone(async () => {
        d.reject(new Error('backend went away'))
        await new Promise((r) => setImmediate(r))
      })
      await new Promise((r) => setImmediate(r))
    } finally {
      watch.stop()
    }

    expect(watch.seen.map(String)).toEqual([])
  })

  it('a late SUCCESS after unmount does not reach React either', async () => {
    // The reported stack came through `.catch`, but `.then` calls setRules on the same dead
    // component. Guarding only the failure branch would leave half the defect in place.
    const d = deferred()
    listDispositionPolicies.mockReturnValue(d.promise)
    await mount(createElement(DispositionRules, { embedded: true }))
    await flush()

    await act(async () => { root.unmount() })

    const watch = watchUnhandled()
    try {
      await withEnvironmentGone(async () => {
        d.resolve([rule('late')])
        await new Promise((r) => setImmediate(r))
      })
      await new Promise((r) => setImmediate(r))
    } finally {
      watch.stop()
    }

    expect(watch.seen.map(String)).toEqual([])
  })

  // ── the gate itself ─────────────────────────────────────────────────────────────────────────
  // Tested directly rather than through the panel. Driving two overlapping loads from the UI
  // means finding a control that re-calls load(), which makes the test about that control's
  // wiring instead of about ordering; the first version of this test did exactly that and passed
  // for the wrong reason — the effect only calls load() while `rules == null`, so the second
  // request was never issued at all and the assertion was measuring a single load.

  it('drops a slow earlier request when a newer one has already settled', async () => {
    let begin
    const Probe = () => { begin = useRequestGate(); return null }
    await mount(createElement(Probe))

    const first = begin('rules')          // issued first…
    const second = begin('rules')         // …superseded before it settles
    expect(second()).toBe(true)
    expect(first()).toBe(false)
  })

  it('keeps streams independent, so one panel does not invalidate another', async () => {
    let begin
    const Probe = () => { begin = useRequestGate(); return null }
    await mount(createElement(Probe))

    const rules = begin('rules')
    const conflicts = begin('conflicts')   // a different stream must not cancel the rules load
    expect(rules()).toBe(true)
    expect(conflicts()).toBe(true)
  })

  it('rejects a request that started before unmount', async () => {
    let begin
    const Probe = () => { begin = useRequestGate(); return null }
    await mount(createElement(Probe))

    const inFlight = begin('rules')
    expect(inFlight()).toBe(true)
    await act(async () => { root.unmount() })
    expect(inFlight()).toBe(false)
  })

  it('still renders data under StrictMode, whose cleanup+remount a bare alive flag would break',
     async () => {
    // The invariant that catches the naive fix. StrictMode mounts, runs cleanup, and mounts
    // again on the same instance and the same refs; an `alive = false` set by that first cleanup
    // leaves the live component unable to apply ANY result, and the panel renders empty forever.
    // This must pass before and after.
    listDispositionPolicies.mockResolvedValue([rule('VISIBLE')])
    await mount(createElement(StrictMode, null, createElement(DispositionRules, { embedded: true })))
    await flush(8)

    expect(container.textContent).toMatch(/VISIBLE/)
  })

  it('still shows a load failure to a user who is actually looking at it', async () => {
    // The other invariant: guarding must not silence real errors on a MOUNTED component.
    listDispositionPolicies.mockRejectedValue(new Error('nope'))
    await mount(createElement(DispositionRules, { embedded: true }))
    await flush(6)

    expect(container.textContent).toMatch(/nope|could not|error|failed/i)
  })
})
