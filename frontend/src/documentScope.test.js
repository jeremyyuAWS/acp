import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { hasDocumentSelection, documentSelection, documentScopeSentence, ineligibleReason }
  from './remediableScope.js'

// The product has TWO filters, and only one of them carried.
//
// `scan_scope` (criterion × format) is gated once in the backend's _rule_outcome, so assess,
// remediate and publish inherit it with no plumbing. The per-document selection is the other
// one: marking a single document in scope excludes every unmarked document from remediation.
//
// That second filter lived entirely inside Remediate. Its predicate was written out by hand in
// three places there, and Publish — the screen that produces the compliance record — had no idea
// it existed. So an operator could mark 2 of 258 documents, remediate those two, and read a
// conformance report whose every number is about 258. "Certified" against an unstated document
// scope is exactly as unverifiable as certified against an unstated criterion scope, which is
// the defect ScopeBanner was built for.

const HERE = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(HERE, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

const FILES = Array.from({ length: 258 }, (_, i) => ({ file: `doc${i}.docx` }))

describe('the per-document filter, as data', () => {
  it('is absent until something is actually marked in scope', () => {
    expect(documentScopeSentence(documentSelection(FILES, {}))).toBeNull()
    // na/defer are different decisions and must not switch the restriction on.
    expect(documentScopeSentence(documentSelection(FILES,
      { 'doc1.docx': 'na', 'doc2.docx': 'defer' }))).toBeNull()
  })

  it('names both sides of the 2-of-258 case', () => {
    // The number that was missing. "2 in scope" alone reads as a starting state; the 256 is the
    // fact the reader needs.
    const s = documentScopeSentence(documentSelection(FILES,
      { 'doc0.docx': 'inscope', 'doc1.docx': 'inscope' }))
    expect(s).toBe('2 of 258 documents marked in scope — the other 256 are not remediated.')
  })

  it('handles a selection that matches nothing in this scan', () => {
    // Marks left over from a different document set. The gate is ON — every file is excluded —
    // while a count taken over the current files alone would say "0 marked" and render nothing,
    // which is silence in exactly the case that remediates nothing.
    const s = documentScopeSentence(documentSelection(FILES, { 'gone.docx': 'inscope' }))
    expect(s).toMatch(/none of these 258 documents are marked in scope/)
    expect(s).toMatch(/nothing here will be remediated/)
  })

  it('asks the same question the eligibility gate asks', () => {
    // hasDocumentSelection is the exact predicate ineligibleReason's `hasInscopeSelections`
    // branch keys on. Derived on both sides so the statement cannot claim "no restriction"
    // while the gate is dropping every file.
    const triage = { 'gone.docx': 'inscope' }
    expect(hasDocumentSelection(triage)).toBe(true)
    const opts = { triage, hasInscopeSelections: hasDocumentSelection(triage), remActions: ['auto'] }
    const f = { file: 'doc0.docx', rec: { action: 'auto' } }
    expect(ineligibleReason(f, opts)).toBe('outOfScope')
  })
})

describe('both downstream screens state it', () => {
  it('Publish receives triage and renders the sentence', () => {
    // The whole point. Remediate always honoured this filter; Publish never knew of it.
    const s = code('Publish.jsx')
    expect(s).toMatch(/triage = \{\}/)
    expect(s).toMatch(/docScope=\{documentScopeSentence\(documentSelection\(files, triage\)\)\}/)
    expect(s).toContain("from './remediableScope.js'")
  })

  it('App passes triage down to Publish', () => {
    // Without this the prop defaults to {} and the banner is silently always absent — a fix
    // that looks complete in Publish.jsx and does nothing.
    expect(code('App.jsx')).toMatch(/<Publish [^>]*triage=\{triage\}/)
  })

  it('Remediate renders the identical expression', () => {
    // Same call, same helper, so the two screens cannot word or count the same fact differently.
    expect(code('Remediate.jsx'))
      .toMatch(/docScope=\{documentScopeSentence\(documentSelection\(files, triage\)\)\}/)
  })

  it('ScopeBanner marks the run narrow whenever a document scope is present', () => {
    // A per-document restriction is narrow by definition — there is no wide version of it.
    const s = code('ScopeBanner.jsx')
    expect(s).toMatch(/const narrow = isNarrowScope\(run\?\.scope\) \|\| !!docScope/)
    expect(s).toMatch(/\{docScope \? <> · ⚠ \{docScope\}<\/> : null\}/)
  })

  it('keeps the ⚠ on the FILE scope tied to the file scope', () => {
    // `narrow` now also turns true for a document restriction. If the file-scope clause reused
    // it, a whole-Drive scan with a document selection would render "⚠ across your whole Google
    // Drive" — a warning attached to the one boundary that is not narrow.
    expect(code('ScopeBanner.jsx')).toMatch(/\{isNarrowScope\(run\?\.scope\) \? '⚠ ' : ''\}\{fileScope\}/)
  })
})

describe('one definition, not four', () => {
  it('nothing re-derives the predicate by hand', () => {
    // It was written out three times in Remediate. A fourth copy in Publish would have been the
    // defect this change is about, one screen further along.
    for (const f of ['Remediate.jsx', 'Publish.jsx', 'ScopeBanner.jsx']) {
      expect(code(f), `${f} re-derives the in-scope predicate`)
        .not.toMatch(/Object\.values\(triage\)\.some/)
    }
  })

  it('ScopeBanner takes a sentence, not triage', () => {
    // It knows about scopes, not about triage semantics. Passing triage would put a third
    // interpretation of the same data in a third file.
    const s = code('ScopeBanner.jsx')
    expect(s).toMatch(/docScope = null/)
    expect(s).not.toMatch(/triage/)
  })
})
