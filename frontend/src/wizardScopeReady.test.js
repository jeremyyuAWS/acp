/**
 * "Specific folders", nothing selected, Continue enabled — and the run covers everything.
 *
 * From the New-scan wizard on 2026-08-20, all on screen simultaneously:
 *   · "Specific folders" selected
 *   · "Nothing selected — this scan covers all of OneDrive."
 *   · footer "Entire source · 4 formats · Core 17"
 *   · Continue enabled
 *
 * The empty list genuinely does scan everything — that is the correct reading on a source card,
 * where no selection is the connection's default. The wizard borrowed it for a mode whose whole
 * meaning is a restriction. The reassuring interpretation of missing input, again (#479, #483,
 * #491) — except this one spends a full estate scan.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  scopeIncomplete, scopeFooterPart, blockedReason, INCOMPLETE_LINE,
} from './wizardScopeReady.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('an unfinished narrowing', () => {
  it('is incomplete when "Specific folders" is chosen and none are', () => {
    expect(scopeIncomplete('some', [])).toBe(true)
  })

  it('is NOT incomplete once a folder is chosen', () => {
    expect(scopeIncomplete('some', [{ id: 'd/1' }])).toBe(false)
  })

  it('is not incomplete when the user never claimed to narrow', () => {
    // "Entire source" with an empty list is the honest, intended state — the caveat must not
    // fire there or it becomes the warning nobody reads.
    expect(scopeIncomplete('all', [])).toBe(false)
  })

  it('counts exclusions-only as still incomplete', () => {
    // "Exclude Archive, include nothing" names no scope to subtract from, so it falls through to
    // the whole source exactly as an empty list does.
    expect(scopeIncomplete('some', [])).toBe(true)
  })

  it('survives a missing list rather than throwing', () => {
    for (const bad of [null, undefined]) expect(scopeIncomplete('some', bad)).toBe(true)
  })
})

describe('the footer summary', () => {
  it('no longer says "Entire source" while the user is narrowing', () => {
    // THE contradiction: this line sat two inches below a selected "Specific folders".
    expect(scopeFooterPart('some', [], []), 'the footer still claims the entire source')
      .not.toMatch(/Entire source/)
    expect(scopeFooterPart('some', [], [])).toBe('No folders selected')
  })

  it('still says "Entire source" when that is what was chosen', () => {
    expect(scopeFooterPart('all', [], [])).toBe('Entire source')
  })

  it('counts folders and exclusions when there are some', () => {
    expect(scopeFooterPart('some', [{ id: 'a' }], [])).toBe('1 folder')
    expect(scopeFooterPart('some', [{ id: 'a' }, { id: 'b' }], [{ id: 'c' }]))
      .toBe('2 folders · 1 excluded')
  })
})

describe('the primary action', () => {
  it('is blocked, with a reason naming the fix', () => {
    expect(blockedReason('some', [])).toBe(INCOMPLETE_LINE)
    expect(INCOMPLETE_LINE).toMatch(/at least one folder/)
  })

  it('is available in every legitimate state', () => {
    expect(blockedReason('all', [])).toBeNull()
    expect(blockedReason('some', [{ id: 'a' }])).toBeNull()
  })
})

describe('the surfaces actually consult this', () => {
  // The predicate being right proves nothing about anything calling it — the lesson from #491,
  // where deleting the gate left 2342 tests green. The DOM half is in wizardEmptyScope.test.jsx;
  // these pin the wiring that a DOM test would not distinguish from a coincidence.
  it('the wizard blocks its footer button on the reason', () => {
    const w = read('ScanScopeWizard.jsx')
    // Through `stepBlockedReason`, which is a thin wrapper over `blockedReason` scoped to step 1.
    // The scoping matters and is the reason this assertion moved: left unscoped, the reason would
    // also disable "Run discovery" on the review step for a scope the user already fixed and
    // walked past, which reads as the wizard refusing a valid run.
    expect(w, 'the block was removed from the wizard').toMatch(/stepBlockedReason\(/)
    expect(read('discoveryWizardSteps.js'), 'the step gate stopped consulting the real reason')
      .toMatch(/blockedReason\(scopeMode, folders\)/)
    expect(w, 'the forward control no longer honours the block').toMatch(/disabled=\{busy \|\| !!blocked\}/)
  })

  it('the wizard footer reads through the mode-aware summary', () => {
    expect(read('ScanScopeWizard.jsx')).toMatch(/scopeFooterPart\(scopeMode, folders, excluded\)/)
  })

  it('the wizard tells the picker it is narrowing', () => {
    expect(read('ScanScopeWizard.jsx'), 'the picker will report the source-card meaning')
      .toMatch(/requireSelection/)
  })

  it('the picker honours requireSelection instead of claiming everything', () => {
    const p = read('FolderPicker.jsx')
    expect(p).toMatch(/requireSelection \? \(/)
    expect(p).toMatch(/INCOMPLETE_LINE/)
    // And the source-card meaning must survive for the caller that legitimately needs it.
    expect(p, 'the source card lost its "scans everything" line').toMatch(/source scans/)
  })
})
