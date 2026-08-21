import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
import { bucketLabel, exceptionType, httpStatus, buildUnreadableWhy } from './unreadableWhy.js'

// WHY the "could not be read" files could not be read — aggregated, on the screen that reports the
// count. The reason was recorded per file the whole time (`scan.file_error`) and reachable only one
// drawer at a time, while the breakdown that exists read a field the backend never sets and
// therefore said "no reason was recorded" over a fully recorded scan.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

const dec = (file, detail) => ({ action: 'scan.file_error', file, detail, ts: '2026-08-21T00:00:00Z' })
const bad = (file) => ({ file, name: file, status: 'error', score: null })
const good = (file) => ({ file, name: file, status: 'done', score: 90 })

describe('bucketing a recorded failure', () => {
  it('reads the exception type out of the logger’s own format', () => {
    expect(exceptionType('HttpError: <HttpError 404 when requesting …>')).toBe('HttpError')
    expect(exceptionType('ReadTimeout: timed out')).toBe('ReadTimeout')
    // Not an exception-shaped string — nothing is invented from it.
    expect(exceptionType('the file was locked')).toBe(null)
  })

  it('takes an HTTP status only where the message states one', () => {
    expect(httpStatus('HttpError: <HttpError 404 when requesting https://…>')).toBe(404)
    expect(httpStatus('ClientResponseError: server responded with 503')).toBe(503)
    // A digit run inside a NAME is not a status. Grouping "Q4-2026-404-report.pdf" under HTTP 404
    // would be a fabricated cause, which is the one failure mode this module exists to avoid.
    expect(httpStatus('OSError: cannot open Q4-404-report.pdf')).toBe(null)
    expect(httpStatus('ValueError: 200 pages')).toBe(null)
  })

  it('groups by type and status, NOT by the verbatim message', () => {
    // The whole point. The detail carries a URL or an item id, so grouping on it yields one bucket
    // per file — a list, not a breakdown.
    const a = bucketLabel('HttpError: <HttpError 404 when requesting https://graph…/items/AAA>')
    const b = bucketLabel('HttpError: <HttpError 404 when requesting https://graph…/items/BBB>')
    expect(a).toBe('HttpError · HTTP 404')
    expect(b).toBe(a)
  })

  it('keeps an unrecognised message verbatim rather than dropping it', () => {
    expect(bucketLabel('something nobody has seen before')).toBe('something nobody has seen before')
    expect(bucketLabel('')).toBe(null)
    expect(bucketLabel(null)).toBe(null)
  })
})

describe('reading the scan’s decision log', () => {
  const log = [
    dec('a.docx', 'HttpError: <HttpError 404 when requesting …/items/AAA>'),
    dec('b.docx', 'HttpError: <HttpError 404 when requesting …/items/BBB>'),
    dec('c.pdf', 'PackageNotFoundError: file is not a zip file'),
  ]

  it('labels each row from its own logged reason', () => {
    const { reasonOf } = buildUnreadableWhy(log)
    expect(reasonOf(bad('a.docx'))).toBe('HttpError · HTTP 404')
    expect(reasonOf(bad('c.pdf'))).toBe('PackageNotFoundError')
  })

  it('returns null for a file the log says nothing about — a gap stays a gap', () => {
    // Never "unreadable". A guess dressed as a finding is worse than an admitted hole, and this is
    // the exact sentence that once sent an investigation to inspect documents nothing had touched.
    const { reasonOf } = buildUnreadableWhy(log)
    expect(reasonOf(bad('d.xlsx'))).toBe(null)
  })

  it('prefers a reason carried on the row over the log', () => {
    const { reasonOf } = buildUnreadableWhy(log)
    expect(reasonOf({ file: 'a.docx', status: 'error', error_reason: 'OSError: disk gone' }))
      .toBe('OSError')
  })

  it('keeps the verbatim message reachable behind the label', () => {
    const { sampleOf } = buildUnreadableWhy(log, [bad('a.docx'), bad('c.pdf')])
    expect(sampleOf('HttpError · HTTP 404')).toContain('items/AAA')
    expect(sampleOf('nothing like this')).toBe(null)
  })

  it('populates the samples EAGERLY, so lookup order cannot matter', () => {
    // sampleOf must not silently return null until reasonOf has happened to run — that coupling
    // survives every test and fails once, in a component that reorders its own render.
    const { sampleOf } = buildUnreadableWhy(log, [bad('c.pdf')])
    expect(sampleOf('PackageNotFoundError')).toBe('PackageNotFoundError: file is not a zip file')
  })

  it('flags transport failures, and only those', () => {
    const { fetchLikely } = buildUnreadableWhy(log, [bad('a.docx'), bad('c.pdf')])
    expect(fetchLikely('HttpError · HTTP 404')).toBe(true)
    // A malformed package IS about the document. Marking it as a fetch failure would send the
    // reader to the source for a file the source handed over correctly.
    expect(fetchLikely('PackageNotFoundError')).toBe(false)
  })
})

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(DiscoveryResults, props)) })
  return container.textContent
}
afterEach(() => unmountAll())

