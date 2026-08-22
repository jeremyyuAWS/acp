// assessDashboardRetired.test.js
// Asserts that Dashboard is intentionally retired from the Assess tab post-run view.
// Dashboard.jsx is KEPT ON DISK so the retirement is one mount to reverse.
// If this test fails it means <Dashboard> was re-added to App.jsx -- remove it again
// (or delete this test if the component is deliberately re-mounted).

import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

describe('Dashboard retirement from Assess tab', () => {
  it('Dashboard.jsx still exists on disk (kept for easy re-mount)', () => {
    expect(existsSync(join(HERE, 'Dashboard.jsx'))).toBe(true)
  })

  it('App.jsx does NOT mount <Dashboard in the assessed results block', () => {
    const src = code('App.jsx')
    // The assessed block is identified by AssessWorklist being present.
    // <Dashboard should not appear near it.
    const assessedBlockStart = src.indexOf('AssessWorklist')
    expect(assessedBlockStart).toBeGreaterThan(-1)
    // Find the slice from AssessWorklist to the closing </> of that block
    const blockSlice = src.slice(assessedBlockStart, assessedBlockStart + 800)
    expect(blockSlice).not.toContain('<Dashboard')
  })
})
