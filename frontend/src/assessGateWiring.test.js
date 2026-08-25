/**
 * The Assess tab shows a gate ("Available after discovery completes") while discovery runs.
 *
 * When busy=true and run.completed_at is not yet set, the Assess tab should show only the
 * holding screen — no AssessSetup, no AssessRunner. Once discovery is done (completed_at
 * is set), the full Assess screen renders normally.
 *
 * Source-level, like assessSetupWiring.test.jsx: App.jsx is too large to mount for one
 * gating fact, so we read it as text and assert the structure directly.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

describe('Assess tab gate while discovery is running', () => {
  it('App.jsx contains the "Available after discovery completes" copy', () => {
    expect(app).toContain('Available after discovery completes')
  })

  it('the gate condition checks both busy and !run?.completed_at', () => {
    expect(app).toMatch(/busy && !run\?\.completed_at/)
  })

  it('AssessRunner is gated off during discovery', () => {
    // AssessRunner must be conditional on !(busy && !run?.completed_at) so it
    // does not start up while the discovery scan is still in flight.
    expect(app).toMatch(/!\(busy && !run\?\.completed_at\)[\s\S]{0,200}AssessRunner/)
  })

  it('AssessSetup is gated off during discovery', () => {
    // AssessSetup must include !busy in its condition so it stays hidden on the
    // gate screen and does not flash in on re-render.
    expect(app).toMatch(/!busy[\s\S]{0,100}AssessSetup/)
  })

  it('the gate offers a "Go to Discover" back link', () => {
    expect(app).toContain('Go to Discover')
  })
})
