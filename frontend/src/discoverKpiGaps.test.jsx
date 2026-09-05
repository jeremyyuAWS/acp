/**
 * Three KPI gaps that made the BY AGE / BY SIZE / BY FOLDER panels permanently invisible
 * on any real Discover run, and caused the completion summary to never appear on
 * discover-only scans (ADR 0020).
 *
 * Gap 1 — invRows never forwarded.
 *   DiscoveryResults computed `invRows = inventory?.rows ?? null` but `inventory`
 *   (= `scope.inventory`) is a summary object with no `.rows`. The per-file rows
 *   live in `inv` in Discover.jsx and were never forwarded, so all three distribution
 *   panels returned null on every real scan.
 *
 * Gap 2 — DiscoverCompleteSummary gated on `completed_at`, which is NULL for discover-only
 *   scans (set only when ASSESS finishes, per ADR 0020 / handlers.py:1323).
 *
 * Gap 3 — DiscoverRunProgress `onContinue` not wired, so the done-card CTA in the
 *   run-progress panel was inert.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const discover = read('Discover.jsx')
const results = read('DiscoveryResults.jsx')

// ── Gap 1 — invRows prop ──────────────────────────────────────────────────────

describe('source — per-file inventory rows reach DiscoveryResults', () => {
  it('DiscoveryResults accepts invRows as an explicit prop', () => {
    // The prop must exist in the signature so Discover can pass inv.rows in.
    expect(results).toMatch(/invRows\s*=\s*null/)
  })

  it('DiscoveryResults does NOT derive invRows from inventory.rows', () => {
    // inventory (= scope.inventory) is the summary object — it has no .rows.
    // Deriving from it silently discards the per-file rows and hides every distribution panel.
    expect(results).not.toMatch(/inventory\?\.rows/)
    expect(results).not.toMatch(/inventory\.rows/)
  })

  it('Discover forwards inv.rows to DiscoveryResults as invRows', () => {
    // inv is the per-file inventory loaded by loadDiscoveryInventory.
    expect(discover).toMatch(/invRows=\{inv\?\.rows \?\? null\}/)
  })
})

// ── Gap 2 — discovered_at gate ────────────────────────────────────────────────

describe('source — DiscoverCompleteSummary shows after discovery, not assessment', () => {
  it('gates on run.discovered_at, not run.completed_at', () => {
    // completed_at is set at the end of ASSESS (handlers.py:1053). A discover-only
    // scan (ADR 0020) never sets it, so gating on it means the summary never appears.
    expect(discover).toMatch(/run\?\.discovered_at/)
    // The gate must not fall back to completed_at — that is the bug we just fixed.
    expect(discover).not.toMatch(/DiscoverCompleteSummary[\s\S]{0,30}completed_at/)
  })

  it('also accepts status===discovered as a fallback when discovered_at is missing', () => {
    // A scan whose worker was interrupted after inventory-write but before _mark_discovered
    // has status='discovered' in Postgres but discovered_at=NULL. That is durable state
    // (per the PRD, "Postgres checkpoints are sufficient to render a truthful fallback card"),
    // so the card must render even without the timestamp.
    expect(discover).toMatch(/run\?\.status\s*===\s*['"]discovered['"]/)
    // The estatebar fallback hides under the same condition so the two panels don't both show.
    // displayBusy is the active job only when it belongs to the displayed scan. A raw global
    // `busy` here painted a newer job over a completed Scan History selection.
    const estatebarGate = discover.match(/displayBusy\s*\|\|\s*!\(run\?\.discovered_at[^)]+\)/)
    expect(estatebarGate).not.toBeNull()
  })
})

// ── Gap 3 — onContinue wired ──────────────────────────────────────────────────

describe('source — DiscoverRunProgress gets the Continue callback', () => {
  it('passes onContinue={onAdvance} to DiscoverRunProgress', () => {
    // Without this the done-card CTA inside DiscoverRunProgress is disabled.
    expect(discover).toMatch(/onContinue=\{onAdvance\}/)
  })
})

// ── DOM — distribution panels appear when invRows is provided ─────────────────

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
afterEach(unmountAll)

const row = (file, extra = {}) => ({
  file, size_kb: 100, source_modified: '2024-01-01T00:00:00Z', parent_folder: 'Dept/Sub',
  tags: [], issues: [], department: 'Clinical', sourceName: 'SharePoint', ...extra,
})

it('BY AGE panel renders when invRows has rows with source_modified', async () => {
  const rows = [
    row('a.pdf', { source_modified: '2020-06-01T00:00:00Z' }),
    row('b.pdf', { source_modified: '2022-06-01T00:00:00Z' }),
  ]
  await act(async () => {
    root.render(createElement(DiscoveryResults, { files: rows, invRows: rows }))
  })
  expect(container.textContent).toMatch(/by age/i)
})

it('BY SIZE panel renders when invRows has rows with size_kb', async () => {
  const rows = [
    row('a.pdf', { size_kb: 50 }),
    row('b.pdf', { size_kb: 5000 }),
  ]
  await act(async () => {
    root.render(createElement(DiscoveryResults, { files: rows, invRows: rows }))
  })
  expect(container.textContent).toMatch(/by size/i)
})

it('BY FOLDER panel renders when invRows has rows with parent_folder', async () => {
  const rows = [
    row('a.pdf', { parent_folder: 'HR/Policies' }),
    row('b.pdf', { parent_folder: 'HR/Policies' }),
  ]
  await act(async () => {
    root.render(createElement(DiscoveryResults, { files: rows, invRows: rows }))
  })
  expect(container.textContent).toMatch(/by folder/i)
})

it('distribution panels are absent when invRows is null', async () => {
  const rows = [row('a.pdf')]
  await act(async () => {
    root.render(createElement(DiscoveryResults, { files: rows, invRows: null }))
  })
  // No crash, but no distribution panels either.
  expect(container.textContent).not.toMatch(/by age/i)
  expect(container.textContent).not.toMatch(/by size/i)
  expect(container.textContent).not.toMatch(/by folder/i)
})
