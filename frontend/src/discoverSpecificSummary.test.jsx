import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const discover = readFileSync(join(here, 'Discover.jsx'), 'utf8')

describe('Discover keeps its own information hierarchy', () => {
  it('keeps Discover scan-specific and leaves full-estate context to Overview', () => {
    expect(discover).toMatch(/id="discover-latest"/)
    expect(discover).not.toMatch(/id="discover-estate"/)
    expect(discover).not.toMatch(/<EstateProgressPanel/)
  })

  it('shows lifecycle details only when actionable matches exist', () => {
    expect(discover).toMatch(/lifecycleCandidateRows\.length > 0[\s\S]{0,500}<DiscoveryLifecycleResults/)
    expect(discover).toMatch(/lifecycle_status === 'Archive Candidate'/)
    expect(discover).toMatch(/lifecycle_status === 'Delete Candidate'/)
  })

  it('shows the lifecycle estate summary even when no rule produced a candidate', () => {
    expect(discover).toMatch(/id="discover-lifecycle-estate"[\s\S]{0,350}<DiscoveryLifecycleEstateSummary/)
    expect(discover).not.toMatch(/lifecycleCandidateRows\.length > 0[\s\S]{0,350}id="discover-lifecycle-estate"/)
  })
})
