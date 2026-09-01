import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { ineligibleReason, remediableFiles, emptyScopeReason, scopeSummary, SCOPE_REASONS } from './remediableScope.js'

const here = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(here, f), 'utf8')
  .split('\n').filter((l) => { const t = l.trim(); return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('{/*') })
  .join('\n')

// Two defects, both of which made a click look like it worked when it did nothing:
//   1. The hero CTA offered "Run Remediation" only when `!remStarted`, and remStarted is true
//      the moment a reviewer approves/rejects/defers ANYTHING. Clearing the review queue — the
//      step that unblocks remediation — was precisely what removed the button that runs it.
//   2. "Remediate all" with an empty scope posted anyway and reported "no eligible files with
//      issues", which is true, useless, and looks identical to a dead button.

const OPTS = { triage: {}, hasInscopeSelections: false, remActions: ['fix', 'auto'] }
const ok = (file) => ({ file, rec: { action: 'fix' } })

describe('eligibility: one rule set, applied in order', () => {
  it('an eligible document has no reason', () => {
    expect(ineligibleReason(ok('a.pptx'), OPTS)).toBeNull()
  })

  it('an already-remediated document is excluded, by either marker', () => {
    expect(ineligibleReason({ ...ok('a'), remediated_at: '2026-07-10' }, OPTS)).toBe('remediated')
    expect(ineligibleReason({ ...ok('a'), drive_write_url: 'https://drive/x' }, OPTS)).toBe('remediated')
  })

  it('a document with no auto-fixable recommendation is excluded', () => {
    expect(ineligibleReason({ file: 'a' }, OPTS)).toBe('noAutoFix')
    expect(ineligibleReason({ file: 'a', rec: { action: 'review' } }, OPTS)).toBe('noAutoFix')
  })

  it('triage flags exclude', () => {
    expect(ineligibleReason(ok('a'), { ...OPTS, triage: { a: 'na' } })).toBe('triaged')
    expect(ineligibleReason(ok('a'), { ...OPTS, triage: { a: 'defer' } })).toBe('triaged')
  })

  it('an in-scope selection excludes everything outside it', () => {
    const opts = { ...OPTS, hasInscopeSelections: true, triage: { a: 'inscope' } }
    expect(ineligibleReason(ok('a'), opts)).toBeNull()
    expect(ineligibleReason(ok('b'), opts)).toBe('outOfScope')
  })

  it('the FIRST rule wins, so a document is counted once', () => {
    // already-remediated AND deferred -> counted under 'remediated' only.
    const f = { ...ok('a'), remediated_at: 'x' }
    expect(ineligibleReason(f, { ...OPTS, triage: { a: 'defer' } })).toBe('remediated')
  })

  it('remediableFiles is exactly the complement', () => {
    const files = [ok('a'), { ...ok('b'), remediated_at: 'x' }, { file: 'c' }]
    expect(remediableFiles(files, OPTS).map((f) => f.file)).toEqual(['a'])
  })
})

describe('when nothing is eligible, say why', () => {
  it('names the counts and never exceeds the document count', () => {
    const files = [{ ...ok('a'), remediated_at: 'x' }, { ...ok('b'), drive_write_url: 'u' }, { file: 'c' }]
    const msg = emptyScopeReason(files, OPTS)
    expect(msg).toMatch(/of 3 documents/)
    expect(msg).toMatch(/2 already remediated/)
    expect(msg).toMatch(/1 with no automatic fix/)
    const nums = [...msg.matchAll(/(\d+) (?:already|with|marked|outside)/g)].map((m) => +m[1])
    expect(nums.reduce((a, b) => a + b, 0)).toBeLessThanOrEqual(files.length)
  })

  it('suggests a next step that matches the reason', () => {
    const remediated = [{ ...ok('a'), remediated_at: 'x' }]
    expect(emptyScopeReason(remediated, OPTS)).toMatch(/Re-scan/)
    const deferred = [ok('a')]
    expect(emptyScopeReason(deferred, { ...OPTS, triage: { a: 'defer' } })).toMatch(/triage flag/)
  })

  it('handles an empty scan without inventing documents', () => {
    expect(emptyScopeReason([], OPTS)).toMatch(/no documents/)
    expect(emptyScopeReason(null, OPTS)).toMatch(/no documents/)
  })

  it('every bucket has a phrase', () => {
    for (const k of ['remediated', 'noAutoFix', 'triaged', 'outOfScope']) {
      expect(SCOPE_REASONS[k], k).toBeTruthy()
    }
  })
})

