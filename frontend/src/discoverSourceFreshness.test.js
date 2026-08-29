import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { sourceFreshnessBadge } from './Discover.jsx'

// PRD Phase 3 (freshness/sync states): Discover surfaces the SAME /source-status the Release
// Center and Monitor already use (see sourceStaleness.test.js), the one place the PRD's own
// inventory spec actually asks for it. This pins that Discover fetches it, and that the badge
// text is honest about WHICH kind of 'unavailable' a file is in — data the endpoint has always
// returned (source_staleness.py's `error` field) but no surface read until now.
const HERE = dirname(fileURLToPath(import.meta.url))
const disc = () => readFileSync(join(HERE, 'Discover.jsx'), 'utf8')

describe('Discover: source-freshness badge', () => {
  it('imports getSourceStatus and fetches it for the scan, best-effort', () => {
    const s = disc()
    expect(s).toMatch(/import \{[^}]*getSourceStatus[^}]*\} from '\.\/api\.js'/)
    expect(s).toMatch(/getSourceStatus\(scanId\)/)
    // a failure clears the map rather than leaving stale badges or throwing
    expect(s).toMatch(/\.catch\(\(\) => \{ if \(live\) setSrcStatus\(\{\}\) \}\)/)
  })

  it('renders nothing for unchanged/untracked — no per-row "up to date" claim', () => {
    const s = disc()
    expect(s).not.toMatch(/source unchanged/)
    expect(s).not.toMatch(/up to date/)
  })

  it('flags a changed source the same way the Release Center already does', () => {
    const s = disc()
    expect(s).toMatch(/row\.state === 'stale'/)
    expect(s).toMatch(/⚠ source changed/)
  })

  it('tells deleted-at-source apart from a lost authorization, not one generic "unreachable"', () => {
    const s = disc()
    expect(s).toMatch(/row\.error === 'not_found'/)
    expect(s).toMatch(/deleted at source/)
    expect(s).toMatch(/row\.error === 'forbidden'/)
    expect(s).toMatch(/authorization required/)
    // the generic fallback is still there for drive_error / unparseable / a missing error code
    expect(s).toMatch(/source unreachable/)
  })

  it('a locked (unopenable) file never also gets a freshness badge', () => {
    const s = disc()
    expect(s).toMatch(/const fresh = f\.locked \? null : sourceFreshnessBadge\(srcStatus\[f\.file\]\)/)
  })
})

describe('sourceFreshnessBadge (pure label function)', () => {
  it('returns null for no row, unchanged, and untracked — no badge is the correct answer', () => {
    expect(sourceFreshnessBadge(undefined)).toBeNull()
    expect(sourceFreshnessBadge(null)).toBeNull()
    expect(sourceFreshnessBadge({ state: 'unchanged' })).toBeNull()
    expect(sourceFreshnessBadge({ state: 'untracked' })).toBeNull()
  })

  it('flags a stale source', () => {
    const b = sourceFreshnessBadge({ state: 'stale' })
    expect(b.label).toBe('⚠ source changed')
  })

  it('tells apart deleted / forbidden / generic unavailable', () => {
    expect(sourceFreshnessBadge({ state: 'unavailable', error: 'not_found' }).label)
      .toBe('deleted at source')
    expect(sourceFreshnessBadge({ state: 'unavailable', error: 'forbidden' }).label)
      .toBe('authorization required')
    expect(sourceFreshnessBadge({ state: 'unavailable', error: 'drive_error' }).label)
      .toBe('source unreachable')
    expect(sourceFreshnessBadge({ state: 'unavailable', error: 'unparseable' }).label)
      .toBe('source unreachable')
    expect(sourceFreshnessBadge({ state: 'unavailable' }).label)   // no error code at all
      .toBe('source unreachable')
  })

  // PRD Phase 3's fuller vocabulary — ACP's own import/publish state, layered by the backend
  // (source_staleness.classify_sync_state) on top of the four states above.
  it('flags a file still being imported', () => {
    expect(sourceFreshnessBadge({ state: 'importing' }).label).toBe('importing…')
  })

  it('flags a failed import', () => {
    expect(sourceFreshnessBadge({ state: 'import_failed' }).label).toBe('import failed')
  })

  it('flags publish pending — a fix exists and has not been published yet', () => {
    expect(sourceFreshnessBadge({ state: 'publish_pending' }).label).toBe('publish pending')
  })

  it('flags a conflict — the source changed and ACP holds an unpublished fix', () => {
    expect(sourceFreshnessBadge({ state: 'conflict' }).label).toBe('⚠ conflict')
  })

  it("flags ACP's version as newer than the live source", () => {
    expect(sourceFreshnessBadge({ state: 'acp_newer' }).label).toBe('ACP version newer')
  })
})
