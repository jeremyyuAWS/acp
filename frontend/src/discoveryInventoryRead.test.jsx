/**
 * Discover reads the lifecycle columns from `GET /scans/{id}/inventory` — and a read that did not
 * complete renders NOTHING.
 *
 * This is the file for the failure path, which is the one most likely to regress into a
 * reassuring zero. A 403, a dropped connection and an estate with no tagged files are three
 * different facts; only one of them is "no file needs your decision", and it is the only one
 * allowed to say so. So the assertions here are mostly about what is ABSENT.
 *
 * `api.js` is partially mocked — `importOriginal` keeps every other export real, so DispositionRules
 * and the rest of Discover's module graph behave exactly as they do in the suite's other Discover
 * mounts, and only the one route under test is controlled.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const h = vi.hoisted(() => ({ mode: 'ok', rows: [], calls: [] }))

vi.mock('./api.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getScanInventory: (scanId, { offset = 0, limit = 1000 } = {}) => {
      h.calls.push({ scanId, offset, limit })
      if (h.mode === 'reject') return Promise.reject(new Error('HTTP 403 — forbidden'))
      // Still in flight: a promise that never settles, so the mount renders the loading state.
      if (h.mode === 'pending') return new Promise(() => {})
      // The truncated read: the route reports more rows than it hands back.
      if (h.mode === 'short') return Promise.resolve({ scan_id: scanId, total: 5000, offset, limit, rows: [] })
      return Promise.resolve({ scan_id: scanId, total: h.rows.length, offset, limit,
                               rows: h.rows.slice(offset, offset + limit) })
    },
  }
})

const { default: Discover } = await import('./Discover.jsx')

let container, root
beforeEach(() => {
  ;({ container, root } = createTestRoot())
  h.mode = 'ok'
  h.calls = []
  h.rows = [
    { file: 'Clinical/old-pathway.docx', path: 'Clinical/old-pathway.docx',
      lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      lifecycle_reason: "matched archive rule 'Legacy clinical policies'" },
    { file: 'Clinical/live.docx', path: 'Clinical/live.docx', lifecycle_status: 'Active' },
  ]
})
afterEach(unmountAll)

const FILES = [
  { file: 'Clinical/old-pathway.docx', type: 'DOCX', tags: [], issues: [], department: 'Clinical', sourceName: 'SharePoint' },
  { file: 'Clinical/live.docx', type: 'DOCX', tags: [], issues: [], department: 'Clinical', sourceName: 'SharePoint' },
]

const render = async (props = {}) => {
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'SharePoint' }], files: FILES, busy: false, onScan: () => {},
      onAdvance: () => {}, scanId: 'scan-1', ...props,
    }))
  })
  // let the inventory read settle
  for (let k = 0; k < 6; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return container
}
const text = () => container.textContent

describe('a completed read fills the recommendation surface', () => {
  it('calls the inventory route for the scan on screen', async () => {
    await render()
    expect(h.calls[0]).toMatchObject({ scanId: 'scan-1', offset: 0 })
  })

  it('feeds the completed read into the export panel too, not just the recommendation surface', async () => {
    // DiscoverInventoryExport was wired with `inventory={scope.inventory}` alone — the SUMMARY
    // object (by_format/by_status/samples), which has no `.rows` array — so its own
    // `rows || inventory.rows` fallback always landed on `null` and it read "The inventory could
    // not be read" on every run, including a completed read like this one. Regression guard: a
    // successful read must reach BOTH consumers of `inv`, not just DiscoveryResults.
    await render({ run: { id: 'scan-1', discovered_at: '2026-08-26T14:00:00Z' } })
    expect(text()).not.toContain('The inventory could not be read')
    expect(text()).toContain('Inventory taken')
  })

  // THE RECOMMENDATION SURFACE IS GONE FROM DISCOVER. The RECOMMENDATIONS table, the
  // per-file lifecycle tag/rule/reason, the EVERY DISCOVERED FILE partition and the "I approve"
  // acknowledgement bar were all removed on 2026-09-02 (PRD "ACP Discover and Overview
  // Simplification"). The READ is unchanged and still has to succeed — the inventory snapshot and
  // the counts below it depend on it — so what these cases pin now is that a completed read still
  // reaches the screen, and that none of it is re-stated as a lifecycle claim.
  it('does not restate the read as a lifecycle recommendation', async () => {
    await render()
    // The read completed and reached the screen…
    expect(text()).toContain('DISCOVERY RESULTS')
    expect(text()).not.toContain('The inventory could not be read')
    // The lifecycle SUMMARY survives — a measured count from a completed read is a fact, and
    // DiscoveryResults still states it as a stat tile.
    expect(text()).toContain('tagged for archive review')
    // What went is the per-file detail and the gate: the rule that produced a tag, the reason
    // recorded against the file, the RECOMMENDATIONS table and the approval bar that blocked
    // Assess until every row was decided.
    expect(text()).not.toContain("matched archive rule 'Legacy clinical policies'")
    expect(text()).not.toContain('Legacy clinical policies')
    expect(text()).not.toContain('I approve')
    expect(text()).not.toContain('RECOMMENDATIONS')
  })

  it('states a measured zero the same way, with nothing to approve, when the rules matched nothing', async () => {
    // The pair is the point: the stat tile must report a MEASURED zero here and a measured count
    // above, while the approval gate is absent from both. "0 tagged for archive review" over an
    // UNREAD estate is the false reassurance this file was written about, and the
    // read-did-not-complete cases below still pin that the tile is absent there.
    h.rows = h.rows.map((r) => ({ ...r, lifecycle_status: 'Active', lifecycle_rule_id: null, lifecycle_reason: null }))
    await render()
    expect(text()).toContain('DISCOVERY RESULTS')
    // The columns came back, so the zero here is a fact about the estate, not about the read.
    expect(text()).toContain('tagged for archive review')
    // …and there is nothing to approve, on either input.
    expect(text()).not.toContain('I approve')
  })
})

describe('a read that did not complete renders NOTHING — never a zero', () => {
  const absent = () => {
    // Every lifecycle-dependent surface, by the words only it produces.
    expect(text()).not.toContain('tagged for archive review')
    expect(text()).not.toContain('tagged for deletion review')
    expect(text()).not.toContain('RECOMMENDATIONS')
    expect(text()).not.toContain('EVERY DISCOVERED FILE, IN ONE BUCKET')
    expect(text()).not.toContain('I approve')
    // And nothing that would read as "we checked and found none".
    expect(text()).not.toContain('No recommendation')
    expect(text()).not.toContain('matched no file')
  }

  it('is absent when the route rejects', async () => {
    h.mode = 'reject'
    await render()
    // The rest of the screen still works — this is a missing section, not a broken tab.
    expect(text()).toContain('DISCOVERY RESULTS')
    expect(text()).toContain('files discovered')
    absent()
  })

  it('is absent when the read was truncated — a page is not the estate', async () => {
    h.mode = 'short'
    await render()
    expect(text()).toContain('DISCOVERY RESULTS')
    absent()
  })

  it('is absent while the read is still in flight', async () => {
    // The route never answers, so the screen stays in the state it is in before an answer.
    // "Not loaded yet" must look like "we do not know", not like "nothing is tagged".
    h.mode = 'pending'
    await render()
    expect(h.calls).toHaveLength(1)
    expect(text()).toContain('DISCOVERY RESULTS')
    absent()
  })

  it('is absent when there is no scan to read an inventory for', async () => {
    await render({ scanId: null })
    expect(h.calls).toHaveLength(0)
    absent()
  })

  it('does not block Assess on an acknowledgement it cannot show', async () => {
    h.mode = 'reject'
    await render()
    // The read failed, so no row carries a lifecycle_status — every row is 'unassessed', which has
    // nothing for a bulk action to accept, so no "Accept all" button renders at all. That absence
    // IS the assertion: Assess must not stay blocked waiting on a control that cannot exist.
    const acceptAll = [...container.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Accept all'))
    expect(acceptAll, 'a rejected read produced a recommendation to accept').toBeUndefined()
    // By the stable hook, not the label.
    const assess = container.querySelector('button[data-advance="assess"]')
    expect(assess.disabled).toBe(false)
  })
})

describe('a file the inventory did not cover is not promoted to "checked"', () => {
  it('makes no partition claim at all, rather than an unread file passing as decided', async () => {
    // The EVERY DISCOVERED FILE partition — which existed to keep an unread file in its own
    // bucket instead of folding it into "no recommendation" — was removed on 2026-09-02. A
    // partial read must therefore produce no partition, not a partition missing a bucket: the
    // second is the failure mode the panel existed to prevent.
    h.rows = [h.rows[0]]     // only one of the two files has an inventory row
    await render()
    expect(text()).toContain('DISCOVERY RESULTS')       // the screen rendered
    expect(text()).not.toContain('No lifecycle record was read for these')
    expect(text()).not.toContain('The buckets add up to the 2 files discovered')
    expect(text()).not.toContain('EVERY DISCOVERED FILE')
  })
})

describe('discovery-only run — no WCAG files, only unsupported formats in the inventory', () => {
  it('shows the Continue to Assess button even when files=[]; it must not be gated on WCAG results', async () => {
    // Simulate a user whose estate contains ONLY images/videos/unsupported formats.
    // The scan produced zero WCAG file_records (files=[]) but the inventory carries those rows.
    h.rows = [
      { file: 'Media/photo.png', path: 'Media/photo.png', status: 'discovered' },
      { file: 'Media/video.mp4', path: 'Media/video.mp4', status: 'discovered' },
    ]
    await render({ files: [] })
    // The button must exist — a discovery-only run should still be able to advance to Assess.
    const assess = container.querySelector('button[data-advance="assess"]')
    expect(assess, 'Continue to Assess button is missing on a discovery-only run').not.toBeNull()
    // No pending WCAG actions and no acknowledgement to gate on, so it must be enabled.
    expect(assess.disabled).toBe(false)
  })
})

// ── the live 2026-08-28 "0 documents discovered" report ────────────────────────────────
//
// Traced to GET /scans (api/routes/scans.py) using list_scans(), which filters to
// `completed_at IS NOT NULL` — never set on an ADR 0020 Discover-only run. App.jsx calls that
// route on load to build scanList and pickDefaultScan() (frontend/src/defaultScan.js) returns
// null for an empty list, so `run` (and therefore `scanId`/`scope`, both passed down from it)
// never got set at all on a deployment where Discover-only is the default. These two tests pin
// that exact contrast: the same DiscoveryResults component renders the live bug's symptom when
// scanId/scope are absent, and the REAL count once they carry what a fixed /scans route lets
// App.jsx actually find (api/store.py's list_finished_scans(), same fix already shipped for
// /monitor/estate in #907 and /schedule in #908).
describe('the live 2026-08-28 zero-documents report, reproduced and then fixed', () => {
  it('reproduces the exact symptom: no scanId/scope at all reads as a measured zero, not a missing answer', async () => {
    // This is what App.jsx handed Discover before the /scans fix, on any account whose most
    // recent scans were all Discover-only: pickDefaultScan([]) -> null -> setScan() never called.
    await render({ scanId: null, scope: null, files: [], run: null })
    expect(h.calls, 'no scanId means the inventory route must never even be called').toHaveLength(0)
    expect(text()).toContain('DISCOVERY RESULTS')
    expect(text()).toContain('0 documents discovered across 1 sources')
    expect(text()).toContain('0files discovered')
    // The header's scope/"listed" line is entirely absent, matching the live screenshot exactly
    // (no "folder:", no "listed <date>") — see DiscoveryResults.jsx's own header comment.
    expect(text()).not.toMatch(/listed \w+ \d/)
  })

  it('fixed: once scanId and scope.inventory carry what the now-fixed /scans route lets the app find, the real count renders', async () => {
    h.rows = [
      { file: 'Drive/report.pdf', path: 'Drive/report.pdf', status: 'discovered' },
      { file: 'Drive/handbook.docx', path: 'Drive/handbook.docx', status: 'discovered' },
    ]
    await render({
      scanId: 'scan-1',
      files: [],                                          // still nothing assessed — Discover-only
      scope: { kind: 'drive', inventory: { discovered: 32, truncated: false } },
      run: { id: 'scan-1', discovered_at: '2026-08-28T14:00:00Z' },
    })
    expect(h.calls[0]).toMatchObject({ scanId: 'scan-1' })
    expect(text()).toContain('DISCOVERY RESULTS')
    // The estate KPI row, the eligibility breakdown and the results panel all agree — this is the
    // concrete, DOM-level proof the fix works end to end, not just at the API layer. ("Discovery
    // complete · 32 files inventoried" was DiscoverCompleteSummary's wording; the panel that
    // replaced it on 2026-09-02 says "discovered 32" in its KPI row.)
    expect(text()).toContain('Estate overview')
    expect(text()).toMatch(/discovered32/)
    expect(text()).toContain('32files discovered')
    expect(text()).not.toContain('0files discovered')
    expect(container.querySelector('button[data-advance="assess"]')).toBeTruthy()
  })
})

describe('the scan ID on screen — QA and auditing need a name for this exact run', () => {
  it('shows the scan ID when one is on screen', async () => {
    await render()                       // default render() props include scanId: 'scan-1'
    expect(text()).toContain('Scan ID: scan-1')
  })

  it('shows nothing when there is no scan to name', async () => {
    await render({ scanId: null, scope: null, files: [], run: null })
    expect(text()).not.toContain('Scan ID:')
  })
})

describe('raw scan data — clicking the scan ID surfaces scope + the decision log for support', () => {
  it('is collapsed by default', async () => {
    await render({ scope: { kind: 'drive', inventory: { discovered: 32 },
                            enumeration: { auth_ok: true, files_found: 32, truncated: false } } })
    expect(text()).not.toContain('RAW SCAN DATA')
    expect(text()).toContain('show raw scan data')
  })

  it('reveals scope.enumeration and the decision log on click, copyable as one JSON blob', async () => {
    const c = await render({
      scope: { kind: 'drive', inventory: { discovered: 0 },
               enumeration: { auth_ok: true, files_found: 0, truncated: false } },
    })
    const toggle = [...c.querySelectorAll('button')].find((b) => /show raw scan data/.test(b.textContent))
    expect(toggle, 'no toggle to reveal the raw data').toBeTruthy()
    await act(async () => { toggle.click() })
    expect(text()).toContain('RAW SCAN DATA')
    // The exact fields a "why did this find nothing" investigation starts from.
    expect(text()).toContain('"auth_ok": true')
    expect(text()).toContain('"files_found": 0')
    expect(text()).toContain('scan-1')   // scan_id, inside the same JSON blob
    expect(text()).toContain('Copy to clipboard')
  })

  it('is absent entirely when there is no scan on screen', async () => {
    await render({ scanId: null, scope: null, files: [], run: null })
    expect(text()).not.toContain('show raw scan data')
    expect(text()).not.toContain('RAW SCAN DATA')
  })
})
