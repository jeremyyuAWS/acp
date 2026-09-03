import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const discover = readFileSync(join(here, 'Discover.jsx'), 'utf8')

describe('Discover keeps its own information hierarchy', () => {
  it('leads with the latest discovery and subordinates shared estate context', () => {
    const latest = discover.indexOf('id="discover-latest"')
    const estate = discover.indexOf('id="discover-estate"')
    expect(latest).toBeGreaterThan(-1)
    expect(estate).toBeGreaterThan(latest)
    expect(discover).toMatch(/id="discover-estate"[\s\S]{0,180}defaultOpen=\{false\}/)
  })

  it('shows lifecycle details only when actionable matches exist', () => {
    expect(discover).toMatch(/lifecycleCandidateRows\.length > 0[\s\S]{0,500}<DiscoveryLifecycleResults/)
    expect(discover).toMatch(/lifecycle_status === 'Archive Candidate'/)
    expect(discover).toMatch(/lifecycle_status === 'Delete Candidate'/)
  })
})
