/**
 * The SPA's assessment scope (activeScope.js's module-level SCOPE_SCS/ACTIVE_SCOPE_PRESET/etc.,
 * read by Overview, ScopeBanner, AssessmentScopeCard, AssessRunner, CoverageScorecard,
 * ScanScopeChip, AccessibilityStatus, Transparency, and FileDrawer) was refreshed from the
 * server exactly ONCE, at boot (App.jsx's `getConfig().then(applyScopeConfig)` effect).
 *
 * AssessSetup already calls `onSaved?.(scope)` after every successful PUT /settings that writes
 * a new `scan_scope` — the same setting /config's `_active_scope_info()` reads — but App.jsx
 * never passed an `onSaved` prop. So an operator who edited and saved a new assessment scope
 * kept seeing the PREVIOUS scope's "N of 20 in scope" arithmetic everywhere until a full page
 * reload: the exact bug class applyScopeConfig itself was built to fix (see activeScope.js's own
 * doc comment — "two sources of truth for one question, and the wrong one was the one the
 * customer could see"), just recurring after a live edit instead of at build time.
 *
 * Source-level pin, matching this repo's convention for "two things must stay wired together"
 * bugs (see sessionExpiry.test.js, rescanResetsState.test.js) — the wiring itself, not a full
 * AssessSetup mount, is what broke.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
// Executable lines only: a comment describing the deleted bug is not the bug.
const code = (f) => readFileSync(join(here, f), 'utf8').split('\n')
  .filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*') })
  .join('\n')

describe('the assessment scope is re-adopted after a save, not just at boot', () => {
  const app = code('App.jsx')

  it('AssessSetup is wired to a real onSaved handler, not left unset', () => {
    // An omitted onSaved is exactly how this shipped: AssessSetup already calls
    // onSaved?.(scope) on every successful save, and nothing consumed it.
    expect(app).toMatch(/<AssessSetup[\s\S]{0,300}onSaved=\{/)
  })

  it('the boot effect and the save handler share one adopt function, not two copies', () => {
    expect(app).toMatch(/const adoptScopeConfig = \(c\) => \{ if \(applyScopeConfig\(c\)\) setScopeTick/)
    // Both call sites route through it — a hand-rolled second copy in the onSaved prop would
    // silently drift from the boot effect's own handling (e.g. forgetting the scopeTick bump).
    expect((app.match(/adoptScopeConfig/g) || []).length).toBeGreaterThanOrEqual(3) // def + boot + onSaved
  })

  it('the save handler re-fetches /config before adopting — it cannot reuse a stale response', () => {
    expect(app).toMatch(/onSaved=\{\(\) => \{ getConfig\(\)\.then\(adoptScopeConfig\)\.catch\(\(\) => \{\}\) \}\}/)
  })
})
