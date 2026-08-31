import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// The "N documents discovered" headline read files.length — file_records (App.jsx's scan?.files),
// which ADR 0020 leaves empty until Assess actually opens each document. That is NOT what Discover
// found: before Assess ever runs, or partway through it, the headline read 0 or a partial count
// while the very same screen's own breakdown (sourced from scope.inventory, the discovery-time
// snapshot) correctly stated the real estate size.
//
// Found live 2026-08-22: a fresh Discover-only scan of a real 170-file estate showed "0 documents
// discovered" here. Running Assess against it and stopping partway through made the number climb
// to 46 — file_records filling in as Assess processed files — while Discover's own "170 files
// discovered" breakdown a few lines down never moved, because it reads scope.inventory instead.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container.textContent
}
afterEach(() => unmountAll())

describe('the "N documents discovered" headline', () => {
  it('reads scope.inventory.discovered, not the empty file_records array, before Assess has run', async () => {
    const t = await mount({ files: [], scope: { kind: 'drive', inventory: { discovered: 170 } } })
    expect(t).toMatch(/170 documents discovered/i)
    // \b0\b, not /0 documents discovered/ bare — "17**0** documents discovered" contains that
    // exact substring since 170 ends in the digit 0, which made this assertion pass even when the
    // bug it exists to catch was still live.
    expect(t).not.toMatch(/\b0\b documents discovered/i)
  })

  it('keeps reading scope.inventory.discovered while file_records is only partially filled in', async () => {
    // The exact shape of a stopped-partway-through Assess run: file_records has SOME rows, but
    // fewer than the real estate — the headline must not report the partial count as the total.
    const partial = Array.from({ length: 46 }, (_, i) => ({ file: `f${i}.docx`, status: 'done' }))
    const t = await mount({ files: partial, scope: { kind: 'drive', inventory: { discovered: 170 } } })
    expect(t).toMatch(/170 documents discovered/i)
    expect(t).not.toMatch(/46 documents discovered/i)
  })

  it('falls back to files.length when scope carries no inventory — a scan predating it, or none at all', async () => {
    const files = Array.from({ length: 12 }, (_, i) => ({ file: `f${i}.docx`, status: 'done' }))
    const t = await mount({ files, scope: null })
    expect(t).toMatch(/12 documents discovered/i)
  })
})

// The completion card ("N files inventoried") reads a SEPARATE, self-healing count from the live
// banner above — root cause fixed backend-side 2026-08-28 (api/handlers.py's _scan_discover used
// to flip scan_runs.status to 'discovered' before scope.inventory was actually persisted, so a
// reader in that race window could see status='discovered' with scope.inventory.discovered still
// 0). That closes the window for every NEW scan, but a scan that already reached 'discovered' with
// the bad snapshot BEFORE the fix deployed keeps reading it forever — a page refresh re-reads the
// same wrong persisted value from Postgres, it does not repair it. Once a scan is genuinely
// complete (!busy, status='discovered'), file_records has been backfilled from scan_inventory
// (ADR 0020's get_scan fallback — see store.py), so files.length is real ground truth there,
// unlike on the live banner above where file_records is still empty pre-Assess.
describe('the completion card ("N files inventoried") self-heals a stale zero', () => {
  const doneRun = (extra = {}) => ({ id: 's1', status: 'discovered', discovered_at: '2026-08-28T04:00:00Z', ...extra })

  it('shows the real inventory count when scope.inventory.discovered is a stale/wrong 0', async () => {
    const files = Array.from({ length: 6922 }, (_, i) => ({ file: `f${i}.docx`, status: 'discovered' }))
    const c = await mount({
      files, scope: { kind: 'drive', inventory: { discovered: 0 } }, run: doneRun(),
    })
    expect(c).toMatch(/6,922 files inventoried/)
  })

  it('does not touch a genuinely correct non-zero discoveredCount', async () => {
    const files = Array.from({ length: 170 }, (_, i) => ({ file: `f${i}.docx`, status: 'discovered' }))
    const c = await mount({
      files, scope: { kind: 'drive', inventory: { discovered: 170 } }, run: doneRun(),
    })
    expect(c).toMatch(/170 files inventoried/)
  })

  it('still shows 0 for a genuinely empty estate — not a false positive', async () => {
    const c = await mount({
      files: [], scope: { kind: 'drive', inventory: { discovered: 0 } }, run: doneRun(),
    })
    expect(c).toMatch(/0 files inventoried/)
  })

  it('does not affect the live "N documents discovered" banner while the scan is still running', async () => {
    // Same stale-zero shape, but busy=true (or not yet 'discovered') — the completion card must
    // not render at all here, so this can only be the live banner, which correctly keeps
    // preferring scope.inventory.discovered per its own (untouched) fallback rule above.
    const files = Array.from({ length: 6922 }, (_, i) => ({ file: `f${i}.docx`, status: 'discovered' }))
    const t = await mount({
      files, scope: { kind: 'drive', inventory: { discovered: 0 } }, busy: true, run: { id: 's1', status: 'running' },
    })
    expect(t).toMatch(/0 documents discovered/i)
    expect(t).not.toMatch(/files inventoried/)
  })
})

