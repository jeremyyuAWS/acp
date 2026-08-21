import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import { classificationCoverage, hasClassificationData, hasDepartment, hasClassTag,
         CLASSIFICATION_TAGS, NO_CLASSIFICATION_TITLE } from './classificationData.js'

// An unclassified estate is reported as UNCLASSIFIED, not as an estate with nothing in it.
//
// Discover carries a triage surface — documents grouped by department, PII / legal-hold /
// public-facing chips, an exposure-and-risk chart, a confirm-or-correct workflow. On the SIM estate
// all of it is populated. On a REAL scan none of it is, and until now the screen did not say so:
// the whole estate landed in one "Unassigned" group under a chart reading 100% internal with every
// risk flag at zero.
//
// Verified in the tree rather than inferred: `file_records` (store.py:70) has no department and no
// tags, `get_scan` (store.py:1752) projects that table alone, and store.py:4647 says outright that
// "department has no scan-derived source yet, so on most estates that bucket IS the estate."
//
// EVERY ONE OF THOSE NUMBERS IS TRUE AND THE READING IS FALSE. "0 legal-hold" asserts that this
// estate holds no documents under legal hold — a finding nobody obtained, on the screen a
// compliance reader opens precisely to find them.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

const plain = (n) => Array.from({ length: n }, (_, i) => ({
  file: `f${i}.docx`, name: `f${i}.docx`, type: 'DOCX', status: 'done', score: 90,
}))
const classified = () => [
  { ...plain(1)[0], department: 'Legal', tags: ['legal-hold'] },
  { ...plain(2)[1], department: 'HR', tags: ['PII'] },
]

describe('did classification reach the screen', () => {
  it('is false for rows a real scan produces', () => {
    // No department column, no tags column — this is the shape get_scan returns today.
    expect(hasClassificationData(plain(12))).toBe(false)
    const c = classificationCoverage(plain(12))
    expect(c).toEqual({ total: 12, department: 0, tagged: 0, any: false })
  })

  it('is true as soon as either half arrives', () => {
    // OR, not AND: the two have different sources and can arrive apart. An estate with departments
    // and no tags still has something true to show.
    expect(hasClassificationData([{ file: 'a', department: 'Legal' }])).toBe(true)
    expect(hasClassificationData([{ file: 'a', tags: ['PII'] }])).toBe(true)
  })

  it('does not count a STATUS tag as classification', () => {
    // certified / needs-review / auto-fixable are workflow state, not sensitivity. Counting them
    // would light the whole triage surface on an estate nobody classified — the exact failure this
    // module exists to prevent, reached by being too generous.
    expect(hasClassTag({ tags: ['certified', 'needs-review', 'auto-fixable'] })).toBe(false)
    expect(hasClassTag({ tags: ['certified', 'PII'] })).toBe(true)
  })

  it('does not count an empty-string department', () => {
    expect(hasDepartment({ department: '   ' })).toBe(false)
    expect(hasDepartment({ department: 'Legal' })).toBe(true)
    expect(hasDepartment({})).toBe(false)
  })

  it('returns null when nothing was read, which is not the same as empty', () => {
    // "we did not look" and "we looked and found none" must not collapse. One is a gap; the other
    // is a measurement.
    expect(classificationCoverage(null)).toBe(null)
    expect(classificationCoverage(undefined)).toBe(null)
    expect(classificationCoverage([])).toEqual({ total: 0, department: 0, tagged: 0, any: false })
  })

  it('offers the same tag list Discover does', () => {
    // A tag present in one list and not the other would silently never be counted.
    expect(CLASSIFICATION_TAGS).toEqual(['PII', 'legal-hold', 'public-facing', 'high-traffic'])
  })
})

let container, root
const mount = async (files) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files, busy: false, onScan: () => {} }))
  })
  return container.textContent
}
afterEach(() => unmountAll())

describe('the screen, on an unclassified estate', () => {
  it('says it is unclassified instead of charting zeros', async () => {
    const t = await mount(plain(12))
    expect(t).toContain(NO_CLASSIFICATION_TITLE)
    expect(t).toMatch(/does not yet derive a department or a sensitivity label/i)
  })

  it('renders NO risk-flag COUNT at all', async () => {
    // The claim is "no such number is stated", NOT "the phrase never appears". Those differ, and
    // the difference bit immediately: the replacement copy quotes "0 legal-hold" in order to deny
    // it, so a bare /legal-hold/ ban matched its own explanation. Eighth time that shape has failed
    // on correct output in this repo.
    //
    // So: assert on a tag rendered NEXT TO A NUMBER, which is what a count is, and on the chart's
    // own affordances being gone.
    const t = await mount(plain(12))
    for (const tag of CLASSIFICATION_TAGS) {
      const counted = new RegExp(`${tag.replace('-', '.')}\\s*\\d`, 'i')
      expect(t, `a ${tag} count was stated for an unclassified estate`).not.toMatch(counted)
    }
    expect(t).not.toMatch(/expand internal to see its risk flags/i)
    expect(t).not.toMatch(/top legal-exposure surface/i)
  })

  it('stops promising a grouping by department', async () => {
    const t = await mount(plain(12))
    expect(t).not.toMatch(/grouped by department/i)
  })

  it('stops claiming department is inferred from the file name', async () => {
    // Nothing does this for a real file. A help text explaining a mechanism that does not run sends
    // a reader looking for the naming convention that would make it work.
    const t = await mount(plain(12))
    expect(t).not.toMatch(/inferred from the file name/i)
    expect(t).toMatch(/Department and sensitivity are not\s*collected yet/i)
  })

  it('still lists the documents — this omits a CLAIM, not the estate', async () => {
    // The rows live inside collapsed department groups, so filenames are not in textContent until
    // one is expanded. What must be present is the estate itself: the count, the group, and the
    // type breakdown, none of which depends on classification.
    const t = await mount(plain(12))
    expect(t).toMatch(/12 documents discovered/i)
    expect(t).toMatch(/By document type/i)
    expect(t).toMatch(/Unassigned/i)          // the group is still there; only the CLAIM went
  })
})

describe('the screen, when classification IS present', () => {
  it('renders the exposure chart and the department grouping', async () => {
    // Guards every case above from passing on a component that simply deleted the surface.
    const t = await mount(classified())
    expect(t).toMatch(/expand internal to see its risk flags/i)
    expect(t).toMatch(/grouped by department/i)
    expect(t).not.toContain(NO_CLASSIFICATION_TITLE)
  })
})
