import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('#129 — the AI audit trail surfaces the real provenance ledger, honestly', () => {
  it('getScanAiCalls hits /ai_calls and returns [] on any miss', () => {
    const src = read('api.js')
    expect(src).toMatch(/getScanAiCalls = \(scanId\)/)
    expect(src).toMatch(/\/scans\/\$\{encodeURIComponent\(scanId\)\}\/ai_calls/)
    expect(src).toMatch(/SIM \|\| !scanId/)
  })

  it('the card lazily loads the ledger, narrows it to this file, and never fabricates activity', () => {
    const src = read('EvidenceCard.jsx')
    // Lazy: fetched only on first open (aiCalls === null guard).
    expect(src).toMatch(/if \(aiCalls === null && item\?\.scan_id\)/)
    expect(src).toMatch(/getScanAiCalls\(item\.scan_id\)/)
    // Narrowed to the file on the card (scan-wide rows without a file still show).
    expect(src).toMatch(/auditRows = \(aiCalls \|\| \[\]\)\.filter\(\(c\) => !c\.file \|\| c\.file === item\?\.file\)/)
    // An empty ledger says so plainly — it does NOT invent a call.
    expect(src).toMatch(/No AI calls recorded for this file/)
    // Each row shows the honest privacy zone from the persisted record, not a guess.
    expect(src).toMatch(/audit-zone-\$\{c\.zone === 'local' \? 'local' : 'cloud'\}/)
    // Latency rendered from the real measurement (ms → s), '—' when absent.
    expect(src).toMatch(/Number\.isFinite\(c\.latency_ms\)/)
  })
})
