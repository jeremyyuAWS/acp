/**
 * Test helper — render a screen in jsdom and open every collapsed AccordionSection.
 *
 * The 2026-09-02 UI-simplification PRD puts Overview's detail sections behind disclosures, and
 * several of them are collapsed on load. A test that asserts on their content has to open them,
 * and it must do so through the real control: the sections render `{open && children}`, so a
 * collapsed panel genuinely has no content in the DOM. Reading `innerHTML` off a static render
 * would therefore assert on markup nobody can see — a check that cannot fail.
 *
 * Not a component and not scanned by the mounted/unmounted audits: this is a `.js` module with no
 * default export, so `unmountedComponents.test.jsx` (which reads `.jsx` files with a default
 * export) never sees it.
 */
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { afterEach } from 'vitest'

const mounted = new Set()

// Overview starts an asynchronous inventory read on mount. Leaving its React root alive until
// jsdom tears `window` down lets that promise dispatch state into a dead environment — a CI-only
// unhandled error whose timing depends on how quickly the rest of the suite finishes.
afterEach(() => {
  for (const entry of mounted) {
    act(() => { entry.root.unmount() })
    entry.container.remove()
  }
  mounted.clear()
})

/** Every accordion header currently reporting itself collapsed. */
export const collapsedToggles = (root) =>
  [...root.querySelectorAll('button.acc-toggle[aria-expanded="false"]')]

/**
 * Mount `element` and click open every collapsed accordion, repeating until none are left —
 * one section's content can itself contain another accordion (EstateProgressPanel's three).
 * Returns the container so callers can query it; `container.innerHTML` is the usual read.
 */
export function mountExpanded(element, { container = document.createElement('div') } = {}) {
  document.body.appendChild(container)
  const root = createRoot(container)
  mounted.add({ root, container })
  act(() => { root.render(element) })
  for (let pass = 0; pass < 5; pass++) {
    const shut = collapsedToggles(container)
    if (!shut.length) break
    act(() => { shut.forEach((b) => b.click()) })
  }
  return container
}

/** `mountExpanded`, read back as HTML — the shape most of these tests actually assert on. */
export const htmlExpanded = (element) => mountExpanded(element).innerHTML