// A scan that has been created but not yet claimed by a worker (progress.phase === 'queued')
// looked identical to a genuine empty result: DiscoverRunProgress already shows its own
// "Discovery queued" card, but the bold "0 documents discovered" line directly below it repeated
// the zero as if it were a finding, with only a small italic "provisional" caveat easy to miss —
// reported live 2026-08-28 against a freshly-queued scan (raw scan data: status: 'queued', scope:
// null, decisions: []).
describe('the live banner while a scan is queued (not yet claimed by a worker)', () => {
  it('is suppressed in favor of the "Discovery queued" card, not shown as "0 documents discovered"', async () => {
    const t = await mount({
      files: [], scope: null, busy: true, run: { id: 's1', status: 'queued' },
      progress: { phase: 'queued', started_at: '2026-08-28T17:00:00Z' },
    })
    expect(t).toMatch(/Discovery\s*Queued/)
    expect(t).not.toMatch(/documents discovered/i)
  })

  it('reappears once the scan moves past queued into an active phase', async () => {
    const t = await mount({
      files: [], scope: null, busy: true, run: { id: 's1', status: 'running' },
      progress: { phase: 'discovering', started_at: '2026-08-28T17:00:00Z' },
    })
    expect(t).toMatch(/0 documents discovered/i)
  })
})

// Same shape, different path: found live 2026-08-28, scan 90203ef148e3. Here `progress` is null
// (this tab is not tracking the scan — busy is false) but the DISPLAYED run's own status is
// 'queued'. The queued-progress-card guard above never fires (no progress object at all), so
// without this the bold zero line rendered alone, with no "Discovery queued" card and no caveat —
// read as a completed, genuinely empty scan. The informational banner from discoverFailedRun.test
// covers the explanation; this confirms the zero-count line itself is also suppressed.
describe('the live banner for a queued run this tab is not tracking (busy false)', () => {
  it('is suppressed when run.status is "queued" even with no progress object at all', async () => {
    const t = await mount({ files: [], scope: null, busy: false, run: { id: 's7', status: 'queued' } })
    expect(t).not.toMatch(/documents discovered/i)
  })
})

// The completion card's "Assessable" tile used to read scope.inventory.by_status.assessable
// directly, on its own — skipping estateFunnel.js's `assessmentEligible()`, which prefers the
// newer, direct `assessment_eligible` field and treats `by_status.assessable` as the older
// fallback shape only. DiscoveryResults' own headline "Assessable" stat tile (a few hundred
// pixels below this card, same screen, same scan) already calls `assessmentEligible()` — so a
// scan whose two fields disagreed would show two different "assessable" counts on one screen,
// the exact "four-denominator" defect estateFunnel.js's own header comment warns against.
describe('the completion card\'s "Assessable" count agrees with DiscoveryResults\' below it', () => {
  const doneRun = (extra = {}) => ({ id: 's9', status: 'discovered', discovered_at: '2026-08-29T04:00:00Z', ...extra })

  it('prefers assessment_eligible over a stale by_status.assessable', async () => {
    const files = Array.from({ length: 200 }, (_, i) => ({ file: `f${i}.pdf`, status: 'discovered' }))
    const c = await mount({
      files, run: doneRun(),
      scope: {
        kind: 'drive',
        inventory: { discovered: 200, assessment_eligible: 170, by_status: { assessable: 40 } },
      },
    })
    expect(c).toMatch(/\b170\b/)
    expect(c).not.toMatch(/\b40\b assessable/i)
  })

  it('falls back to by_status.assessable when assessment_eligible is absent', async () => {
    const files = Array.from({ length: 200 }, (_, i) => ({ file: `f${i}.pdf`, status: 'discovered' }))
    const c = await mount({
      files, run: doneRun(),
      scope: { kind: 'drive', inventory: { discovered: 200, by_status: { assessable: 170 } } },
    })
    expect(c).toMatch(/\b170\b/)
  })
})

// The completion card's "N of M are scannable document types" line reads run.files —
// scan_runs.files, a scalar column set from scanner.py's _list() return value (already
// filtered to scannable MIME types) — NOT scan?.files/file_records, a same-named but
// differently-shaped field passed as the `files` prop. Found live 2026-08-29: a real Drive
// scan showed "1,033 documents" in the top nav bar and "6,922 files inventoried" in this
// exact card, same scan — traced to run.files (scannable-only) vs scope.inventory.discovered
// (whole estate), two legitimately different, unlabelled numbers read as a contradiction.
describe('the completion card\'s scannable-document count reads run.files', () => {
  const doneRun = (extra = {}) => ({ id: 's10', status: 'discovered', discovered_at: '2026-08-29T04:00:00Z', ...extra })

  it('threads run.files through as the scannable count, separate from the discovered total', async () => {
    const files = Array.from({ length: 200 }, (_, i) => ({ file: `f${i}.pdf`, status: 'discovered' }))
    const c = await mount({
      files, run: doneRun({ files: 173 }),
      scope: { kind: 'drive', inventory: { discovered: 6922, assessment_eligible: 173 } },
    })
    expect(c).toMatch(/173 of 6,922/)
  })

  it('omits the line when run.files is absent — a scan predating the column, not a fabricated 0', async () => {
    const files = Array.from({ length: 200 }, (_, i) => ({ file: `f${i}.pdf`, status: 'discovered' }))
    const c = await mount({
      files, run: doneRun({ files: null }),
      scope: { kind: 'drive', inventory: { discovered: 200 } },
    })
    expect(c).not.toMatch(/scannable document type/)
  })
})
