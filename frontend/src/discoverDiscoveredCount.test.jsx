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
