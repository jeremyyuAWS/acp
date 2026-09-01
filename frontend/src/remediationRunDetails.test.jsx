import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// The progressive-disclosure shell for the Remediate tab. Two things are being pinned here, and
// they pull in opposite directions on purpose:
//
//   · the DISCLOSURE — eight reference panels stop standing between a reviewer and the next
//     decision, which means their content really is absent from the document when collapsed
//     (asserted, because "collapsed" that still renders everything buys nothing);
//   · the EXEMPTION — a section marked `alert` escapes the disclosure entirely and is counted in
//     writing on the toggle. If that ever regresses, a blocking verification failure goes quiet
//     behind a control, which is the one failure this component must not have.

const { default: RemediationRunDetails } = await import('./RemediationRunDetails.jsx')

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })

const render = async (props) => {
  await act(async () => { root.render(createElement(RemediationRunDetails, props)) })
  return container
}
const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}
const toggle = () => container.querySelector('[data-testid="rundetails-toggle"]')
const shell = () => container.querySelector('[data-testid="rundetails"]')
const sections = () => [...container.querySelectorAll('[data-testid="rundetails-section"]')]
const alerts = () => [...container.querySelectorAll('[data-testid="rundetails-alert"]')]
const seen = (t) => (container.textContent || '').includes(t)
// Looked up by id WITHOUT a selector: the id is generated, and querySelector would need it to be
// selector-safe. This asserts the aria-controls reference resolves, not that it happens to escape.
const byId = (id, where = container) => [...where.querySelectorAll('[id]')].find((n) => n.id === id) || null

const SECTIONS = [
  { id: 'reviewer-analytics', title: 'Reviewer analytics', hint: 'throughput and agreement',
    children: createElement('p', null, 'REVIEWER_ANALYTICS_BODY') },
  { id: 'ai-quality', title: 'AI quality', children: createElement('p', null, 'AI_QUALITY_BODY') },
  { id: 'audit-history', title: 'Audit history', children: createElement('p', null, 'AUDIT_HISTORY_BODY') },
]

