import { describe, expect, it } from 'vitest'

// Keep the acceptance contract close to the UI: operational success is measured; reviewer
// decisions and post-write validation are shown only where the decision recorded the exact
// model call, and a model with none reads "Not linked" rather than a rate over nothing.
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
    expect(source).toContain('<th>Reviewer decisions</th><th>Post-write validation</th>')
    expect(source).toContain('reviewedCell(m.reviewed)')
    expect(source).toContain('validationCell(m.validation)')
    expect(source).toContain("return 'Not linked'")
    expect(source).toContain('read as not linked rather than estimated')
    expect(source).not.toMatch(/estimated acceptance|estimated edit rate/i)
    expect(source).not.toContain('are not reported here yet')
  })

  it('shows the declared criterion-level rollout decision without licensing automation', () => {
    expect(source).toContain('costs?.shadow_rollout')
    expect(source).toContain('Stronger-model rollout gates')
    expect(source).toContain("r.verdict === 'enable'")
    expect(source).toContain('Assisted pilot—human approval required')
    expect(source).toContain('Review all {rolloutRows.length} criterion-format decisions')
    expect(source).toContain('The gate is evidence, not a deployment switch')
  })
})
