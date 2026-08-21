import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Two items I had listed as "remaining board polish" — both wrong, checked rather than built.
//
// UPPERCASE FIELD LABELS. The rule builder's NAME / ACTION / FOLDER PATH STARTS WITH / LAST
// MODIFIED BEFORE already render uppercase — `fieldLabel` carries `textTransform: 'uppercase'`.
// The board match is real; my LOE list had it wrong because I compared the board screenshot
// against the raw SOURCE STRING ("Folder path starts with"), never against the rendered style.
// Grepping source text for a board's rendered caps is exactly the failure this file exists to
// catch before it becomes a wasted rebuild.
//
// "SWITCH SOURCE" is not a gap — it is a RECORDED REMOVAL, and the record is in the file this
// test reads. ScanReviewModal.jsx says so about its own header:
//
//     "Sources included" was a heading, a rule and a status dot spent on a single fact, above
//     the decision the user came for; the fact survives, the chrome does not.
//
// Adding the control back in would reverse that decision silently — the same failure class
// CLAUDE.md's retired-features section warns about, for a design simplification instead of a
// removed feature. This is pinned so a future pass (mine or anyone's) checks the reasoning
// before reaching for the board screenshot as the whole story.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('the rule builder labels are already board-matched', () => {
  it('fieldLabel renders uppercase', () => {
    const s = read('DispositionRules.jsx')
    const m = /const fieldLabel = \{([^}]*)\}/.exec(s)
    expect(m, 'fieldLabel style block moved or was renamed').toBeTruthy()
    expect(m[1]).toMatch(/textTransform:\s*'uppercase'/)
  })

  it('the label text itself matches the board, case aside', () => {
    // The board reads FOLDER PATH STARTS WITH / LAST MODIFIED BEFORE — the source strings are
    // lowercase sentence case, which is correct: CSS does the capitalising, so the source stays
    // readable and a screen reader (which does not re-case AT announcement from text-transform
    // the way a sighted reader sees it) still gets a normal sentence.
    const rules = read('lifecycleRules.js')
    expect(rules).toContain("label: 'Folder path starts with'")
    expect(rules).toContain("label: 'Last modified before'")
  })
})

describe('"Switch source" is absent on purpose', () => {
  it('ScanReviewModal records why, not just that', () => {
    const s = read('ScanReviewModal.jsx')
    expect(s).not.toMatch(/Switch source/)
    // The reasoning has to still be there — an absence with no explanation reads as an omission,
    // which is the exact ambiguity that put this on my list as "remaining" in the first place.
    expect(s).toMatch(/the fact survives, the chrome does not/)
  })
})