describe('the Run Remediation button is reachable after a review', () => {
  const rem = code('Remediate.jsx')

  it('the CTA is no longer gated on remStarted', () => {
    // The exact defect: `(!remStarted && remediable.length > 0)`
    expect(rem).not.toMatch(/!remStarted && remediable\.length > 0/)
    // The 2026-09-01 redesign renamed the action and narrowed its scope to the DETERMINISTIC
    // partition (`autoBatch`) rather than every remediable file, so the button can never be the
    // thing that approves an AI draft. The invariant this test exists for — the offer does not
    // disappear once a review has happened — is unchanged.
    expect(rem).toMatch(/autoBatch && autoBatch\.count > 0/)
    expect(rem).toMatch(/label: `Apply \$\{autoBatch\.count\} automatic fix/)
  })

  it('but a run in flight shows as running rather than re-offering the button', () => {
    expect(rem).toMatch(/const remRunning = remBusy \|\| \(remProg != null && remProg\.done < remProg\.total\)/)
    expect(rem).toMatch(/remRunning \? \{ label: 'Applying fixes…', disabled: true \}/)
  })

  it('remStarted survives where it is still meaningful', () => {
    // It still drives the progress rail and the "all caught up" state; don't leave it dead.
    expect(rem).toMatch(/const remStarted = /)
    expect((rem.match(/remStarted/g) || []).length).toBeGreaterThan(2)
  })
})

describe('an empty scope explains itself before the round trip', () => {
  const rem = code('Remediate.jsx')

  it('runServerRemediation refuses early and says why', () => {
    expect(rem).toMatch(/if \(scope\.length === 0\) \{/)
    expect(rem).toMatch(/setRemMsg\(emptyScopeReason\(files, scopeOpts\)\)/)
  })

  it('the set and the explanation share one eligibility test', () => {
    expect(rem).toMatch(/remediableFiles\(files, scopeOpts\)/)
    expect(rem).not.toMatch(/if \(f\.remediated_at \|\| f\.drive_write_url\) return false/)
  })

  it('a stale scope gets a different sentence than an empty one', () => {
    expect(rem).toMatch(/the server found no eligible work in the/)
    expect(rem).toMatch(/re-scan to refresh/)
  })

  it('the refusal is not styled as muted chatter', () => {
    expect(rem).toMatch(/remMsg\.startsWith\('Nothing to remediate'\) \? '#8A4B00'/)
  })
})

// ── the scope panel must say what it is skipping ──────────────────────────────────────
//
// On 2026-07-29 the deployed Remediation panel read "Documents · 258" with the badges
// "2 in scope · 0 N/A · 0 deferred", all 258 rows listed, and 256 of them showing untouched
// ✓/N/A/⏸ buttons. Both readings a user could take from that were wrong in the same direction:
// the badges count only EXPLICIT decisions, AND `ineligibleReason` drops every unmarked file
// once any file is marked — so 256 documents were excluded from the run with nothing saying so.
describe('scopeSummary: the number the panel was missing', () => {
  const files = (n) => Array.from({ length: n }, (_, i) => ok(`f${i}.pptx`))

  it('with no selection, every eligible document is in and nothing is excluded by scope', () => {
    const s = scopeSummary(files(258), OPTS)
    expect(s.total).toBe(258)
    expect(s.eligible).toBe(258)
    expect(s.restrictedBySelection).toBe(false)
    expect(s.excluded.outOfScope).toBeUndefined()
  })

  it('marking 2 of 258 excludes the other 256 — the case the panel hid', () => {
    const opts = { ...OPTS, hasInscopeSelections: true, triage: { 'f0.pptx': 'inscope', 'f1.pptx': 'inscope' } }
    const s = scopeSummary(files(258), opts)
    expect(s.eligible).toBe(2)
    expect(s.excluded.outOfScope).toBe(256)
    expect(s.restrictedBySelection).toBe(true)
  })

  it('counts each document once, under the FIRST rule that excluded it', () => {
    // already-remediated AND unmarked: 'remediated' wins, so the two buckets cannot double-count.
    const opts = { ...OPTS, hasInscopeSelections: true, triage: { 'a': 'inscope' } }
    const s = scopeSummary([ok('a'), { ...ok('b'), remediated_at: 'x' }, ok('c')], opts)
    expect(s.excluded.remediated).toBe(1)
    expect(s.excluded.outOfScope).toBe(1)
    expect(s.eligible + Object.values(s.excluded).reduce((a, b) => a + b, 0)).toBe(s.total)
  })

  it('agrees with remediableFiles exactly — the panel cannot promise what the button will not do', () => {
    const opts = { ...OPTS, hasInscopeSelections: true, triage: { 'f3.pptx': 'inscope' } }
    expect(scopeSummary(files(10), opts).eligible).toBe(remediableFiles(files(10), opts).length)
  })

  it('a triage flag is not reported as a scope exclusion', () => {
    const opts = { ...OPTS, triage: { 'f0.pptx': 'na', 'f1.pptx': 'defer' } }
    const s = scopeSummary(files(5), opts)
    expect(s.excluded.triaged).toBe(2)
    expect(s.restrictedBySelection).toBe(false)
  })
})

describe('the panel renders the exclusion, rather than leaving it to be inferred', () => {
  const rem = code('Remediate.jsx')

  it('derives the summary from the same opts the button uses', () => {
    expect(rem).toMatch(/scopeSummary\(files, scopeOpts\)/)
  })

  it('shows an excluded chip in the badge row when a selection is restricting the run', () => {
    expect(rem).toMatch(/scopeInfo\.restrictedBySelection/)
    expect(rem).toMatch(/excluded — not marked/)
  })

  it('marks each excluded row, so it cannot read as merely undecided', () => {
    expect(rem).toMatch(/const outOfScope = ineligibleReason\(f, scopeOpts\) === 'outOfScope'/)
    expect(rem).toMatch(/outOfScope \? 'docrow outofscope' : 'docrow'/)
    expect(rem).toMatch(/outOfScope && <span className="docexcl">/)
  })

  it('keys the row marker on the SCOPE reason, not merely on a selection existing', () => {
    // A document with no automatic fix is already ineligible for its own reason, and marking it
    // ✓ would not change that — labelling it "excluded by your selection" would be false
    // precision. Rendering showed 173 marked rows against a badge of 117 before this.
    expect(rem).not.toMatch(/hasInscopeSelections && <span className="trstatchip out"/)
  })

  it('no longer claims only that "Only in-scope files are remediated"', () => {
    // The old sentence was true and uninformative — it never said unset means excluded.
    expect(rem).not.toMatch(/Only in-scope files are remediated/)
    expect(rem).toMatch(/Marking even one ✓ restricts the run/)
  })
})
