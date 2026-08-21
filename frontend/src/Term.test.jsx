import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Term — the inline glossary tooltip. Pins: it's invisible until triggered, hover AND focus both
// trigger it (a mouse-only test would miss half of what this exists for), Escape dismisses it,
// an unrecognized glossary key degrades to the plain label rather than crashing, and the
// accessible wiring (role="tooltip", aria-describedby, aria-expanded) is actually present.

const { default: Term } = await import('./Term.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Term, { k: 'unreadable', children: 'could not be read', ...props }))
  })
  return container
}
const trigger = (c) => c.querySelector('.terminfo')
afterEach(unmountAll)

describe('Term', () => {
  it('renders the label with no definition visible until triggered', async () => {
    const c = await mount()
    expect(c.textContent).toContain('could not be read')
    expect(c.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('shows the definition on hover (mouseenter)', async () => {
    const c = await mount()
    // React synthesizes onMouseEnter from the native, bubbling `mouseover` event — mouseenter
    // itself does not bubble, which is what React's delegated listener actually needs to see.
    await act(async () => { trigger(c).dispatchEvent(new MouseEvent('mouseover', { bubbles: true })) })
    const tip = c.querySelector('[role="tooltip"]')
    expect(tip).not.toBeNull()
    expect(tip.textContent).toContain('password-protected')
  })

  it('shows the definition on keyboard focus, not only on hover', async () => {
    const c = await mount()
    await act(async () => { trigger(c).focus() })
    expect(c.querySelector('[role="tooltip"]')).not.toBeNull()
  })

  it('links the trigger to the definition via aria-describedby, and marks it expanded', async () => {
    const c = await mount()
    await act(async () => { trigger(c).focus() })
    const btn = trigger(c)
    const tip = c.querySelector('[role="tooltip"]')
    expect(btn.getAttribute('aria-describedby')).toBe(tip.id)
    expect(btn.getAttribute('aria-expanded')).toBe('true')
  })

  it('closes on Escape', async () => {
    const c = await mount()
    const btn = trigger(c)
    await act(async () => { btn.focus() })
    expect(c.querySelector('[role="tooltip"]')).not.toBeNull()
    await act(async () => { btn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(c.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('degrades to the plain label for an unrecognized glossary key, never a crash', async () => {
    const c = await mount({ k: 'not-a-real-key' })
    expect(c.textContent).toBe('could not be read')
    expect(c.querySelector('.terminfo')).toBeNull()
  })
})
