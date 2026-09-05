/**
 * The complete, exact set of components nothing renders — pinned, so the list cannot drift.
 *
 * WHY AN EXACT SET RATHER THAN A WATCHLIST. `lastTwoWiring.test.jsx` already guards the other
 * direction: named components that MUST be mounted. Nothing guarded this one, and it drifted — a
 * 2026-08-30 audit found 17 unmounted components against the 12 CLAUDE.md declared, with two of the
 * undeclared five (`ScopeFunnel`, `ProcessingDetails`) additionally carrying a DEAD IMPORT in
 * App.jsx, which is what makes an orphan actively misleading: a reader greps, sees the import, and
 * concludes it is wired.
 *
 * A watchlist of known orphans would not have caught that, because the whole failure is a component
 * silently JOINING the set. So this asserts set equality in both directions:
 *   · a component that stops being rendered fails until it is listed here (and in CLAUDE.md),
 *   · a listed one that gets mounted fails until it is removed from here.
 * Either failure is a prompt to update the record, not a bug to route around.
 *
 * WHAT COUNTS AS UNMOUNTED. A module with a DEFAULT export that no screen renders as <Component/>.
 * Modules that exist only for named exports are NOT orphans and are excluded by construction:
 * `Transparency.jsx` (TraceChip, RuleBreakdown) and `charts.jsx` (Donut, Bars, …) are imported and
 * used all over the app despite having no default component to mount. An earlier pass of this audit
 * flagged both, which is exactly the false positive this rule removes.
 *
 * NOT A LIST OF THINGS TO DELETE OR WIRE UP. CLAUDE.md's standing instruction is to keep retired
 * features so restoring one is a single commit — and several of these were removed deliberately.
 * Four of them (`Dashboard`, `ProcessingDetails`, `ScanSetup`, `ScopeFunnel`) were never mounted at
 * any point in this repo's history, verified with `git log -S`, so they are unbuilt rather than
 * retired. Neither state is a defect on its own; being invisible on a status list is.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Comments stripped for the reason discoverUploadRemoved.test.jsx strips them: a comment explaining
// an absence necessarily names the absent thing, so an un-stripped scan matches its own explanation.
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

const screens = () => readdirSync(here).filter((f) => f.endsWith('.jsx') && !f.includes('.test.'))

/** Components with a default export — the only ones that can be "mounted" at all. */
function defaultExporting() {
  return screens()
    .filter((f) => /export default/.test(read(f)))
    .map((f) => f.replace(/\.jsx$/, ''))
}

function unmounted() {
  const bodies = screens().map((f) => [f.replace(/\.jsx$/, ''), code(f)])
  return defaultExporting()
    .filter((c) => !bodies.some(([owner, body]) =>
      owner !== c && new RegExp(`<${c}[\\s/>]`).test(body)))
    .sort()
}

