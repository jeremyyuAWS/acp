import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Retired from Assess on 2026-09-03. AssessRunProgress now owns the authoritative live progress
// experience, so mounting ProcessingStatusPanel here would recreate the duplicate green status
// banner, percentage bar, and worker summary. Keep the shared component for its other consumers.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'AssessRunner.jsx'), 'utf8')

describe('the shared processing panel is retired from AssessRunner', () => {
  it('keeps the component available but does not mount it in the Assess file-list panel', () => {
    expect(src).not.toMatch(/import ProcessingStatusPanel/)
    expect(src).not.toMatch(/<ProcessingStatusPanel/)
  })

  it('keeps the live per-document list mounted', () => {
    expect(src).toContain('aria-label="Per-document assessment progress"')
  })
})
