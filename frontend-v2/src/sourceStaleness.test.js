import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Source-level wiring for the Release Center's source-staleness surface (Phase 3, PR3). The
// classification is proven server-side; this pins that the UI fetches it, warns honestly, and
// only ever offers a re-scan for files it actually found changed.
const HERE = dirname(fileURLToPath(import.meta.url))
const pub = () => readFileSync(join(HERE, 'Publish.jsx'), 'utf8')
const api = () => readFileSync(join(HERE, 'api.js'), 'utf8')
const mon = () => readFileSync(join(HERE, 'Monitor.jsx'), 'utf8')

describe('api: getSourceStatus', () => {
  it('GETs the source-status endpoint (headers() attaches the Drive token)', () => {
    const s = api()
    expect(s).toMatch(/export const getSourceStatus = \(scanId\) =>/)
    expect(s).toMatch(/\/scans\/\$\{scanId\}\/source-status`, \{ headers: headers\(\) \}/)
  })
})

describe('Release Center: source-staleness UI', () => {
  it('fetches source-status for the scan and derives the stale set', () => {
    const s = pub()
    expect(s).toMatch(/import \{[^}]*getSourceStatus[^}]*rescoreFile[^}]*\} from '\.\/api\.js'/)
    expect(s).toMatch(/getSourceStatus\(run\.id\)/)
    expect(s).toMatch(/const srcOf = \(f\) => srcStatus\.byFile\[f\.file\]\?\.state/)
    expect(s).toMatch(/const staleReady = ready\.filter\(\(f\) => !done\[f\.file\] && srcOf\(f\) === 'stale'\)/)
  })

  it('warns only when a source actually changed, and offers a scoped re-scan', () => {
    const s = pub()
    expect(s).toMatch(/\{staleReady\.length > 0 && \(/)
    expect(s).toMatch(/changed at the source in Drive since this scan/)
    expect(s).toMatch(/Re-scan changed sources \(\$\{staleReady\.length\}\)/)
  })

  it('re-scan loops rescoreFile over ONLY the stale files, then re-checks', () => {
    const s = pub()
    expect(s).toMatch(/const targets = staleReady\.map\(\(f\) => f\.file\)/)
    expect(s).toMatch(/Promise\.allSettled\(targets\.map\(\(f\) => rescoreFile\(run\?\.id, f\)\)\)/)
    expect(s).toMatch(/loadSourceStatus\(\)/)
  })

  it('per-row badges are honest: stale is flagged, unreachable is muted, nothing else claims “unchanged”', () => {
    const s = pub()
    // Both branches are gated on the server-derived state; the visible text is honest.
    expect(s).toMatch(/srcOf\(f\) === 'stale' &&/)
    expect(s).toMatch(/⚠ source changed/)
    expect(s).toMatch(/srcOf\(f\) === 'unavailable' &&/)
    expect(s).toMatch(/source unreachable/)
    // No blanket "source unchanged" / "up to date" claim rendered per row.
    expect(s).not.toMatch(/source unchanged/)
    expect(s).not.toMatch(/source up to date/)
  })
})

// R5 — the same real drift signal, now surfaced on the Monitor tab (Continuous Monitoring), which
// previously ran on illustrative demo data (sourceWatch from sim.js).
describe('Monitor: real source-drift panel (R5)', () => {
  it('imports getSourceStatus and fetches it for the real run', () => {
    const s = mon()
    expect(s).toMatch(/import \{[^}]*getSourceStatus[^}]*\} from '\.\/api\.js'/)
    expect(s).toMatch(/getSourceStatus\(run\.id\)/)
  })

  it('derives the stale set from the SERVER state and never invents drift', () => {
    const s = mon()
    expect(s).toMatch(/\.filter\(\(r\) => r\.state === 'stale'\)/)
    expect(s).toMatch(/stale: s\?\.stale_count \|\| 0/)
    // the error path leaves the panel empty rather than fabricating changes
    expect(s).toMatch(/\.catch\(\(\) => \{ if \(live\) setDrift\(\{ loaded: true, stale: 0/)
  })

  it('is a REAL panel (LIVE), gated to a real run — not the illustrative demo surface', () => {
    const s = mon()
    expect(s).toMatch(/\{!SIM && run\?\.id && \(/)
    expect(s).toMatch(/className="panel mon-drift"/)
    expect(s).toMatch(/No source changes since the last scan/)
    // the drift panel must NOT be fed by the sim sourceWatch
    expect(s).not.toMatch(/sourceWatch[^)]*drift/)
  })
})
