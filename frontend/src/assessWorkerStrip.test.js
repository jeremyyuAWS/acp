import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Retired from Assess on 2026-09-03. Worker and progress summaries now live in the authoritative
// AssessRunProgress card; AssessRunner is intentionally limited to alerts and per-file activity.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'AssessRunner.jsx'), 'utf8')

describe('the duplicate worker summary is retired from AssessRunner', () => {
  it('does not render the old worker strip', () => {
    expect(src).not.toContain('className="assesshealth"')
    expect(src).not.toContain('progress not confirmed')
    expect(src).not.toContain('<WorkerReplicaControl')
  })

  it('retains the file-level activity list', () => {
    expect(src).toContain('activeAssessmentFiles(workerSnap?.jobs, runId)')
    expect(src).toContain('aria-label="Per-document assessment progress"')
  })
})
