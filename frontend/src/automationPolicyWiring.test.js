import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

describe('Remediate impact planner wiring', () => {
  it('retires the partial browser population and mounts the run-backed planner', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const source = readFileSync(join(here, 'Remediate.jsx'), 'utf8')
    expect(source).toMatch(/<RemediationImpactCard[^>]*runId=\{runId\}/)
    expect(source).not.toContain('<AutomationPolicyControl')
    expect(source).not.toContain('const automationPolicyFindings')
    // Intentionally retired, retained so the earlier policy presentation can be restored.
    expect(readFileSync(join(here, 'AutomationPolicyControl.jsx'), 'utf8')).toContain('export default')
  })
})
