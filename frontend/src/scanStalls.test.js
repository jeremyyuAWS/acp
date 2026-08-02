import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { trackStall, stallNote, STALL_AFTER_MS } from './App.jsx'

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'App.jsx'), 'utf8')

// A progress bar that cannot express "stalled" is the same defect as a null score rendering
// as "clean" (#101), an error path rendering 0/100 as complete (#86), and a Drive sweep
// failing silently (#99): the UI stating something it has no evidence for. On 2026-07-30 a
// worker restart left three scans frozen at "Analysing documents · 0/N" and the banner went
// on spinning and counting up "still working (Ns)" — which read as a broken product and got
// reported as one three times.

describe('trackStall — when the counter last moved', () => {
  it('starts the clock on first observation', () => {
    expect(trackStall(null, 0, 5, 1000)).toEqual({ done: 0, total: 5, since: 1000 })
  })

  it('holds the original timestamp while the counter sits still', () => {
    const a = trackStall(null, 2, 5, 1000)
    const b = trackStall(a, 2, 5, 60000)
    expect(b.since).toBe(1000)
    expect(b).toBe(a)                       // identity preserved — no churn per poll
  })

  it('resets the clock when the counter advances', () => {
    const a = trackStall(null, 2, 5, 1000)
    expect(trackStall(a, 3, 5, 60000).since).toBe(60000)
  })

  it('resets when the total appears — discovery landing IS progress', () => {
    // The reported symptom was "0 documents discovered": total goes 0 → N while done stays
    // 0. If only `done` were watched, the clock would keep running through a healthy
    // discovery and a large estate would trip the warning while working perfectly.
    const a = trackStall(null, 0, 0, 1000)
    expect(trackStall(a, 0, 400, 60000).since).toBe(60000)
  })
})

describe('stallNote — says so, or says nothing', () => {
  const at = (ms) => stallNote({ done: 0, total: 5, since: 0 }, ms)

  it('stays silent before the threshold', () => {
    expect(at(0)).toBeNull()
    expect(at(STALL_AFTER_MS - 1)).toBeNull()
  })

  it('names the time the scan went quiet once the threshold passes', () => {
    const note = at(STALL_AFTER_MS + 1)
    expect(note).toMatch(/no progress since \d{1,2}:\d{2}/)
    expect(note).toMatch(/worker may have restarted/)
  })

  it('hedges the cause and does not claim the scan is lost', () => {
    // The banner cannot distinguish a restart from a slow document, so it must not assert
    // either. It also must not tell the user to start over: the backend requeues the work.
    const note = at(STALL_AFTER_MS + 1)
    expect(note).toMatch(/may have/)
    expect(note).toMatch(/resume/)
    expect(note).not.toMatch(/failed|broken|lost|re-?run the scan/i)
  })

  it('is silent with no observation at all', () => {
    expect(stallNote(null, 999999)).toBeNull()
    expect(stallNote({ done: 0, total: 0, since: null }, 999999)).toBeNull()
  })

  it('waits long enough not to libel a slow document', () => {
    // A 300-page scanned PDF through OCR legitimately holds the counter for minutes.
    expect(STALL_AFTER_MS).toBeGreaterThanOrEqual(120000)
  })
})

describe('the banner stops asserting progress once stalled', () => {
  it('replaces the "still working" timer rather than sitting beside it', () => {
    // Elapsed time measures how long we have waited, never that anything is happening.
    // Printing both would leave the contradiction on screen.
    expect(src).toMatch(/if \(p\.stalled\) return `\$\{s\} · \$\{p\.stalled\}`/)
    expect(src.indexOf('if (p.stalled) return'))
      .toBeLessThan(src.indexOf('still working (${p.elapsed}s)'))
  })

  it('drops the spinner, which is the loudest false claim of motion', () => {
    expect(src).toMatch(/progress\.stalled \? <span aria-hidden="true"[^>]*>⚠<\/span> : <span className="spinner" \/>/)
  })

  it('carries the stall through the 0-documents-discovered path too', () => {
    // The state every one of the three reports was filed from.
    expect(src).toMatch(/return \{ phase: 'discovering', elapsed, stalled \}/)
  })

  it('tracks the stall on reconnect as well as on a fresh scan', () => {
    // A user who reloads mid-stall lands in reconnectScan; a banner that only warned on the
    // original poll loop would go back to spinning silently for them.
    expect(src.match(/stall = trackStall\(/g) || []).toHaveLength(2)
  })
})
