import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// A progress bar says how far along a run is. It cannot say WHICH documents are done, which is
// what someone watching a 258-document assessment actually wants to know — and the header above
// it was reporting "0 documents" for the whole run, because `docs` filters on a score the files
// do not have until they finish.
const here = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(here, f), 'utf8')
  .split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') && !t.startsWith('{/*') })
  .join('\n')

describe('the header counts documents that exist, not documents that finished', () => {
  const src = code('AssessRunner.jsx')

  it('prefers the run total over the scored-only list', () => {
    // `docs = files.filter(f => f.score != null)` is empty until the first file lands, so on a
    // deferred run the header read "Computing conformance · 0 documents" from start to finish.
    expect(src).toMatch(/\{\(liveTotal \|\| docs\.length\)\.toLocaleString\(\)\} documents/)
  })

  it('takes the total from the scan run, which knows it before any file is scored', () => {
    expect(src).toMatch(/const total = run\.files \|\| fs\.length \|\| 1/)
    expect(src).toMatch(/setLiveTotal\(total\)/)
  })
})

describe('per-document detail under the bar', () => {
  const src = code('AssessRunner.jsx')

  it('renders a row per document with its state', () => {
    expect(src).toMatch(/className="assesslist"/)
    expect(src).toMatch(/f\.done \? 'done' : 'pending'/)
  })

  it('shows the criteria a finished document FAILED, by number', () => {
    expect(src).toMatch(/r\.outcome === 'FAIL'/)
    expect(src).toMatch(/scs\.map\(\(c\) => <b key=\{c\}>\{c\}<\/b>\)/)
  })

  it('distinguishes "not fetched yet" from "nothing failed"', () => {
    // An empty array is a real answer. Rendering it as a spinner would leave a clean document
    // looking permanently unfinished.
    expect(src).toMatch(/scs === undefined/)
    expect(src).toMatch(/alclean/)
  })

  it('fetches criteria once per document, never per poll tick', () => {
    // Scan-wide traces are file x rule rows — 5,000+ on a 258-document estate, several times a
    // second. This asks per file, and the guard set means it never asks twice.
    expect(src).toMatch(/scsWanted\.current\.has\(f\.file\)/)
    expect(src).toMatch(/scsWanted\.current\.add\(f\.file\)/)
    expect(src).toMatch(/getScanTraces\(runId, f\.file\)/)
  })

  it('never lets the detail fetch break the assessment', () => {
    expect(src).toMatch(/\.catch\(\(\) => \{ \/\* best-effort detail/)
  })
})

describe('the client can ask for one file', () => {
  const api = code('api.js')

  it('passes the file through to the route that already supported it', () => {
    expect(api).toMatch(/export const getScanTraces = \(scanId, file = null\)/)
    expect(api).toMatch(/\$\{BASE\}\/scans\/\$\{encodeURIComponent\(scanId\)\}\/traces\$\{q\}/)
  })

  it('still works with no file, so existing callers are untouched', () => {
    expect(api).toMatch(/const q = file \? `\?file=\$\{encodeURIComponent\(file\)\}` : ''/)
  })
})

describe('the list cannot swamp the page', () => {
  const css = readFileSync(join(here, 'styles.css'), 'utf8')

  it('is height-capped and scrolls', () => {
    expect(css).toMatch(/\.assesslist \{[^}]*max-height: 420px[^}]*overflow-y: auto/s)
  })

  it('truncates a long filename rather than wrapping the row', () => {
    expect(css).toMatch(/\.alname \{[^}]*text-overflow: ellipsis/s)
  })
})
