/**
 * Clicking a breakdown bar opens the files behind it.
 *
 * The assertions that matter here are the ones about HONESTY and REACH, because both failure modes
 * are silent:
 *
 *   · A drill-down whose list is shorter than its bar is a screen that under-reports without
 *     saying so. It happens for real on BY FILE TYPE, whose counts come from the server's
 *     whole-estate summary while the browser holds only the rows the inventory route returned — so
 *     the short case is tested, and the panel has to explain itself in numbers.
 *   · A row that only a mouse can open is a barrier shipped inside an accessibility product. The
 *     trigger is asserted to be a real <button> carrying aria-expanded/aria-controls, not a div.
 *
 * Membership is asserted to come from the SAME pass as the count for age and size, which is what
 * makes "the list matches the bar" a property of the code rather than a coincidence of fixtures.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import BucketFiles, { SEARCH_THRESHOLD, VISIBLE_CAP } from './BucketFiles.jsx'
import BreakdownBars from './BreakdownBars.jsx'
import { ageBucketDistribution, sizeBucketDistribution } from './discoveryDistributions.js'
import { formatMembers, searchRows, rowName } from './bucketMembers.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

afterEach(unmountAll)

// One container per mount, per testRoots.js — a root left mounted throws out of the scheduler
// after teardown and reddens CI with a green test list.
let container
const mount = (el) => {
  const made = createTestRoot()
  container = made.container
  act(() => { made.root.render(el) })
  return container
}
const files = (n, prefix = 'file') =>
  Array.from({ length: n }, (_, i) => ({ file: `${prefix}-${i}.docx`, path: `/dept/${prefix}` }))

describe('bucket membership comes from the pass that counts', () => {
  it('gives every age bucket exactly the rows its count claims', () => {
    const now = Date.now()
    const yearsAgo = (y) => new Date(now - y * 365.25 * 24 * 3600 * 1000).toISOString()
    const rows = [
      { file: 'new.docx', source_modified: yearsAgo(0.5) },
      { file: 'mid.docx', source_modified: yearsAgo(2) },
      { file: 'old.docx', source_modified: yearsAgo(9) },
      { file: 'undated.docx' },
    ]
    const dist = ageBucketDistribution(rows)
    for (const b of dist.buckets) {
      expect(b.rows).toHaveLength(b.count)          // the property, per bucket
    }
    // …and the rows are the RIGHT ones, not merely the right number.
    const byKey = Object.fromEntries(dist.buckets.map((b) => [b.key, b.rows.map(rowName)]))
    expect(byKey.lt1).toEqual(['new.docx'])
    expect(byKey['1to3']).toEqual(['mid.docx'])
    expect(byKey.gt5).toEqual(['old.docx'])
    expect(byKey.unknown).toEqual(['undated.docx'])
  })

  it('gives every size bucket exactly the rows its count claims', () => {
    const rows = [
      { file: 'tiny.docx', size_kb: 10 },
      { file: 'big.docx', size_kb: 50_000 },
      { file: 'nosize.docx' },
    ]
    const dist = sizeBucketDistribution(rows)
    for (const b of dist.buckets) expect(b.rows).toHaveLength(b.count)
    const byKey = Object.fromEntries(dist.buckets.map((b) => [b.key, b.rows.map(rowName)]))
    expect(byKey.tiny).toEqual(['tiny.docx'])
    expect(byKey.large).toEqual(['big.docx'])
    expect(byKey.unknown).toEqual(['nosize.docx'])
  })

  it('matches file types against the INVENTORY, not the scanned rows', () => {
    // The grey buckets are the ones `files` cannot contain: only assessable formats are scanned.
    // Matching against `files` would open "Other" onto an empty list on exactly the estates where
    // it is largest — the defect this argument order exists to prevent.
    const invRows = [{ file: 'a.docx' }, { file: 'clip.mp4' }, { file: 'notes.zip' }]
    const scanned = [{ file: 'a.docx' }]
    const members = formatMembers(invRows, scanned)
    expect(members.get('av').map(rowName)).toEqual(['clip.mp4'])
    expect(members.get('other').map(rowName)).toEqual(['notes.zip'])
    // Falls back to the scanned rows only when there is no inventory to read.
    expect(formatMembers(null, scanned).get('docx').map(rowName)).toEqual(['a.docx'])
  })
})

describe('the drill-down list', () => {
  it('opens from a real button that says it is expandable', () => {
    mount(createElement(BreakdownBars, {
      buckets: [{ key: 'other', label: 'Other', count: 2 }],
      columns: '110px 1fr 56px', colorOf: () => '#ccc', idPrefix: 'type-files',
      membersOf: () => files(2, 'other'),
    }))
    const btn = container.querySelector('button[aria-controls="type-files-other"]')
    expect(btn).toBeTruthy()
    expect(btn.tagName).toBe('BUTTON')                     // reachable by Tab, fires on Enter/Space
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    expect(container.querySelector('#type-files-other')).toBeNull()

    act(() => { btn.click() })
    expect(btn.getAttribute('aria-expanded')).toBe('true')
    const panel = container.querySelector('#type-files-other')
    expect(panel).toBeTruthy()
    expect(panel.querySelectorAll('li')).toHaveLength(2)
    expect(panel.textContent).toContain('other-0.docx')

    act(() => { btn.click() })                             // and it closes again
    expect(container.querySelector('#type-files-other')).toBeNull()
  })

  it('leaves a bucket with no rows to show as a plain row, not an inert button', () => {
    mount(createElement(BreakdownBars, {
      buckets: [{ key: 'other', label: 'Other', count: 4 }],
      columns: '110px 1fr 56px', colorOf: () => '#ccc', idPrefix: 'type-files',
      membersOf: () => [],
    }))
    expect(container.querySelector('button')).toBeNull()
    expect(container.textContent).toContain('Other')
  })

  it('scrolls rather than growing without bound', () => {
    mount(createElement(BucketFiles, {
      id: 'p', bucket: { key: 'other', label: 'Other', count: 60 }, rows: files(60),
    }))
    const list = container.querySelector('ul[aria-label="Files in Other"]')
    expect(list.style.overflowY).toBe('auto')
    expect(list.style.maxHeight).toBe('260px')
    // Focusable, or a keyboard user cannot scroll the region at all.
    expect(list.getAttribute('tabindex')).toBe('0')
  })

  it('offers search past the threshold and not below it', () => {
    mount(createElement(BucketFiles, {
      id: 'p', bucket: { key: 'k', label: 'Small', count: SEARCH_THRESHOLD }, rows: files(SEARCH_THRESHOLD),
    }))
    expect(container.querySelector('input[type="search"]')).toBeNull()

    mount(createElement(BucketFiles, {
      id: 'p', bucket: { key: 'k', label: 'Big', count: SEARCH_THRESHOLD + 1 },
      rows: files(SEARCH_THRESHOLD + 1),
    }))
    expect(container.querySelector('input[type="search"]')).toBeTruthy()
  })

  it('never lets a search result read as the bucket total', () => {
    const rows = [...files(9, 'alpha'), { file: 'needle.pdf', path: '/x' }]
    mount(createElement(BucketFiles, {
      id: 'p', bucket: { key: 'k', label: 'Mixed', count: rows.length }, rows,
    }))
    const input = container.querySelector('input[type="search"]')
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
      setter.call(input, 'needle')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.querySelectorAll('li')).toHaveLength(1)
    // Both numbers, so the filter cannot be mistaken for the estate.
    expect(container.textContent).toContain('showing 1 of 10')
  })

  it('SAYS SO when it holds fewer rows than the bar claims', () => {
    // The estate-inventory case: the bar counts 4,000 from the server summary, the browser read 3.
    mount(createElement(BucketFiles, {
      id: 'p', bucket: { key: 'other', label: 'Other', count: 4000 }, rows: files(3),
    }))
    const text = container.textContent
    expect(text).toContain('3')
    expect(text).toContain('4,000')
    expect(text).toMatch(/whole estate listing/i)
  })

  it('caps what it renders and says the cap is a cap', () => {
    mount(createElement(BucketFiles, {
      id: 'p', bucket: { key: 'k', label: 'Huge', count: VISIBLE_CAP + 25 },
      rows: files(VISIBLE_CAP + 25),
    }))
    expect(container.querySelectorAll('li')).toHaveLength(VISIBLE_CAP)
    expect(container.textContent).toContain(`of ${(VISIBLE_CAP + 25).toLocaleString()} matching`)
  })
})

describe('search', () => {
  it('treats an empty query as no filter, not as no matches', () => {
    const rows = files(3)
    expect(searchRows(rows, '')).toHaveLength(3)
    expect(searchRows(rows, '   ')).toHaveLength(3)
  })

  it('matches on the path as well as the name, case-insensitively', () => {
    const rows = [{ file: 'a.docx', path: '/Finance/Q3' }, { file: 'b.docx', path: '/HR' }]
    expect(searchRows(rows, 'finance').map(rowName)).toEqual(['a.docx'])
    expect(searchRows(rows, 'B.DOCX').map(rowName)).toEqual(['b.docx'])
  })
})
