import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Proves App.jsx actually uses isActiveJobStale to abandon a reconnect, and stamps/clears the
// companion timestamp everywhere it stamps/clears the job id — the pure staleness logic is
// covered on its own in activeJobStaleness.test.js. Source-level, matching this codebase's own
// established pattern for App.jsx (remediateWiring.test.jsx, monitorQueuePreGate.test.jsx):
// mounting the real App.jsx means stubbing its entire dependency graph for a check a static read
// answers directly.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('a job nobody ever claimed does not reconnect forever', () => {
  const app = () => code('App.jsx')

  it('imports isActiveJobStale', () => {
    expect(app()).toMatch(/import \{ isActiveJobStale \} from '\.\/activeJobStaleness\.js'/)
  })

  it('stamps ACTIVE_JOB_AT_KEY at the same call site ACTIVE_JOB_KEY is stamped', () => {
    const s = app()
    expect(s).toMatch(
      /sessionStorage\.setItem\(ACTIVE_JOB_KEY, job_id\)\s*\n\s*sessionStorage\.setItem\(ACTIVE_JOB_AT_KEY, String\(Date\.now\(\)\)\)/)
  })

  it('clears both keys together when the job resolves', () => {
    const s = app()
    expect(s).toMatch(/sessionStorage\.removeItem\(ACTIVE_JOB_KEY\)\s*\n\s*sessionStorage\.removeItem\(ACTIVE_JOB_AT_KEY\)/)
  })

  it('abandons a stale pending job on load instead of calling reconnectJob on it', () => {
    const s = app()
    const m = s.match(
      /let pendingJobId = sessionStorage\.getItem\(ACTIVE_JOB_KEY\)[\s\S]{0,400}?if \(pendingJobId\) \{\s*\n\s*reconnectJob\(pendingJobId\)/)
    expect(m, 'the load effect\'s pendingJobId handling was not found in the shape this test expects').toBeTruthy()
    expect(m[0]).toMatch(/isActiveJobStale\(Number\(sessionStorage\.getItem\(ACTIVE_JOB_AT_KEY\)\)\)/)
    expect(m[0]).toMatch(/pendingJobId = null/)
  })
})
