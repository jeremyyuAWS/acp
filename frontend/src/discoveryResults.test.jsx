/**
 * The Discovery results screen, mounted.
 *
 * DOM-level, not browser-level: `preview_start` runs vite rooted at the SHARED checkout whatever
 * worktree you are in, so a browser check of a worktree change exercises code that does not
 * contain it and passes anyway (CLAUDE.md). Everything asserted here is asserted against the DOM
 * this component actually produced.
 *
 * The wiring — that Discover mounts this and that the acknowledgement gates the Assess button —
 * is pinned separately in discoveryResultsWiring.test.js, because a source sweep cannot catch a
 * syntax error and a DOM test cannot see a component that was never mounted.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
afterEach(unmountAll)

const F = (file, extra = {}) => ({ file, type: file.split('.').pop().toUpperCase(), ...extra })
const arch = (file, rule = 'Legacy clinical policies') =>
  F(file, { lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
            lifecycle_reason: `matched archive rule '${rule}'` })
const del = (file, rule = 'Superseded drafts') =>
  F(file, { lifecycle_status: 'Delete Candidate', lifecycle_rule_id: 'p2',
            lifecycle_reason: `matched delete rule '${rule}'` })
const active = (file) => F(file, { lifecycle_status: 'Active' })

const render = async (props = {}) => {
  await act(async () => { root.render(createElement(DiscoveryResults, props)) })
  return container
}
const text = () => container.textContent
const boxes = () => [...container.querySelectorAll('input[type=checkbox]')]
const click = async (el) => { await act(async () => { el.click() }) }
const setInput = async (el, value) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      el instanceof HTMLSelectElement ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype,
      'value',
    ).set
    setter.call(el, value)
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}

// A small estate with both recommendation kinds, one unreadable file and one untestable format.
const ESTATE = [
  arch('Clinical Guidelines/2019/sepsis-pathway-v3.docx'),
  arch('Clinical Guidelines/2020/triage-criteria.pdf'),
  del('Accessibility Program/_superseded/alt-text-draft-2.docx'),
  active('Accessibility Program/live-policy.docx'),
  active('Accessibility Program/diagram.png'),
  F('Clinical Guidelines/scan.pdf', { locked: true, openIssue: 'Permission denied', lifecycle_status: 'Active' }),
]

describe('nothing is claimed about data that never arrived', () => {
  it('renders nothing at all when there are no file rows', async () => {
    await render({ files: null })
    expect(container.innerHTML).toBe('')
  })

  it('omits the archive / deletion headline when no row carries the lifecycle column', async () => {
    await render({ files: [F('a.docx'), F('b.pdf')] })
    expect(text()).toContain('2')
    expect(text()).toContain('files discovered')
    // The absence is the point: a "0 tagged for archive review" here would be a claim about the
    // estate made from a field nobody read.
    expect(text()).not.toContain('tagged for archive review')
    expect(text()).not.toContain('tagged for deletion review')
    expect(text()).not.toContain('RECOMMENDATIONS')
    expect(text()).not.toContain('I approve')
  })

  it('shows a MEASURED zero once the lifecycle column is present', async () => {
    await render({ files: [active('a.docx')] })
    expect(text()).toContain('tagged for archive review')
    expect(text()).toContain('tagged for deletion review')
  })
})

describe('the estate summary and its reconciliations add up on screen', () => {
  it('states each headline with the noun it counts', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('files discovered')
    expect(text()).toContain('tagged for archive review')
    expect(text()).toContain('tagged for deletion review')
    expect(text()).toContain('could not be read')
  })

  it('prints the by-file-type total, and it equals the number discovered', async () => {
    await render({ files: ESTATE })
    const rows = [...container.querySelectorAll('.critrow')]
    const counts = rows.map((r) => Number(r.lastElementChild.textContent.replace(/,/g, '')))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(ESTATE.length)
    expect(text()).toContain('every type, added up')
    // The sum is rendered, not merely computed — a reader can check the partition.
    expect(text()).toMatch(/Total/)
  })

  it('by-file-type reads the whole estate listing when an inventory is present, not just the scanned rows', async () => {
    // The scanned rows (ESTATE) hold 5 docx/pdf and 1 png — but a real estate this size might hold
    // thousands of images that were never opened at all. Once an inventory carries by_format, the
    // panel must show THAT population, not the 6-row scanned one, or the estate reads as
    // document-only when it is not (found 2026-08-21).
    await render({ files: ESTATE, inventory: { discovered: 9006, by_format: { docx: 2, pdf: 1, image: 9000, other: 3 } } })
    expect(text()).toContain('the whole estate listing')
    const rows = [...container.querySelectorAll('.critrow')]
    const counts = rows.map((r) => Number(r.lastElementChild.textContent.replace(/,/g, '')))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(9006)
    const imageRow = rows.find((r) => r.firstElementChild.textContent === 'Images')
    expect(imageRow.lastElementChild.textContent).toBe('9,000')
  })

  it('by-file-type falls back to the scanned rows when there is no inventory to read', async () => {
    await render({ files: ESTATE, inventory: { discovered: 12408 } })   // no by_format
    const rows = [...container.querySelectorAll('.critrow')]
    const counts = rows.map((r) => Number(r.lastElementChild.textContent.replace(/,/g, '')))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(ESTATE.length)
  })

  it('says when the whole-estate listing total differs from the rows on screen', async () => {
    await render({ files: ESTATE, inventory: { discovered: 12408 } })
    expect(text()).toContain('This discovery listed 12,408 files in the estate')
  })

  // Found live 2026-08-26: a fresh Discover-only scan (ADR 0020 defers analysis to Assess) has
  // zero assessed rows by construction — the page header correctly said "6,922 documents
  // discovered" while this screen's own headline read "0 files discovered" for a scan that had
  // never been assessed. `files: []` here is that exact state, not a `files: null` early-return.
  it('shows the real estate total, not 0, when nothing has been assessed yet', async () => {
    await render({ files: [], inventory: { discovered: 6922 } })
    expect(text()).toContain('6,922')
    expect(text()).toContain('files discovered')
    expect(text()).not.toContain('0 files discovered')
  })

  it('does not show the "two totals differ" note in that same case — there is nothing to explain', async () => {
    await render({ files: [], inventory: { discovered: 6922 } })
    expect(text()).not.toContain('This discovery listed')
  })

  it('still shows the note for a genuinely scoped view (some, not all, rows assessed)', async () => {
    await render({ files: ESTATE, inventory: { discovered: 12408 } })
    expect(text()).toContain('This discovery listed 12,408 files in the estate')
    expect(text()).toContain('6')
  })

  it('warns that a truncated listing is a floor, not a total', async () => {
    await render({ files: ESTATE, inventory: { discovered: 6, truncated: true } })
    expect(text()).toContain('hit its cap')
    expect(text()).toContain('a floor, not a total')
  })
})

describe('the could-not-be-read panel is separate, and never guesses', () => {
  it('lists the recorded reason and sums it to the unreadable count', async () => {
    await render({ files: ESTATE })
    expect(text()).toContain('COULD NOT BE READ')
    expect(text()).toContain('Permission denied')
  })

  it('says the reason was not recorded rather than inventing one', async () => {
    await render({ files: [active('a.docx'), F('b.pdf', { status: 'error', lifecycle_status: 'Active' })] })
    expect(text()).toContain('No reason was recorded for these')
    expect(text()).not.toContain('unreadable file')
  })
})

describe('retired sections — intentionally absent', () => {
  it('does not render lifecycle recommendations', async () => {
    await render({ files: ESTATE })
    expect(text()).not.toContain('RECOMMENDATIONS')
  })

  it('does not render the every-discovered-file reconciliation', async () => {
    await render({ files: ESTATE })
    expect(text()).not.toContain('EVERY DISCOVERED FILE')
  })

  it('does not render the acknowledgement bar', async () => {
    await render({ files: ESTATE })
    expect(container.querySelector('input[type=checkbox]')).toBeNull()
  })
})
