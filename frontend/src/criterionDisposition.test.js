// Structural tests for the W4 criterion disposition persistence backend and frontend wiring.
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, it, expect } from 'vitest'

const ROOT = resolve(__dirname, '../..')

function read(rel) {
  return readFileSync(resolve(ROOT, rel), 'utf8')
}

// ── Store ────────────────────────────────────────────────────────────────────

describe('store.py — criterion_disposition table', () => {
  const store = read('api/store.py')

  it('defines criterion_disposition table', () => {
    expect(store).toContain('CREATE TABLE IF NOT EXISTS criterion_disposition')
  })

  it('table has required columns', () => {
    const idx = store.indexOf('CREATE TABLE IF NOT EXISTS criterion_disposition')
    const block = store.slice(idx, idx + 500)
    expect(block).toContain('scan_id TEXT NOT NULL')
    expect(block).toContain('file TEXT NOT NULL')
    expect(block).toContain('sc TEXT NOT NULL')
    expect(block).toContain('kind TEXT NOT NULL')
    expect(block).toContain('reason TEXT NOT NULL')
    expect(block).toContain('actor TEXT')
    expect(block).toContain('owner_email TEXT')
  })

  it('has index on (scan_id, file)', () => {
    expect(store).toContain('idx_criterion_disposition_file')
    expect(store).toContain('ON criterion_disposition(scan_id, file)')
  })

  it('has index on (scan_id, file, sc)', () => {
    expect(store).toContain('idx_criterion_disposition_sc')
    expect(store).toContain('ON criterion_disposition(scan_id, file, sc)')
  })

  it('defines record_criterion_disposition method', () => {
    expect(store).toContain('def record_criterion_disposition(')
  })

  it('record_criterion_disposition validates kind against closed set', () => {
    expect(store).toContain('_DISPOSITION_KINDS')
    expect(store).toContain("frozenset({\"attested\", \"out_of_scope\"})")
  })

  it('record_criterion_disposition inserts row', () => {
    const idx = store.indexOf('def record_criterion_disposition(')
    // window wide enough to include the INSERT (past signature + docstring + validation)
    const body = store.slice(idx, idx + 900)
    expect(body).toContain('INSERT INTO criterion_disposition')
  })

  it('defines list_criterion_dispositions method', () => {
    expect(store).toContain('def list_criterion_dispositions(')
  })

  it('list_criterion_dispositions is owner-scoped', () => {
    const idx = store.indexOf('def list_criterion_dispositions(')
    const body = store.slice(idx, idx + 700)
    expect(body).toContain('owner_email')
  })

  it('list_criterion_dispositions orders most-recent-first', () => {
    const idx = store.indexOf('def list_criterion_dispositions(')
    const body = store.slice(idx, idx + 700)
    expect(body).toContain('ORDER BY ts DESC')
  })

  // Pinned as a FLOOR, not an equality. This assertion has already drifted once — its title
  // still says 14 while it asserted 15 — because every unrelated migration since has had to come
  // back and edit this line. An exact pin here tests nothing about criterion_disposition; it
  // tests that nobody has added a table anywhere else in the file. What this feature actually
  // needs is that its DDL shipped inside a migrated schema, which the CREATE/index assertions
  // above cover, plus a version at or past the one it landed in.
  it('shipped in a migrated schema at or past v15', () => {
    const m = store.match(/_SCHEMA_VERSION = (\d+)/)
    expect(m, '_SCHEMA_VERSION not found in api/store.py').toBeTruthy()
    expect(Number(m[1])).toBeGreaterThanOrEqual(15)
  })
})

// ── Routes ───────────────────────────────────────────────────────────────────

