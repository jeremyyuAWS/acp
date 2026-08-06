import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// ADR 0026 Epic 5 — the Assessment Timeline: the persisted per-document events grouped into
// pipeline stages, each node timestamped from its REAL events and click-through auditable.
// A stage with no events is ⬜ pending — never a fabricated timestamp (ADR 0016).
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'FileDrawer.jsx'), 'utf8')

describe('Assessment Timeline — auditable stages over the append-only record', () => {
  it('stages are derived from persisted event kinds only', () => {
    expect(src).toMatch(/const TIMELINE_STAGES = \[/)
    expect(src).toMatch(/\['Scanned', \['scan'\]\]/)
    expect(src).toMatch(/\['Human review', \['review', 'human', 'decision'\]\]/)
    expect(src).toMatch(/events\.filter\(\(e\) => kinds\.includes\(e\.kind\)\)/)
  })

  it('a stage with no events renders pending — no fabricated timestamp, node disabled', () => {
    expect(src).toMatch(/const done = evs\.length > 0/)
    expect(src).toMatch(/<span className="atl-meta muted">pending<\/span>/)
    expect(src).toMatch(/disabled=\{!done\}/)
  })

  it('a done stage is timestamped from its real last event and expands to the events themselves', () => {
    expect(src).toMatch(/const last = done \? evs\[evs\.length - 1\] : null/)
    expect(src).toMatch(/fmtTs\(last\.ts\)/)
    expect(src).toMatch(/\{isOpen && done && \(/)
    expect(src).toMatch(/\{evs\.map\(eventRow\)\}/)
  })

  it('the timeline replaced the flat audit list in the drawer mount', () => {
    expect(src).toMatch(/<AssessmentTimeline scanId=\{scanId\} file=\{file\?\.file\} \/>/)
    expect(src).not.toMatch(/<AuditTimeline /)
  })
})