// ───────────────────────────────────────────────────────────────────────────────────────────
// Collapsed by default — the whole point of the surface.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('collapsed by default', () => {
  it('renders the toggle but none of the section content', async () => {
    await render({ sections: SECTIONS })
    expect(toggle()).not.toBeNull()
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(seen('REVIEWER_ANALYTICS_BODY')).toBe(false)
    expect(seen('AI_QUALITY_BODY')).toBe(false)
    expect(sections()).toHaveLength(0)
  })

  it('does not even render the section headings, so nothing is merely visually hidden', async () => {
    // A "collapsed" panel that still puts its headings in the document is still in the reading
    // order and still in the tab order. The disclosure has to actually remove it.
    await render({ sections: SECTIONS })
    expect(seen('Reviewer analytics')).toBe(false)
    expect(seen('throughput and agreement')).toBe(false)
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// Uncontrolled — the component owns its own state when no onToggle is given.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('uncontrolled disclosure', () => {
  it('clicking the toggle reveals the sections and flips aria-expanded', async () => {
    await render({ sections: SECTIONS })
    await click(toggle())
    expect(toggle().getAttribute('aria-expanded')).toBe('true')
    expect(seen('REVIEWER_ANALYTICS_BODY')).toBe(true)
    expect(seen('AI_QUALITY_BODY')).toBe(true)
    expect(sections()).toHaveLength(3)
  })

  it('clicking again collapses it back', async () => {
    await render({ sections: SECTIONS })
    await click(toggle())
    await click(toggle())
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(seen('REVIEWER_ANALYTICS_BODY')).toBe(false)
  })

  it('seeds its state from `open`, so a host can start it expanded without controlling it', async () => {
    await render({ sections: SECTIONS, open: true })
    expect(toggle().getAttribute('aria-expanded')).toBe('true')
    expect(seen('AUDIT_HISTORY_BODY')).toBe(true)
  })

  it('each revealed section is a real, keyboard-operable disclosure', async () => {
    // Native <details>/<summary> is the whole accessibility story for the inner panels — no focus
    // handling and no aria-expanded of our own to drift out of sync.
    await render({ sections: SECTIONS, open: true })
    for (const d of sections()) {
      expect(d.tagName).toBe('DETAILS')
      expect(d.querySelector('summary')).not.toBeNull()
    }
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// Controlled — onToggle is supplied, so the host owns the state and the component must not
// second-guess it. The failure this guards is a component that reports the intent AND acts on it,
// which desynchronises from the host on the first click.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('controlled disclosure', () => {
  it('calls onToggle with the negated value and does NOT self-toggle', async () => {
    const onToggle = vi.fn()
    await render({ sections: SECTIONS, open: false, onToggle })
    await click(toggle())
    expect(onToggle).toHaveBeenCalledTimes(1)
    expect(onToggle).toHaveBeenCalledWith(true)
    // `open` stayed false, so the surface stayed shut — the host decides, not the button.
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(seen('REVIEWER_ANALYTICS_BODY')).toBe(false)
    expect(sections()).toHaveLength(0)
  })

  it('negates from the CURRENT open value, not from a remembered one', async () => {
    const onToggle = vi.fn()
    await render({ sections: SECTIONS, open: true, onToggle })
    expect(seen('REVIEWER_ANALYTICS_BODY')).toBe(true)
    await click(toggle())
    expect(onToggle).toHaveBeenCalledWith(false)
  })

  it('follows the host when `open` changes', async () => {
    const onToggle = vi.fn()
    await render({ sections: SECTIONS, open: false, onToggle })
    await render({ sections: SECTIONS, open: true, onToggle })
    expect(toggle().getAttribute('aria-expanded')).toBe('true')
    expect(seen('AI_QUALITY_BODY')).toBe(true)
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// The exemption. This is the section that matters most.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('alert sections escape the disclosure', () => {
  const BLOCKING = {
    id: 'verify', title: 'Verification failed', alert: true,
    hint: '2 documents still fail after remediation',
    children: createElement('p', null, 'BLOCKING_FAILURE_BODY'),
  }

  it('renders its content while the surface is collapsed', async () => {
    await render({ sections: [...SECTIONS, BLOCKING] })
    expect(toggle().getAttribute('aria-expanded')).toBe('false')
    expect(seen('BLOCKING_FAILURE_BODY')).toBe(true)
    expect(seen('Verification failed')).toBe(true)
    // …while the non-alert siblings stay behind the disclosure.
    expect(seen('REVIEWER_ANALYTICS_BODY')).toBe(false)
  })

  it('is hoisted ABOVE the toggle, not left below it', async () => {
    await render({ sections: [...SECTIONS, BLOCKING] })
    const position = alerts()[0].compareDocumentPosition(toggle())
    // eslint-disable-next-line no-bitwise
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('is announced in the toggle label as "(1 needs attention)"', async () => {
    await render({ sections: [...SECTIONS, BLOCKING] })
    expect(toggle().textContent).toContain('Run details')
    expect(toggle().textContent).toContain('(1 needs attention)')
  })

  it('says nothing about attention when nothing needs it', async () => {
    await render({ sections: SECTIONS })
    expect(toggle().textContent).not.toMatch(/attention/i)
  })

  it('counts more than one, and reads as English when it does', async () => {
    await render({ sections: [...SECTIONS, BLOCKING, { ...BLOCKING, id: 'engine', title: 'Engine error' }] })
    expect(toggle().textContent).toContain('(2 need attention)')
    expect(alerts()).toHaveLength(2)
  })

  it('does not signal the state by colour alone', async () => {
    // WCAG 1.4.1. The count is in the button's own text, and the alert carries a written badge —
    // strip every style attribute and the state must still be readable.
    await render({ sections: [...SECTIONS, BLOCKING] })
    const stripped = shell().cloneNode(true)
    for (const n of stripped.querySelectorAll('[style]')) n.removeAttribute('style')
    expect(stripped.textContent).toContain('1 needs attention')
    expect(stripped.textContent).toMatch(/needs attention/i)
  })

  it('stays visible and is not duplicated once the surface is expanded', async () => {
    await render({ sections: [...SECTIONS, BLOCKING], open: true })
    expect(alerts()).toHaveLength(1)
    expect(seen('BLOCKING_FAILURE_BODY')).toBe(true)
    // The alert is not also dealt out as one of the disclosed <details>.
    expect(sections()).toHaveLength(3)
    expect(sections().some((d) => d.textContent.includes('BLOCKING_FAILURE_BODY'))).toBe(false)
  })

  it('an alert is not put behind a <details> of its own', async () => {
    await render({ sections: [BLOCKING] })
    expect(alerts()[0].closest('details')).toBeNull()
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// Empty sections. An empty disclosure costs a click to learn there was nothing behind it.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('sections with no body are skipped entirely', () => {
  it('renders no stray <details> for null, undefined or false children', async () => {
    await render({ open: true, sections: [
      { id: 'a', title: 'Reviewer analytics', children: null },
      { id: 'b', title: 'AI quality', children: undefined },
      { id: 'c', title: 'Delivery', children: false },
      { id: 'd', title: 'Audit history', children: createElement('p', null, 'AUDIT_HISTORY_BODY') },
    ] })
    expect(sections()).toHaveLength(1)
    expect(seen('AUDIT_HISTORY_BODY')).toBe(true)
    expect(seen('Reviewer analytics')).toBe(false)
    expect(seen('Delivery')).toBe(false)
  })

  it('an empty alert section is skipped too, and does not inflate the count', async () => {
    await render({ sections: [
      { id: 'x', title: 'Engine error', alert: true, children: null },
      { id: 'd', title: 'Audit history', children: createElement('p', null, 'AUDIT_HISTORY_BODY') },
    ] })
    expect(alerts()).toHaveLength(0)
    expect(toggle().textContent).not.toMatch(/attention/i)
  })

  it('keeps a section whose body is 0 or an empty string — those are content, not absence', async () => {
    await render({ open: true, sections: [
      { id: 'a', title: 'Worker queue', children: 0 },
      { id: 'b', title: 'Business risk', children: '' },
    ] })
    expect(sections()).toHaveLength(2)
  })

  it('renders nothing at all when every section is empty', async () => {
    await render({ sections: [{ id: 'a', title: 'Reviewer analytics', children: null }] })
    expect(shell()).toBeNull()
    expect(container.textContent).toBe('')
  })

  it('renders nothing at all for no sections', async () => {
    await render({})
    expect(container.textContent).toBe('')
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// defaultOpen — derived from content by the caller, honoured here.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('defaultOpen', () => {
  it('opens those sections on reveal and leaves the rest shut', async () => {
    await render({ sections: [
      { id: 'a', title: 'Reviewer analytics', defaultOpen: true,
        children: createElement('p', null, 'REVIEWER_ANALYTICS_BODY') },
      { id: 'b', title: 'AI quality', children: createElement('p', null, 'AI_QUALITY_BODY') },
    ] })
    await click(toggle())
    const [a, b] = sections()
    expect(a.open).toBe(true)
    expect(b.open).toBe(false)
  })

  it('is absent rather than false when not asked for', async () => {
    await render({ sections: SECTIONS, open: true })
    expect(sections().every((d) => d.open === false)).toBe(true)
  })
})

// ───────────────────────────────────────────────────────────────────────────────────────────
// Accessibility wiring.
// ───────────────────────────────────────────────────────────────────────────────────────────
describe('accessibility', () => {
  it('is a landmark named by `title`', async () => {
    await render({ sections: SECTIONS })
    expect(shell().tagName).toBe('SECTION')
    expect(shell().getAttribute('aria-label')).toBe('Run details')
  })

  it('takes its accessible name from a custom title', async () => {
    await render({ sections: SECTIONS, title: 'Operational detail' })
    expect(shell().getAttribute('aria-label')).toBe('Operational detail')
    expect(toggle().textContent).toContain('Operational detail')
  })

  it('the toggle is a real button, not a div with a handler', async () => {
    await render({ sections: SECTIONS })
    expect(toggle().tagName).toBe('BUTTON')
    expect(toggle().getAttribute('type')).toBe('button')
  })

  it('aria-controls resolves to the panel it actually controls', async () => {
    await render({ sections: SECTIONS, open: true })
    const id = toggle().getAttribute('aria-controls')
    expect(id).toBeTruthy()
    // Usable as a plain CSS selector — no escaping required by whoever links to it.
    expect(id).toMatch(/^[A-Za-z][\w-]*$/)
    const panel = byId(id)
    expect(panel).not.toBeNull()
    expect(panel.getAttribute('data-testid')).toBe('rundetails-panel')
    expect(panel.textContent).toContain('REVIEWER_ANALYTICS_BODY')
  })

  it('aria-controls still resolves while collapsed — a dangling reference is not a closed panel', async () => {
    await render({ sections: SECTIONS })
    const id = toggle().getAttribute('aria-controls')
    expect(byId(id)).not.toBeNull()
  })

  it('gives two instances distinct panel ids', async () => {
    // Both panels live in one document on the Remediate tab if the surface is ever used twice;
    // a hardcoded id would make aria-controls point at the wrong one.
    const { container: c2, root: r2 } = createTestRoot()
    await render({ sections: SECTIONS })
    await act(async () => { r2.render(createElement(RemediationRunDetails, { sections: SECTIONS })) })
    const a = toggle().getAttribute('aria-controls')
    const b = c2.querySelector('[data-testid="rundetails-toggle"]').getAttribute('aria-controls')
    expect(a).not.toBe(b)
    // Both resolve, each within its own tree.
    expect(byId(a)).not.toBeNull()
    expect(byId(b, c2)).not.toBeNull()
  })

  it('uses each section id as its DOM id', async () => {
    await render({ sections: SECTIONS, open: true })
    expect(byId('reviewer-analytics')).not.toBeNull()
    expect(byId('ai-quality')).not.toBeNull()
  })
})
