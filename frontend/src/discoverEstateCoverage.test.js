import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The estate coverage funnel is NO LONGER on the Discover tab. Inverted rather than deleted, so the
// decision it recorded stays visible and the reversal is one commit — the same treatment
// v2Simplification got when the Upload capability was removed.
//
// WHAT THIS FILE USED TO ASSERT, verbatim, because the reasoning was sound and is worth keeping:
//
//     The estate coverage funnel (discovered → assessment-eligible → remediation-eligible) is shown
//     on the DISCOVER tab — where discovery happens — not only on Overview. Source-level, matching
//     the Overview coverage pin: a full Discover mount needs the whole sources/files/scope stack,
//     and one that rendered nothing would pass a "there is a coverage section" check by rendering
//     nothing.
//
// WHAT CHANGED IS THE PAGE AROUND IT, not that argument. When this landed, the funnel was the only
// thing on Discover that partitioned the estate. DiscoveryResults now does that — five buckets, a
// type breakdown, the unreadable reasons and the recommendations — so the two sat back to back
// stating the same headline count and deriving eligibility twice.
//
// And the funnel's third stage is REMEDIABLE, which is the reading Discover.jsx already rejected
// about itself, in its own words, a few hundred lines below where the funnel was mounted:
//
//     Discovery facts only. Rubric scores and remediation state used to appear here, which read as
//     "the scan already assessed and remediated your documents" — it does neither.
//
// This is a DE-DUPLICATION, not a retirement: Overview still mounts EstateCoverage, so the funnel
// and its cross-stage view are untouched. Only the second copy on the one tab that answers one
// question is gone. See discoverEstatePanelSingular.test.jsx for the live assertions.

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Discover.jsx'), 'utf8')
// Comments stripped: the explanation above quotes the very import it asserts is gone, and this file
// reads its own directory. A whole-file ban would match its own protected reasoning — the shape
// that has failed on correct code repeatedly in this repo.
const code = src
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('Discover no longer shows the estate coverage funnel', () => {
  it('imports neither EstateCoverage nor the funnel-progress helper', () => {
    expect(code).not.toMatch(/import EstateCoverage from '\.\/EstateCoverage\.jsx'/)
    expect(code).not.toMatch(/import \{ estateProgressFromFiles \} from '\.\/estateProgress\.js'/)
    // The stripper must not be what makes this pass.
    expect(code).toContain('export default function Discover')
    expect(code.length).toBeGreaterThan(2000)
  })

  it('and renders no funnel section', () => {
    expect(code).not.toMatch(/<EstateCoverage\b/)
  })

  it('while the panel that DID replace it is still mounted', () => {
    // Removing one estate partition is only correct while the other is there. If DiscoveryResults
    // ever comes off this tab, this becomes a capability deletion rather than a de-duplication.
    expect(code).toMatch(/<DiscoveryResults\b/)
  })

  it('and Overview still carries the funnel, so nothing was retired', () => {
    const overview = readFileSync(join(here, 'Overview.jsx'), 'utf8')
    expect(overview).toMatch(/<EstateCoverage\b/)
  })
})
