/**
 * A clean bill of health, computed from documents nobody read.
 *
 * From one production screenshot on 2026-08-19, over a 22-document estate where NOTHING had been
 * analysed (the SharePoint download bug, #481):
 *
 *   Remediate hero      "Business risk: Internal content only · overall risk LOW"
 *   Drawer status hero  "Ready after 8 reviews · Est. review ~6 min"
 *
 * The risk line reaches LOW when `criticalOpen === 0`, and zero findings is exactly what an
 * unanalysed estate yields. Absence of evidence, rendered as evidence of absence — and "overall
 * risk LOW" is the sentence that ends up in a status report.
 *
 * The cases below pin the distinction that makes this fixable rather than merely softer:
 *
 *   · a REASSURING verdict is withheld when documents went unassessed
 *   · an ALARMING one is not — findings that were genuinely found are still true, and hiding them
 *     to avoid a false calm would trade one wrong answer for a worse one
 *   · "opened and failed" and "never opened" both count, because for "can this verdict be
 *     trusted?" they are the same answer
 *   · a fully-assessed estate is unaffected, so the caveat cannot become the thing that always
 *     fires and stops being read
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  unassessedCount, canClaimLowRisk, unassessedRiskText, showsAssessmentHero,
} from './riskOverUnassessed.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const failed = (file) => ({ file, status: 'error', score: null, issues: [] })
const neverLooked = (file) => ({ file, score: null, issues: [] })          // ADR 0020 Discover row
const clean = (file) => ({ file, status: 'analysed', score: 100, compliant: true, issues: [] })
const withCritical = (file) => ({ file, status: 'analysed', score: 40, issues: [{ severity: 'CRITICAL' }] })

describe('counting what produced no assessment', () => {
  it('counts documents that were opened and failed', () => {
    expect(unassessedCount([failed('a.docx'), clean('b.docx')])).toBe(1)
  })

  it('counts documents nobody opened', () => {
    // An ADR 0020 Discover-only row has no status and no score. It contributed nothing to the
    // findings count either, so it undermines a reassuring verdict exactly as much as a failure.
    expect(unassessedCount([neverLooked('a.docx'), clean('b.docx')])).toBe(1)
  })

  it('counts an assessed document as assessed, findings or not', () => {
    expect(unassessedCount([clean('a.docx'), withCritical('b.docx')])).toBe(0)
  })

  it('survives an empty or malformed list rather than throwing', () => {
    for (const bad of [[], null, undefined, [null]]) expect(unassessedCount(bad)).toBe(0)
  })
})

describe('the low-risk verdict', () => {
  it('is allowed when every document was assessed', () => {
    // The caveat must not fire on a healthy estate, or it becomes the warning nobody reads.
    expect(canClaimLowRisk([clean('a.docx'), clean('b.docx')])).toBe(true)
  })

  it('is WITHHELD when a document produced no assessment', () => {
    // THE case: 22 unanalysable documents, zero findings, "overall risk LOW".
    expect(canClaimLowRisk([failed('a.docx'), clean('b.docx')]), 'LOW risk claimed over an unassessed document')
      .toBe(false)
  })

  it('is withheld for never-opened documents too', () => {
    expect(canClaimLowRisk([neverLooked('a.docx')])).toBe(false)
  })

  it('names the number rather than gesturing at uncertainty', () => {
    const t = unassessedRiskText([failed('a.docx'), failed('b.docx'), clean('c.docx')])
    expect(t).toMatch(/2 documents produced no assessment/)
    expect(t).toMatch(/no basis for a risk verdict/)
    expect(t, 'a withheld verdict still said LOW').not.toMatch(/LOW/i)
  })

  it('pluralises, because "1 documents" undermines the warning it carries', () => {
    expect(unassessedRiskText([failed('a.docx')])).toMatch(/1 document produced/)
  })
})

describe('the drawer’s coverage + estimate hero', () => {
  it('renders for a document that was actually assessed', () => {
    expect(showsAssessmentHero(clean('a.docx'))).toBe(true)
    expect(showsAssessmentHero(withCritical('a.docx'))).toBe(true)
  })

  it('does NOT render for a document that could not be processed', () => {
    // "Ready after 8 reviews · Est. review ~6 min" over a file nobody opened — a time estimate for
    // reviewing findings that do not exist.
    expect(showsAssessmentHero(failed('a.docx')), 'a coverage verdict for an unreadable document')
      .toBe(false)
  })

  it('does not render for a document nobody has opened yet', () => {
    expect(showsAssessmentHero(neverLooked('a.docx'))).toBe(false)
  })

  it('is false rather than throwing when there is no file', () => {
    expect(showsAssessmentHero(null)).toBe(false)
  })
})


describe('the surfaces actually consult these', () => {
  // ADDED AFTER A MUTATION SURVIVED. Deleting the gate from Remediate.jsx left the whole suite
  // green — 2342 tests — because the cases above only prove the predicate is right, never that
  // anything calls it. Remediate mounts a page's worth of dependencies, which is why its existing
  // tests (remediateNavigation, remediateCollapse) are source-level too; the drawer's half is
  // asserted at the DOM in drawerErrorReason.test.jsx, where mounting is already paid for.
  it('Remediate gates the low-risk verdict', () => {
    const r = read('Remediate.jsx')
    expect(r, 'the risk gate was removed from Remediate.jsx').toMatch(/canClaimLowRisk\(files\)/)
    expect(r).toMatch(/unassessedRiskText\(files\)/)
  })

  it('the drawer gates its coverage hero', () => {
    expect(read('FileDrawer.jsx'), 'the assessment hero is no longer gated')
      .toMatch(/showsAssessmentHero\(file\)/)
  })
})
