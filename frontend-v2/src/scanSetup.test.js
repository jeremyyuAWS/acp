import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The first screen used to explain the product and ask nothing. It held three boxes describing
// Discover, Assess and Remediate — restating the nav directly above them — while the decision
// that shapes all three, what to assess, was made two screens away at the top of Discover.
//
// It is now the configurator: file types, checks, source, scan.
//
// THE DESIGN CONSTRAINT THIS FILE EXISTS TO HOLD. `scan_scope` is ONE map of criterion →
// formats, and two components already write all of it without knowing about each other:
// FileTypeConfig saves `scopeForFormats(allowed)` — every criterion, restricted to the ticked
// formats — so it discards a criterion narrowing; ScanScope saves its per-criterion selection
// and ignores the type toggles. Whichever was touched last wins, silently.
//
// On separate screens that is latent. Putting both on ONE screen would make it immediate: tick
// a format, watch your criteria come back. So this screen owns both axes and derives the map
// once at save. The assertions below are what stop someone "simplifying" it back into two
// panels side by side.
//
// Comment-stripped: this header names the very symbols and strings the assertions forbid.

const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

describe('the first screen asks before it scans', () => {
  it('renders the configurator, not an explainer', () => {
    const s = code('EmptyState.jsx')
    expect(s).toMatch(/<ScanSetup\b/)
    expect(s, 'the Discover/Assess/Remediate boxes are back').not.toContain('onboarding-step')
  })

  it('retires the CSS with the markup', () => {
    // Dead selectors outlive dead markup and invite it back.
    expect(readFileSync(join(HERE, 'styles.css'), 'utf8')).not.toContain('.onboarding-step {')
  })

  it('gets the SharePoint token, so the source line can be honest', () => {
    expect(code('App.jsx')).toMatch(/<EmptyState [^>]*hasSPToken=\{hasSPToken\}/)
  })
})

describe('one editor, two axes, one write', () => {
  const s = () => code('ScanSetup.jsx')

  it('writes scan_scope exactly once', () => {
    expect(s().match(/updateSettings\(/g) || []).toHaveLength(1)
    expect(s()).toMatch(/scan_scope: JSON\.stringify\(scope\)/)
  })

  it('does not compose the two panels that fight over the setting', () => {
    // The whole reason this component exists rather than a two-panel layout.
    expect(s(), 'FileTypeConfig would overwrite the criterion selection').not.toContain('FileTypeConfig')
    expect(s(), 'ScanScope would overwrite the format selection').not.toMatch(/<ScanScope\b/)
  })

  it('derives the map from criteria × formats', () => {
    const src = s()
    expect(src).toMatch(/if \(!criteria\.has\(row\.sc\)\) continue/)
    expect(src).toMatch(/row\.formats\.filter\(\(f\) => formats\.has\(f\)\)/)
  })

  it('refuses an empty scope instead of storing it', () => {
    // {} reads as NO restriction on the backend — "assess nothing" saved as "assess
    // everything", silently. Same refusal ScanScope makes.
    expect(s()).toMatch(/if \(!scCount\)/)
  })
})

describe('what it offers is derived, never typed', () => {
  const s = () => code('ScanSetup.jsx')

  it('offers the tracked criteria the engine can judge', () => {
    expect(s()).toMatch(/SCOPE_UNIVERSE\.filter\(\(r\) => TRACKED_17\.has\(r\.sc\)\)/)
  })

  it('offers four file types from the generated list, and no html', () => {
    // SCOPE_FORMATS is the document set; the universe generator excludes html because this is a
    // document engagement. An html checkbox would change nothing when ticked — the defect #168
    // removed for criteria.
    const src = s()
    expect(src).toMatch(/SCOPE_FORMATS\.map/)
    expect(src).not.toMatch(/['"]html['"]/)
  })

  it('groups by the criterion number rather than a hand-written map', () => {
    expect(s()).toMatch(/r\.sc\.startsWith\(digit/)
  })

  it('defaults to the Core 17 preset', () => {
    expect(s()).toMatch(/const CORE = 'acp-core-17'/)
  })
})

describe('it does not overstate what a selection means', () => {
  const s = () => code('ScanSetup.jsx')

  it('counts pairs, not just criteria', () => {
    // "17 checks" over four file types reads as 68. The engine has no lane for some
    // combinations, so the pair count is the honest one.
    expect(s()).toMatch(/pairCount\} criterion × format pairs/)
  })

  it('shows which formats each criterion is judged on', () => {
    // 2.1.1 is pptx-only; 2.4.3 is pdf+pptx. A row with no formats implies all four.
    expect(s()).toMatch(/r\.formats\.map\(\(f\) => f\.toUpperCase\(\)\)/)
  })

  it('reports the capability lane as a set, not the best of them', () => {
    // A criterion is often automated on one format and human-only on another. Collapsing that
    // to the strongest answer tells an operator ACP can fix something it cannot.
    expect(s()).toMatch(/modes\.size > 1/)
  })

  it('does not label the preset as plain WCAG 2.1 AA', () => {
    // ACP supports 17 criteria. "WCAG 2.1 AA" unqualified would imply the whole standard.
    expect(s()).toContain('WCAG 2.1 AA — 17 ACP-supported checks')
  })
})
