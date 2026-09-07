import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

describe('Remediate automation policy population', () => {
  it('combines the deterministic partition with proposal-backed review work', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const source = readFileSync(join(here, 'Remediate.jsx'), 'utf8')
    expect(source).toMatch(/workPartition\?\.lanes\?\.automatic\?\.findings/)
    expect(source).toMatch(/\.\.\.reviewNeeds/)
    expect(source).toMatch(/<AutomationPolicyControl[^>]*findings=\{automationPolicyFindings\}/)
  })
})
