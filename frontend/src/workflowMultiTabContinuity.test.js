/**
 * Multi-tab workflow continuity.
 *
 * Active stages are server-owned, so returning to a background tab must re-read that state
 * immediately. Otherwise a stage started or completed in another tab leaves the compact card
 * stale until the 15-second fallback poll happens to run.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

describe('active workflow refresh across browser tabs', () => {
  it('reconciles the durable compact card when the window regains focus', () => {
    expect(app).toContain("window.addEventListener('focus', refresh)")
    expect(app).toContain("window.removeEventListener('focus', refresh)")
    expect(app).toMatch(/const refresh = \(\) => \{[\s\S]*?getActiveWorkflows\(\)[\s\S]*?setActiveWorkflows/)
  })

  it('keeps the low-frequency poll as a fallback', () => {
    expect(app).toContain('setInterval(refresh, 15_000)')
    expect(app).toContain('clearInterval(id)')
  })
})
