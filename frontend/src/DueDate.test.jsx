import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// R19 · Due date on a document — the deadline half of "who does this, by when". Pins: seeding from
// the persisted value, the overdue badge (strictly-before-today), persisting a change / clearing via
// the decision API on kind='due_date', and the ownerless-deadline caution the design calls for.

let saved   // captures the last saveDecision(scanId, file, kind, value)
vi.mock('./api.js', () => ({
  saveDecision: (scanId, file, kind, value) => { saved = { scanId, file, kind, value }; return Promise.resolve({ ok: true }) },
}))

const { default: DueDate } = await import('./DueDate.jsx')

const NOW = new Date('2026-08-20T12:00:00Z').getTime()   // "today" = 2026-08-20

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(DueDate, { scanId: 's1', file: 'a.pdf', now: NOW, ...props }))
  })
  await act(async () => { await Promise.resolve() })
  return container
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const setDate = async (el, val) => {
  // Use the element's own realm so jsdom's brand check on the native value setter passes.
  const proto = el.ownerDocument.defaultView.HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set
  await act(async () => { setter.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })) })
}
const input = () => container.querySelector('input[type="date"]')

beforeEach(() => { saved = undefined })
afterEach(unmountAll)

describe('DueDate', () => {
  it('seeds the input from the persisted value and slices a full timestamp to a date', async () => {
    const c = await mount({ value: '2026-09-01T00:00:00+00:00', assignee: 'deva@acp.io' })
    expect(input().value).toBe('2026-09-01')
    expect(c.querySelector('.due-overdue')).toBeNull()          // future date, not overdue
    expect(c.querySelector('.due-noowner')).toBeNull()          // has an owner
  })

  it('shows the honest empty state with no date', async () => {
    const c = await mount({ value: '' })
    expect(input().value).toBe('')
    expect(c.textContent).toContain('No due date set')
    expect(c.querySelector('button')).toBeNull()                // no Clear button when empty
  })

  it('flags a past date as overdue, but not one due today', async () => {
    const past = await mount({ value: '2026-08-10', assignee: 'x@acp.io' })
    expect(past.querySelector('.due-overdue')).not.toBeNull()
    // A second, independent mount (afterEach tears both down) — due today is not yet overdue.
    const today = await mount({ value: '2026-08-20', assignee: 'x@acp.io' })
    expect(today.querySelector('.due-overdue')).toBeNull()
  })

  it('persists a chosen date via kind=due_date', async () => {
    const c = await mount({ value: '' })
    await setDate(input(), '2026-10-15')
    await act(async () => { await Promise.resolve() })
    expect(saved).toEqual({ scanId: 's1', file: 'a.pdf', kind: 'due_date', value: '2026-10-15' })
    expect(input().value).toBe('2026-10-15')
  })

  it('clears the date by saving null', async () => {
    const c = await mount({ value: '2026-09-01', assignee: 'd@acp.io' })
    await click([...c.querySelectorAll('button')].find((b) => b.textContent.includes('Clear')))
    await act(async () => { await Promise.resolve() })
    expect(saved).toEqual({ scanId: 's1', file: 'a.pdf', kind: 'due_date', value: null })
    expect(input().value).toBe('')
  })

  it('warns when a date is set on a document with no owner', async () => {
    const c = await mount({ value: '2026-09-01', assignee: '' })
    expect(c.querySelector('.due-noowner')).not.toBeNull()
    expect(c.textContent).toContain('a decoration')
  })

  it('renders nothing without a file', async () => {
    const c = await mount({ file: null })
    expect(c.textContent).toBe('')
  })
})
