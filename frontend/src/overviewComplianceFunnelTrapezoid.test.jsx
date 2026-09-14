import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))

describe('the redundant compliance funnel is intentionally absent', () => {
  it('keeps Balanced Summary as the overview and retires the old funnels', () => {
    const overview = readFileSync(join(here, 'Overview.jsx'), 'utf8')
    expect(overview).toMatch(/<BalancedSummary\b/)
    expect(overview).not.toMatch(/<EstateProgressPanel\b/)
    expect(overview).not.toMatch(/id="compliance-funnel"/)
    expect(overview).not.toMatch(/className="trapfunnel"/)
  })
})
