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
    expect(s).toMatch(/srcOf\(f\) === 'stale' &&[\s\S]{0,120}⚠ source changed/)
    expect(s).toMatch(/srcOf\(f\) === 'unavailable' &&[\s\S]{0,120}source unreachable/)
    // No blanket "source unchanged" / "up to date" claim rendered per row.
    expect(s).not.toMatch(/source unchanged/)
    expect(s).not.toMatch(/source up to date/)
  })
})