describe('the breakdown on the screen', () => {
  // 18 of 22 unreadable — the shape that prompted this.
  const files = [
    ...Array.from({ length: 18 }, (_, i) => bad(`f${i}.docx`)),
    ...Array.from({ length: 4 }, (_, i) => good(`ok${i}.pdf`)),
  ]
  const log = files.filter((f) => f.status === 'error')
    .map((f) => dec(f.file, `HttpError: <HttpError 404 when requesting …/items/${f.file}>`))

  it('names the reason and its count instead of "no reason was recorded"', async () => {
    const why = buildUnreadableWhy(log, files)
    const t = await mount({ files, reasonOf: why.reasonOf, reasonSampleOf: why.sampleOf,
                            reasonFetchLikely: why.fetchLikely })
    expect(t).toContain('COULD NOT BE READ')
    expect(t).toContain('HttpError · HTTP 404')
    expect(t).not.toContain('No reason was recorded')
  })

  it('says which END of the failure the message is about', async () => {
    const why = buildUnreadableWhy(log, files)
    const t = await mount({ files, reasonOf: why.reasonOf, reasonSampleOf: why.sampleOf,
                            reasonFetchLikely: why.fetchLikely })
    expect(t).toMatch(/18 of 18 failed with a transport or HTTP error/)
    expect(t).toMatch(/may never have been fetched/)
  })

  it('adds NO such clause when the failures are about the documents', async () => {
    // Guards the case above from passing on a component that warns unconditionally.
    const docLog = files.filter((f) => f.status === 'error')
      .map((f) => dec(f.file, 'PackageNotFoundError: file is not a zip file'))
    const why = buildUnreadableWhy(docLog, files)
    const t = await mount({ files, reasonOf: why.reasonOf, reasonSampleOf: why.sampleOf,
                            reasonFetchLikely: why.fetchLikely })
    expect(t).toContain('PackageNotFoundError')
    expect(t).not.toMatch(/may never have been fetched/)
  })

  it('still says "not recorded" when the log is empty — the gap is not papered over', async () => {
    const why = buildUnreadableWhy([], files)
    const t = await mount({ files, reasonOf: why.reasonOf, reasonSampleOf: why.sampleOf,
                            reasonFetchLikely: why.fetchLikely })
    expect(t).toContain('No reason was recorded')
    expect(t).not.toMatch(/may never have been fetched/)
  })

  it('renders unchanged when no reason source is wired at all', async () => {
    const t = await mount({ files })
    expect(t).toContain('COULD NOT BE READ')
    expect(t).toContain('No reason was recorded')
  })
})

describe('Discover supplies it from the scan’s own log', () => {
  it('reads the decision log and hands the result to DiscoveryResults', () => {
    // The defect this fixes is a WIRING one: unreadableReasons was already there, already correct,
    // and fed by `defaultReasonOf`, which reads row fields (`openIssue` / `error_reason` /
    // `errorReason`) that no backend response carries. An unwired reason source renders as a
    // recorded gap, which is indistinguishable from a real one.
    const d = read('Discover.jsx')
    expect(d).toMatch(/import \{ buildUnreadableWhy \} from '\.\/unreadableWhy\.js'/)
    expect(d).toMatch(/listScanDecisions\(scanId\)/)
    expect(d).toMatch(/<DiscoveryResults[\s\S]{0,600}?reasonOf=\{why \? why\.reasonOf : undefined\}/)
  })
})
