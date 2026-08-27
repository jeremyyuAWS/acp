/**
 * Scan superseding — a new scan that finishes server-side surfaces in the UI without a
 * page reload.
 *
 * Mechanism: a background listScans() poll runs every 60 s while idle (no in-flight scan).
 * When it finds a scan newer than the one on screen, isTimeTravel becomes true and the
 * banner offers a one-click switch. The banner distinguishes two causes:
 *   - explicitTimeTravel=true  → user deliberately went back in time (existing copy)
 *   - explicitTimeTravel=false → a new scan arrived (new "✨ New scan available" copy)
 *
 * Source-level assertions: App.jsx is too large to mount for these structural facts, so
 * we read it as text, exactly as assessGateWiring.test.js does.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

describe('scan superseding — background poll + banner differentiation', () => {
  it('App.jsx declares an explicitTimeTravel state variable', () => {
    expect(app).toMatch(/useState\(false\)[\s\S]{0,80}explicitTimeTravel|explicitTimeTravel[\s\S]{0,80}useState\(false\)/)
  })

  it('switchScan sets explicitTimeTravel based on whether the chosen scan is the latest', () => {
    // The logic: going to scanList[0] is "forward" (false); picking any older id is "back" (true).
    expect(app).toMatch(/setExplicitTimeTravel\(scanList\.length > 0 && id !== scanList\[0\]\.id\)/)
  })

  it('background poll uses setInterval to refresh listScans while idle', () => {
    expect(app).toMatch(/setInterval[\s\S]{0,200}listScans\(\)\.then\(setScanList\)/)
  })

  it('background poll runs at 60 s intervals', () => {
    expect(app).toMatch(/60[_,]?000/)
  })

  it('background poll is cleared on cleanup', () => {
    // The effect must return a cleanup that calls clearInterval to avoid memory leaks.
    expect(app).toMatch(/clearInterval\(id\)/)
  })

  it('background poll is gated on me and not busy — avoids firing during a live scan', () => {
    expect(app).toMatch(/if \(!me \|\| busy\) return[\s\S]{0,300}listScans\(\)\.then\(setScanList\)/)
  })

  it('the "new scan available" banner text appears when !explicitTimeTravel', () => {
    expect(app).toContain('New scan available')
  })

  it('"new scan available" banner is gated on !explicitTimeTravel', () => {
    // The explicitTimeTravel branch shows the time-travel replay copy;
    // the else branch shows the new-scan-available copy. The window is wide because
    // the time-travel span + its comment separates the two in the source.
    expect(app).toMatch(/explicitTimeTravel[\s\S]{0,1200}New scan available/)
  })

  it('a scan completing from this tab resets explicitTimeTravel to false', () => {
    // Count the setExplicitTimeTravel(false) calls — should appear at completion of
    // doScan, reconnectJob, and the scan-unavailable recovery path.
    const matches = [...app.matchAll(/setExplicitTimeTravel\(false\)/g)]
    expect(matches.length, 'expected setExplicitTimeTravel(false) at scan-complete sites').toBeGreaterThanOrEqual(3)
  })

  it('sign-in resets explicitTimeTravel alongside scan and scanList', () => {
    // The sign-in reset line clears scan, scanList, and explicitTimeTravel together.
    expect(app).toMatch(/setScan\(null\)[\s\S]{0,80}setScanList\(\[\]\)[\s\S]{0,80}setExplicitTimeTravel\(false\)|setExplicitTimeTravel\(false\)[\s\S]{0,80}setScan\(null\)/)
  })
})
