import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(import.meta.dirname, 'automation-policy.css'), 'utf8')
const remediate = readFileSync(join(import.meta.dirname, 'Remediate.jsx'), 'utf8')

describe('automation policy presentation contract', () => {
  it('remains directly below the prominent Remediate header and before workspace tabs', () => {
    const header = remediate.indexOf('<RemediationRunHeader')
    const policy = remediate.indexOf('<AutomationPolicyControl')
    const tabs = remediate.indexOf('<RemediationWorkspaceTabs')
    expect(header).toBeGreaterThan(-1)
    expect(policy).toBeGreaterThan(header)
    expect(tabs).toBeGreaterThan(policy)
  })

  it('has responsive flow and narrow-phone policy layouts', () => {
    expect(css).toMatch(/@media \(max-width: 760px\)[\s\S]*automation-policy__flow/)
    expect(css).toMatch(/@media \(max-width: 430px\)[\s\S]*automation-policy__policies/)
  })

  it('animates only changed deltas and disables that animation for reduced motion', () => {
    expect(css).toMatch(/\.automation-policy__delta[^}]*animation:/)
    expect(css).not.toMatch(/automation-policy__(?:flow|routes|source)[^}]*animation:/)
    expect(css).toMatch(/prefers-reduced-motion: reduce[\s\S]*automation-policy__delta[^}]*animation: none/)
  })

  it('keeps touch scrolling available while the native slider handles horizontal input', () => {
    expect(css).toMatch(/automation-policy__slider input[^}]*touch-action: pan-y/)
    expect(css).toMatch(/automation-policy__ticks button[^}]*min-width: 44px[^}]*min-height: 34px/)
  })

  it('aligns every routing outcome to the same text column', () => {
    expect(css).toMatch(/automation-policy__routes > div[^}]*grid-template-columns: minmax\(150px, \.7fr\) minmax\(0, 1fr\) auto/)
    expect(css).toMatch(/automation-policy__route-impact[^}]*width: 100%[^}]*justify-self: start[^}]*text-align: left/)
  })
})
