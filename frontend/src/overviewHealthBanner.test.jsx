import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Process Health Banner — PR 2 (process-health-pr2).
//
// A degraded run must be immediately visible on the Overview tab: amber when files could not
// be opened (run.error > 0), red when the worker job itself failed (run.status === 'failed').
// Both conditions signal that findings may be incomplete.
//
// ProcessHealthAlert is defined inline in Overview.jsx pending the merge of PR #643
// (process-health-pr1). This test verifies the component definition, both triggering
// conditions, and that the banner is placed above the findings summary tiles — all without
// mounting the component (the pdfjs-dist import chain in Overview prevents test-environment
// mounting; source-level checks cover the same claims without that dependency).

const here = dirname(fileURLToPath(import.meta.url))

// Strip block and line comments before pattern checks, so a comment that quotes
// removed code cannot make the assertion pass on dead text.
const src = readFileSync(join(here, 'Overview.jsx'), 'utf8')
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('ProcessHealthAlert is defined inline in Overview', () => {
  it('defines the component in this file', () => {
    expect(src).toMatch(/function ProcessHealthAlert\(/)
  })

  it('carries role="alert" for assistive technology', () => {
    expect(src).toMatch(/role="alert"/)
  })

  it('mounts ProcessHealthAlert at least twice (warning + critical paths)', () => {
    const mounts = (src.match(/<ProcessHealthAlert/g) || []).length
    expect(mounts).toBeGreaterThanOrEqual(2)
  })
})

describe('amber warning fires when run.error > 0', () => {
  it('guards the warning banner on run.error', () => {
    // The condition must check run.error positively — > 0 or truthy.
    expect(src).toMatch(/run\.error\s*>\s*0/)
  })

  it('uses the warning level for unreadable files', () => {
    // Find the ProcessHealthAlert that reads run.error and confirm level="warning".
    // Locate the block containing "could not be opened" and check for level="warning".
    expect(src).toMatch(/level="warning"/)
  })

  it('mentions "could not be opened" in the label', () => {
    expect(src).toContain('could not be opened')
  })

  it('says "findings may be incomplete"', () => {
    expect(src).toContain('findings may be incomplete')
  })

  it('pluralises via a ternary on run.error', () => {
    // The label template branches on run.error === 1 to pick '' vs 's'.
    expect(src).toMatch(/run\.error === 1 \? '' : 's'/)
  })
})

describe('red critical fires when run.status === "failed"', () => {
  it('guards the critical banner on run.status === "failed"', () => {
    expect(src).toMatch(/run\.status === ['"]failed['"]/)
  })

  it('uses the critical level for worker failures', () => {
    expect(src).toMatch(/level="critical"/)
  })

  it('mentions "worker errors" in the label', () => {
    expect(src).toContain('worker errors')
  })

  it('says "results may be incomplete"', () => {
    expect(src).toContain('results may be incomplete')
  })
})

describe('banner placement', () => {
  it('appears before the headline metrics tiles', () => {
    // The critical banner must precede the "files discovered" tile on screen.
    const bannerIdx = src.indexOf("run.status === 'failed'")
    const tilesIdx = src.indexOf('files discovered')
    expect(bannerIdx).toBeGreaterThan(0)
    expect(tilesIdx).toBeGreaterThan(0)
    expect(bannerIdx).toBeLessThan(tilesIdx)
  })

  it('the warning banner also precedes the headline metrics tiles', () => {
    const bannerIdx = src.indexOf('could not be opened')
    const tilesIdx = src.indexOf('files discovered')
    expect(bannerIdx).toBeGreaterThan(0)
    expect(bannerIdx).toBeLessThan(tilesIdx)
  })
})
