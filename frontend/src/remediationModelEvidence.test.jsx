import { describe, expect, it } from 'vitest'

// Keep the acceptance contract close to the UI: operational success is measured, while reviewer
// acceptance/edit and post-write validation remain explicitly unavailable until call IDs are
// linked to those outcome records.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(here, 'Settings.jsx'), 'utf8')

describe('remediation model evidence', () => {
  it('uses the measured per-model rollup and labels the evidence boundary', () => {
    expect(source).toContain('costs?.month?.by_model || []')
    expect(source).toContain('Remediation model evidence')
    expect(source).toContain('Success means the model call completed')
    expect(source).toContain('Reviewer acceptance, edit rate and post-write validation are not reported here yet')
    expect(source).not.toMatch(/estimated acceptance|estimated edit rate/i)
  })
})
