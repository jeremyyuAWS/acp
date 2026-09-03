/**
 * Estate Progress Panel — source-level assertions.
 *
 * Verifies structure rather than rendering: the component exists, exports a default,
 * and the Overview wires it with the right props. DOM-level tests are impractical here
 * because the dev server runs from the shared checkout (not the worktree), so we follow
 * the pattern from tokenRefreshBanner.test.js and midScanLogoutCleanup.test.js.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(here, f), 'utf8').split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') })
  .join('\n')

const panel = code('EstateProgressPanel.jsx')
const overview = code('Overview.jsx')
const discover = code('Discover.jsx')

describe('EstateProgressPanel component', () => {
  it('exports a default function', () => {
    expect(panel).toMatch(/export default function EstateProgressPanel/)
  })

  it('accepts inventory prop and reads discovered from it', () => {
    expect(panel).toMatch(/inventory\?\.discovered/)
  })

  it('reads the eligible count through estateFunnel, not off one field', () => {
    // `assessmentEligible()` prefers the direct `assessment_eligible` field and falls back to the
    // older `by_status.assessable` shape. Reading `inventory?.assessment_eligible` alone — which is
    // what this line used to pin — made a scan recorded under the older shape report an eligible
    // count here that disagreed with DiscoveryResults' own "Assessable" tile on the same screen.
    expect(panel).toMatch(/import \{ ASSESSABLE_FORMATS, assessmentEligible \} from '\.\/estateFunnel\.js'/)
    expect(panel).toMatch(/const eligible\s+= assessmentEligible\(inventory\)/)
  })

  it('does not repeat the funnel values in a separate KPI row', () => {
    expect(panel).not.toMatch(/function KpiCard/)
    expect(panel).not.toMatch(/<KpiCard/)
  })

  it('renders the four funnel stages', () => {
    expect(panel).toMatch(/Discovered/)
    expect(panel).toMatch(/Eligible/)
    expect(panel).toMatch(/Assessed/)
    expect(panel).toMatch(/Remediated/)
  })

  it('renders a pending-work table', () => {
    expect(panel).toMatch(/function PendingRow/)
    expect(panel).toMatch(/<PendingRow/)
  })

  it('returns null when no estate data exists', () => {
    expect(panel).toMatch(/hasAnyData[\s\S]{0,50}return null/)
  })

  it('places optional recent-scan content before document types', () => {
    expect(panel.indexOf('{afterProgress}')).toBeGreaterThan(panel.indexOf('Estate progress funnel'))
    expect(panel.indexOf('{afterProgress}')).toBeLessThan(panel.indexOf('Document types + Pending work'))
  })
})

describe('EstateProgressPanel wired in Overview', () => {
  it('imports EstateProgressPanel', () => {
    expect(overview).toMatch(/import EstateProgressPanel from ['"]\.\/EstateProgressPanel\.jsx['"]/)
  })

  it('mounts EstateProgressPanel with inventory prop', () => {
    expect(overview).toMatch(/<EstateProgressPanel[\s\S]{0,400}inventory=/)
  })

  it('passes analysed to EstateProgressPanel', () => {
    expect(overview).toMatch(/<EstateProgressPanel[\s\S]{0,400}analysed=/)
  })

  it('passes estateFiles to EstateProgressPanel', () => {
    expect(overview).toMatch(/<EstateProgressPanel[\s\S]{0,400}estateFiles=/)
  })

  it('passes onGo to EstateProgressPanel', () => {
    expect(overview).toMatch(/<EstateProgressPanel[\s\S]{0,400}onGo=/)
  })
})

describe('EstateProgressPanel wired in Discover', () => {
  it('uses the same single-source funnel without restoring the duplicate KPI row', () => {
    expect(discover).toMatch(
      /import EstateProgressPanel from ['"]\.\/EstateProgressPanel\.jsx['"]/,
    )
    expect(discover).toMatch(/<EstateProgressPanel[\s\S]{0,400}inventory=/)
    expect(discover).toMatch(/<EstateProgressPanel[\s\S]{0,600}afterProgress=\{\([\s\S]*?<LastSuccessfulScanSummary/)
    expect(panel).not.toMatch(/<KpiCard/)
  })
})