describe('scans.py — dispose and dispositions routes', () => {
  const scans = read('api/routes/scans.py')

  it('POST /dispose route exists', () => {
    expect(scans).toContain('"/scans/{scan_id}/files/{filename:path}/dispose"')
  })

  it('GET /dispositions route exists', () => {
    expect(scans).toContain('"/scans/{scan_id}/files/{filename:path}/dispositions"')
  })

  it('dispose route validates sc', () => {
    const idx = scans.indexOf('async def dispose_criterion(')
    const body = scans.slice(idx, idx + 1200)
    expect(body).toContain('"sc is required"')
  })

  it('dispose route validates kind against closed set', () => {
    const idx = scans.indexOf('async def dispose_criterion(')
    const body = scans.slice(idx, idx + 1200)
    expect(body).toContain('_DISPOSITION_KINDS')
  })

  it('dispose route validates reason', () => {
    const idx = scans.indexOf('async def dispose_criterion(')
    const body = scans.slice(idx, idx + 1400)
    expect(body).toContain('"reason is required"')
  })

  it('dispose route calls log_decision', () => {
    const idx = scans.indexOf('async def dispose_criterion(')
    const body = scans.slice(idx, idx + 1500)
    expect(body).toContain('log_decision')
    expect(body).toContain('"criterion.disposed"')
  })

  it('dispose route is owner-scoped', () => {
    const idx = scans.indexOf('async def dispose_criterion(')
    const body = scans.slice(idx, idx + 900)
    expect(body).toContain('_owner(request)')
    expect(body).toContain('get_scan(scan_id, owner=owner)')
  })

  it('dispositions route is owner-scoped', () => {
    const idx = scans.indexOf('def list_file_dispositions(')
    const body = scans.slice(idx, idx + 500)
    expect(body).toContain('_owner(request)')
    expect(body).toContain('owner=owner')
  })
})

// ── Capability map ────────────────────────────────────────────────────────────

describe('workspace_capability_map.py — disposition routes registered', () => {
  const cap = read('api/workspace_capability_map.py')

  it('GET /dispositions is in capability map', () => {
    expect(cap).toContain('"/scans/{scan_id}/files/{filename:path}/dispositions"')
  })

  it('POST /dispose is in capability map with assess.run', () => {
    expect(cap).toContain('"/scans/{scan_id}/files/{filename:path}/dispose"')
    // assert it's associated with assess.run
    const idx = cap.indexOf('"/scans/{scan_id}/files/{filename:path}/dispose"')
    const ctx = cap.slice(Math.max(0, idx - 50), idx + 200)
    expect(ctx).toContain('assess.run')
  })
})

// ── Frontend api.js ───────────────────────────────────────────────────────────

describe('api.js — disposeCriterion and listDispositions exports', () => {
  const api = read('frontend/src/api.js')

  it('exports disposeCriterion', () => {
    expect(api).toContain('export const disposeCriterion')
  })

  it('exports listDispositions', () => {
    expect(api).toContain('export const listDispositions')
  })

  it('disposeCriterion POSTs to /dispose endpoint', () => {
    const idx = api.indexOf('export const disposeCriterion')
    const body = api.slice(idx, idx + 400)
    expect(body).toContain('/dispose')
  })

  it('disposeCriterion sends sc, kind, reason in body', () => {
    const idx = api.indexOf('export const disposeCriterion')
    const body = api.slice(idx, idx + 500)
    expect(body).toContain('sc')
    expect(body).toContain('kind')
    expect(body).toContain('reason')
  })

  it('listDispositions GETs /dispositions endpoint', () => {
    const idx = api.indexOf('export const listDispositions')
    const body = api.slice(idx, idx + 300)
    expect(body).toContain('/dispositions')
  })
})

// ── FileDrawer.jsx — live integration ────────────────────────────────────────

describe('FileDrawer.jsx — disposition persistence wired', () => {
  const drawer = read('frontend/src/FileDrawer.jsx')

  it('imports listDispositions from api.js', () => {
    expect(drawer).toContain('listDispositions')
  })

  it('imports disposeCriterion from api.js', () => {
    expect(drawer).toContain('disposeCriterion')
  })
})
