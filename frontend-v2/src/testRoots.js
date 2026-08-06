// Mount React roots in a test so they can all be torn down again.
//
// A root left mounted keeps work in React's concurrent scheduler after the last assertion. When
// vitest tears the jsdom environment down first, that work reaches getActiveElementDeep and throws
// `ReferenceError: window is not defined` as an UNHANDLED error — every test still reports passed,
// and vitest exits non-zero on the error count alone. A CI job that reddens at random, with a green
// test list, is one that gets re-run rather than fixed.
//
// It is not hypothetical: #103 hit it in inventoryAgreesWithDrawer, and #108 in discoverScopeLine,
// which failed 1 full-suite run in 4 on a clean checkout. Both were fixed with a hand-written
// afterEach. This is that fix as one implementation, because the hand-written form has two traps:
//
//   - a `root` declared inside a mount helper is not reachable from afterEach at all, and
//   - a file that mounts more than once (a second helper, or a loop) unmounts only the last root.
//
// Both are shapes that exist in this suite, and neither is visible when the tests pass.
//
// Usage — createTestRoot() per mount, and one afterEach for the file:
//
//   import { createTestRoot, unmountAll } from './testRoots.js'
//   afterEach(unmountAll)
//   const mount = async (props) => {
//     const { container, root } = createTestRoot()
//     await act(async () => { root.render(createElement(Thing, props)) })
//     return container
//   }
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

const mounted = []

/** A detached-then-attached container with a React root, both remembered for unmountAll(). */
export function createTestRoot() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  mounted.push({ root, container })
  return { container, root }
}

/** Unmount every root this file mounted, inside act(), and drop its container. */
export async function unmountAll() {
  // splice(0) empties the list as it reads it, so a failure partway through cannot leave an
  // already-unmounted root queued for a second teardown on the next test.
  for (const { root, container } of mounted.splice(0)) {
    await act(async () => { root.unmount() })
    container.remove()
  }
}

/** Test seam — how many roots are currently tracked. */
export const _trackedCount = () => mounted.length
