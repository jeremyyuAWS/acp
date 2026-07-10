// Two surfaces show the reviewer the images, and they must not both show them.
//
// `evidence` (hitl_queue.evidence) is the pictures with no values — populated whether or not
// the AI ran, so a reviewer can see what they are describing and pick which one "Draft with AI"
// looks at. `proposals` is the pictures WITH a drafted value each, and ProposalEditors renders
// one editor per image.
//
// A row can carry both. Rendering the strip on top of the editors would show every picture
// twice and leave the strip's picker with nothing to disambiguate — the drafts already name
// their own image. So the strip yields to the editors.
import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import EvidenceCard from './EvidenceCard.jsx'

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const base = {
  id: 1, scan_id: 's1', file: 'deck.pptx', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 2,
}
const EVIDENCE = [
  { locator: 'ppt/slides/slide1.xml#Picture 1', thumb: PNG },
  { locator: 'ppt/slides/slide2.xml#Picture 2', thumb: PNG },
]
const PROPOSALS = [
  { locator: 'ppt/slides/slide1.xml#Picture 1', before: '(no alt text)',
    proposed_value: 'A clinician at a desk.', rationale: 'vision model' },
  { locator: 'ppt/slides/slide2.xml#Picture 2', before: '(no alt text)',
    proposed_value: 'A parent signing a form.', rationale: 'vision model' },
]

const markup = (item) => renderToStaticMarkup(createElement(EvidenceCard, { item, onAct: () => {} }))

describe('evidence strip vs per-proposal editors', () => {
  it('no drafts → the strip, so the reviewer can see and pick an image', () => {
    const html = markup({ ...base, evidence: EVIDENCE })
    expect(html).toContain('evcard-evidence-strip')
    expect(html).toContain('images need a description')
    expect(html).not.toContain('evcard-multi-row')
  })

  it('drafts → the editors, each image beside its own value', () => {
    const html = markup({ ...base, proposals: PROPOSALS })
    expect(html).toContain('evcard-multi-row')
    expect(html).toContain('A clinician at a desk.')
    expect(html).toContain('A parent signing a form.')
    expect(html).not.toContain('evcard-evidence-strip')
  })

  it('BOTH → the editors only; the strip would duplicate every picture', () => {
    const html = markup({ ...base, evidence: EVIDENCE, proposals: PROPOSALS })
    expect(html).toContain('evcard-multi-row')
    expect(html).not.toContain('evcard-evidence-strip')
    // each image appears once, in its own editor row
    expect(html.split('evcard-multi-row').length - 1).toBe(2)
  })

  it('neither → no image surface at all, rather than an empty one', () => {
    const html = markup({ ...base })
    expect(html).not.toContain('evcard-evidence-strip')
    expect(html).not.toContain('evcard-multi-row')
  })
})
