// "Why this is safe to approve" is the AFFIRMATIVE counterpart to whyHumanReview. It must only
// speak when the positive facts are genuinely true, and must stay SILENT when the honest answer is
// "this still needs judgement" — otherwise it paints a false green over a finding a human must
// still author or word-check.
import { describe, it, expect } from 'vitest'
import { whySafeToApprove, buildEvidenceCard } from './reviewCard.js'

describe('whySafeToApprove — affirmative only when the evidence is real', () => {
  it('speaks for a re-scan-passed proposal — the strongest positive signal', () => {
    const card = buildEvidenceCard({
      rule_id: '1.1.1', file: 'deck.pptx', validated: true,
      proposals: [{ locator: 'ppt/slides/slide1.xml#Picture 1', before: '(no alt text)',
                    proposed_value: 'A clinician at a desk.',
                    rationale: 'text read from the image (OCR)', grounded: true }],
    })
    const s = whySafeToApprove(card)
    expect(s).not.toBeNull()
    expect(s.points.join(' ')).toMatch(/re-scan already confirmed/i)
  })

  it('speaks for a deterministic contrast fix — sign-off IS the certification', () => {
    const card = buildEvidenceCard({ rule_id: '1.4.3', file: 'report.docx', proposals: null })
    const s = whySafeToApprove(card)
    expect(s).not.toBeNull()
    expect(s.points.join(' ')).toMatch(/deterministic check/i)
  })

  it('stays SILENT for a visual-only 1.1.1 draft — no text anchor, wording needs a human', () => {
    // grounded:false → grounding tone 'warn' → the honest gate suppresses the green box.
    const card = buildEvidenceCard({
      rule_id: '1.1.1', file: 'deck.pptx',
      proposals: [{ locator: 'ppt/slides/slide1.xml#Picture 2', before: '(no alt text)',
                    proposed_value: 'A colourful abstract shape.',
                    rationale: 'vision description only — no text in the image', grounded: false }],
    })
    expect(whySafeToApprove(card)).toBeNull()
  })

  it('stays SILENT for a manual-authoring finding — there is no drafted fix to call safe', () => {
    // 1.2.2 captions: no proposal, reviewRequirement → manual_remediation (tone warn).
    const card = buildEvidenceCard({ rule_id: '1.2.2', file: 'training.pptx', proposals: null })
    expect(whySafeToApprove(card)).toBeNull()
  })
})
