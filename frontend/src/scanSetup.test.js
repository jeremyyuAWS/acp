import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The pre-scan configurator: file source, WCAG checks, scan.
//
// THE FORMAT AXIS MOVED TO ASSESS (Discover/Assess PRD §4.1, §4.4). `scan_scope` is one map of
// criterion → formats. Document type (the format axis) used to be Step 1 here, which is why this
// screen once owned BOTH axes — to avoid a "last touched wins" fight with the Settings
// FileTypeConfig panel. That decision relocated: Discover now shows the whole discovered estate,
// and document type is chosen in Assess (AssessScope.jsx), the single authority for the format
// axis. So this screen no longer offers file types — it selects the CRITERIA and derives their
// scope over the stored/format set. The assertions below hold that: it still writes scan_scope
// exactly once, still refuses an empty scope, and no longer renders a file-type picker.
//
// Comment-stripped: this header names the very symbols and strings the assertions check.

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

describe('one criterion axis, one write', () => {
  const s = () => code('ScanSetup.jsx')

  it('writes scan_scope exactly once', () => {
    expect(s().match(/updateSettings\(/g) || []).toHaveLength(1)
    expect(s()).toMatch(/scan_scope: JSON\.stringify\(scope\)/)
  })

  it('does not render either scope panel that also writes the setting', () => {
    // Rendering FileTypeConfig (format axis) or ScanScope (criterion × format) here would
    // reintroduce a second writer of scan_scope on the same screen.
    expect(s(), 'FileTypeConfig would overwrite the format selection').not.toMatch(/<FileTypeConfig\b/)
    expect(s(), 'ScanScope would overwrite the criterion selection').not.toMatch(/<ScanScope\b/)
  })

  it('derives the map from the selected criteria over the format set', () => {
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

describe('the format axis is no longer chosen here', () => {
  const s = () => code('ScanSetup.jsx')

  it('renders no file-type picker', () => {
    // The document-type chips (SCOPE_FORMATS.map into pressable chips) moved to Assess. A file-type
    // picker here is exactly the duplicate control the PRD removed.
    expect(s(), 'a file-type picker is still rendered here').not.toMatch(/SCOPE_FORMATS\.map/)
    expect(s(), 'a file-type toggle handler is still here').not.toMatch(/toggleFormat/)
  })

  it('still excludes html — this is a document engagement', () => {
    expect(s()).not.toMatch(/['"]html['"]/)
  })
})

describe('what it offers is derived, never typed', () => {
  const s = () => code('ScanSetup.jsx')

  it('offers the tracked criteria the engine can judge', () => {
    expect(s()).toMatch(/SCOPE_UNIVERSE\.filter\(\(r\) => TRACKED_17\.has\(r\.sc\)\)/)
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
    expect(s()).toMatch(/pairCount\} criterion × format pairs/)
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
