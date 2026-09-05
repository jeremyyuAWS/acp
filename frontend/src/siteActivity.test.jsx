// Per-SITE coverage for a multi-site SharePoint run.
//
// The backend can now walk thirty sites in one run, isolate a failure to the site that had it,
// and record per-site totals. None of that reaches an operator without a surface: the aggregate
// count ticks up and nothing says which site it is on, or that site 7 was never read. A grand
// total cannot answer it either — a site that held nothing and a site that was never opened
// contribute the same zero to it.
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: SiteActivity } = await import('./SiteActivity.jsx')

const HERE = dirname(fileURLToPath(import.meta.url))

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(SiteActivity, props)) })
  return container
}
afterEach(() => unmountAll())

const SITES = [
  { id: 'c,1,1', name: 'Finance', status: 'complete', listed: 412,
    libraries: [{ id: 'd1', name: 'Documents' }, { id: 'd2', name: 'Policies' }] },
  { id: 'c,2,2', name: 'HR', status: 'blocked', listed: 0, libraries: [],
    error: 'Sites.Read.All not granted — needs admin consent' },
  { id: 'c,3,3', name: 'Legal', status: 'skipped', listed: 0, libraries: [],
    error: 'over the 2-site limit for one scan' },
]

describe('SiteActivity', () => {
  it('renders nothing when the run has no sites', async () => {
    // OneDrive, a folder scan, Drive, a local corpus. Nothing to show is not loading and must
    // not look like it.
    expect((await mount({})).textContent).toBe('')
    expect((await mount({ sites: [] })).textContent).toBe('')
  })

  it('says how many sites of how many', async () => {
    // A count of finished sites with no denominator is the same missing-boundary failure the
    // scope sentence exists to stop.
    const c = await mount({ sites: SITES })
    expect(c.textContent).toMatch(/1 of 3 sites scanned/)
    expect(c.textContent).toMatch(/2 not read/)
  })

  it('names every selected site, including the ones it never read', async () => {
    // THE POINT. A site missing from this list is the silent omission the whole change is about.
    const c = await mount({ sites: SITES })
    for (const n of ['Finance', 'HR', 'Legal']) expect(c.textContent).toContain(n)
  })

  it('distinguishes could-not-read from not-scanned', async () => {
    // Different problems with different fixes: a permission, versus a second scan or a higher
    // limit. Collapsing them to "unavailable" sends an operator to the wrong one.
    const c = await mount({ sites: SITES })
    expect(c.textContent).toMatch(/Could not read/)
    expect(c.textContent).toMatch(/Not scanned/)
  })

  it('surfaces the failure reason verbatim', async () => {
    const c = await mount({ sites: SITES })
    expect(c.textContent).toMatch(/Sites\.Read\.All not granted/)
  })

  it('lists the libraries covered, so "every document library" is checkable', async () => {
    // A site with four libraries and one with none look identical from the site name alone.
    const c = await mount({ sites: SITES })
    expect(c.textContent).toMatch(/2 libraries: Documents, Policies/)
  })

  it('shows which libraries used Graph delta and the live change counts', async () => {
    const sites = [{ id: 'c,1,1', name: 'Finance', status: 'complete', listed: 12,
      libraries: [
        { id: 'd1', name: 'Documents', mode: 'delta', changed: 3, removed: 1 },
        { id: 'd2', name: 'Policies', mode: 'full' },
      ] }]
    const c = await mount({ sites })
    expect(c.textContent).toMatch(/Documents \(incremental · 3 changed · 1 removed\)/)
    expect(c.textContent).toMatch(/Policies \(full scan\)/)
  })

  it('shows per-library outcome, counts, throttling and failures', async () => {
    const sites = [{ id: 'c,1,1', name: 'Finance', status: 'partial', listed: 12,
      libraries: [
        { id: 'd1', name: 'Policies', mode: 'full', status: 'complete', listed: 12, estate: 14,
          throttled: 2 },
        { id: 'd2', name: 'Records', mode: 'full', status: 'blocked', listed: 0,
          error: 'Graph returned 403' },
      ] }]
    const c = await mount({ sites })
    expect(c.textContent).toMatch(/Policies \(full scan · complete · 12 documents\) · throttled 2 times/)
    expect(c.textContent).toMatch(/Records \(full scan · could not read · 0 documents\) · Graph returned 403/)
  })

  it('never shows the raw Graph site id as a label', async () => {
    // (host,guid,guid) is the least recognisable string in this product.
    const c = await mount({ sites: SITES })
    expect(c.textContent).not.toMatch(/c,1,1/)
    expect(c.querySelector('[title="c,1,1"]')).toBeTruthy()   // …available on hover, not as the name
  })

  it('states each status as TEXT, not colour or an icon alone', async () => {
    // The icon is aria-hidden; this is what a screen reader announces.
    const c = await mount({ sites: [{ id: 'a', name: 'A', status: 'complete', listed: 1 }] })
    expect(c.textContent).toMatch(/Scanned/)
    expect(c.textContent).toMatch(/1 document\b/)
  })

  it('shows a live pulse only for the site being scanned right now', async () => {
    const c = await mount({ sites: [{ id: 'a', name: 'A', status: 'scanning', listed: 0 }] })
    expect(c.querySelector('.pulsedot')).toBeTruthy()
    const done = await mount({ sites: [{ id: 'a', name: 'A', status: 'complete', listed: 1 }] })
    expect(done.querySelector('.pulsedot')).toBeNull()
  })

  it('names the library currently being read and how it is being enumerated', async () => {
    const c = await mount({ sites: [{ id: 'a', name: 'Clinical', status: 'scanning', listed: 200,
      active_library: { id: 'd1', name: 'Policies', mode: 'delta' } }] })
    expect(c.textContent).toMatch(/Reading Policies incrementally/)
  })
})

describe('Discover mounts it', () => {
  it('feeds it live rows during the run and the recorded rows after', () => {
    // The same shape from both sources on purpose: a separate "final report" shape would be a
    // second thing to keep true, and the one that drifted would be the one nobody was watching.
    const d = readFileSync(join(HERE, 'Discover.jsx'), 'utf8')
    expect(d).toContain("import SiteActivity from './SiteActivity.jsx'")
    // Live site rows only belong to the active displayed job. While Scan History shows an older
    // run, Discover nulls displayProgress and falls back to that run's recorded scope instead of
    // painting a newer job's SharePoint sites over it.
    expect(d).toMatch(/<SiteActivity sites=\{displayProgress\?\.sites \|\| scope\?\.sites\} \/>/)
  })
})
