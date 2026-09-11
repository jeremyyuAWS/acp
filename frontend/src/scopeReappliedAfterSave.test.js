// The saved per-scan scope must refresh the shared UI arithmetic without re-reading global defaults.
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

  it('adopts the saved scan scope rather than global defaults', () => {
    expect(app).toContain("onSaved={(scope) => adoptScopeConfig({ scope: { name: 'Selected criteria', criteria: scope } })}")
  })
})