// The record. Update this together with CLAUDE.md's "Currently retired and mounted nowhere" list —
// they are the same fact and a test asserts below that they agree.
const EXPECTED_UNMOUNTED = [
  'AssessScope',
  // Retired 2026-09-02: removed from Overview (PRD "ACP Discover and Overview Simplification").
  // EstateProgressPanel covers the same estate funnel on both tabs. Kept per retired-feature policy.
  'AssessmentReconciliation',
  'ConfidenceDashboard',
  'ControlPlane',
  'Dashboard',           // never mounted in repo history — unbuilt, not retired
  // Retired 2026-09-02: replaced by EstateProgressPanel at the top of Discover. Kept per policy.
  'DiscoverCompleteSummary',
  // Retired 2026-09-03: the whole-estate confidence copy overstated non-zero partial listings.
  // Keep the component available, but make its intentionally unmounted state explicit.
  'DiscoveryCompleteness',
  'Disposition',
  // Retired 2026-09-02 on the owner's request: mounted in Discover, it listed the WHOLE estate
  // — 200 rows of .pyc, .py and .pfb files, every one "Active · No reason recorded", grouped
  // under "No rule recorded · no proposed action" — directly above the Lifecycle results section
  // that already answers the same question for the files a rule actually matched. Kept per the
  // retired-feature policy; see dispositionReviewRemoved.test.jsx.
  'DispositionReviewWorkspace',
  // Retired 2026-09-02: removed from Overview (PRD simplification). EstateProgressPanel
  // and the compliance funnel are the retained coverage story. Kept per retired-feature policy.
  'EstateCoverage',
  // Retired 2026-09-02: removed from Overview (PRD simplification). Kept per retired-feature policy.
  'EstateTreemap',
  'FileTypeConfig',
  // Retired 2026-09-02: removed from Overview (PRD simplification). The findings section that
  // rendered Insight tiles was removed. Kept per retired-feature policy.
  'Insight',
  // Retired 2026-09-02: removed from DiscoveryResults along with the RECOMMENDATIONS table.
  // The per-file override control has no mount point now the table is gone. Kept per policy.
  'LifecycleOverrideControl',
  'LiveAssessment',      // kept for reference; LiveAssessmentLive.jsx says so in its own header
  // Retired 2026-09-02: removed from Overview (PRD simplification). Kept per retired-feature policy.
  'PiiPanel',
  'ProcessingDetails',   // never mounted in repo history
  // Retired 2026-09-01: the Remediate redesign made the inbox's review panel the ONE
  // finding-level approval surface, so this second one was unmounted. Kept per the
  // retired-feature policy — restoring it is re-adding the mount, not rewriting the panel.
  'RemediationApprovals',
  // Retired 2026-09-05: run-level operations already reports the document pipeline. Repeating it
  // inside every finding displaced the human decision and made Guided Remediation unreadable.
  // The component remains available for a one-commit restore outside the decision pane.
  'RemediationDocProgress',
  // Retired 2026-09-04: the two-column Remediation PRD removes the third preview pane. The
  // full-document action remains in the review header; keep this component for easy restoration.
  'RemediationPreview',
  // Retired 2026-09-05: RemediationOpsPanel now owns the reconciled progress partition, active
  // workstream, throughput, activity and exceptions. Keep the legacy card for one-commit restore.
  'RemediationRunProgress',
  // Retired 2026-09-04: the oversized Found → Proposed → Verified tiles were replaced by the
  // readable Current / Proposed rows and a collapsed definition list. Kept per retirement policy.
  'RemediationTransform',
  'RiskScore',
  'RolePrivilege',
  'Rubric',
  'ScanScope',
  // Retired 2026-09-02: removed from Overview (PRD simplification). Kept per retired-feature policy.
  'ScanScopeChip',
  'ScanSetup',           // never mounted in repo history
  'ScopeFunnel',         // never mounted in repo history
  'ScopeRules',
  'ScreenReaderDemo',
  'Upload',
  // Retired 2026-09-02: removed from Overview (PRD simplification). Kept per retired-feature policy.
  'WordCloud',
]

describe('the set of unmounted components is exactly what we say it is', () => {
  it('matches the recorded list, in both directions', () => {
    expect(unmounted()).toEqual(EXPECTED_UNMOUNTED)
  })

  it('and the sweep is really reading the tree — this cannot pass vacuously', () => {
    expect(screens().length).toBeGreaterThan(100)
    expect(defaultExporting().length).toBeGreaterThan(100)
    // A positive control: App.jsx is mounted-by-nothing only because it is the root, so it must NOT
    // appear; and a component we know IS rendered must not appear either.
    expect(unmounted()).not.toContain('LiveAssessmentLive')
  })
})

describe('named-export modules are not orphans', () => {
  it('Transparency and charts are excluded because they have no default export to mount', () => {
    // Guards the rule itself: if either grows a default export, it enters the sweep and the exact-set
    // test above will say so rather than silently re-flagging them.
    expect(read('Transparency.jsx')).not.toMatch(/export default/)
    expect(read('charts.jsx')).not.toMatch(/export default/)
    // …and both are genuinely in use, which is why flagging them would have been wrong.
    const users = screens().filter((f) => /from '\.\/(Transparency|charts)\.jsx'/.test(read(f)))
    expect(users.length).toBeGreaterThan(2)
  })
})

describe('no orphan carries a dead import', () => {
  it('nothing imports a component it never renders', () => {
    // The specific thing that made ScopeFunnel and ProcessingDetails misleading rather than merely
    // dormant: App.jsx imported both, so the tree read as wired. Removed 2026-08-30.
    const offenders = []
    for (const f of screens()) {
      const body = code(f)
      for (const c of EXPECTED_UNMOUNTED) {
        if (new RegExp(`import\\s+${c}\\s+from`).test(body)) offenders.push(`${f} imports ${c}`)
      }
    }
    expect(offenders, 'an unmounted component is imported but never rendered — drop the import, or '
      + 'render it and update EXPECTED_UNMOUNTED').toEqual([])
  })
})

describe('CLAUDE.md agrees with this file', () => {
  it('declares the same set, so the doc and the test cannot diverge', () => {
    // CLAUDE.md is where a human reads this; the test is where it is enforced. Divergence between
    // them is how the list drifted in the first place.
    const claude = readFileSync(join(here, '..', '..', 'CLAUDE.md'), 'utf8')
    const block = /\*\*Currently retired or unmounted[^:]*\*\*[^:]*:([\s\S]*?)\n\n/.exec(claude)
    expect(block, 'CLAUDE.md no longer has the unmounted-components block this test reads').toBeTruthy()
    const declared = [...block[1].matchAll(/`([A-Za-z][\w]*)`/g)].map((m) => m[1]).sort()
    expect(declared).toEqual([...EXPECTED_UNMOUNTED].sort())
  })
})
