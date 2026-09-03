import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// AssessRunProgress owns the visible run progress now. AssessRunner remains responsible for the
// detailed, scrollable file activity list and must not grow a second progress presentation again.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'AssessRunner.jsx'), 'utf8')

describe('AssessRunner is file detail, not a second progress card', () => {
  it('does not mount the retired summary UI', () => {
    expect(src).not.toContain('className="assessbar"')
    expect(src).not.toContain('className="assessrunmeta"')
    expect(src).not.toContain('Computing conformance')
    expect(src).not.toContain('<ProcessingStatusPanel')
  })

  it('keeps the per-document progress list and result detail', () => {
    expect(src).toContain('aria-label="Per-document assessment progress"')
    expect(src).toContain('className="alname"')
    expect(src).toContain('className="alscore"')
    expect(src).toContain('reading criteria…')
  })
})
