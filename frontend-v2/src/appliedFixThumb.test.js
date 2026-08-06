import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { appliedFixAlt } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const code = (f) => readFileSync(join(here, f), 'utf8')
  .split('\n').filter((l) => !l.trim().startsWith('//') && !l.trim().startsWith('{/*')).join('\n')

// A PDF figure's alt text is written from a render of its PAGE; an Office image's from the
// embedded image. The receipt in "Recent AI fixes" shows that same picture, so its own alt text
// must say which. Getting this wrong is the exact defect this product exists to detect.

describe('the applied-fix receipt describes what it actually shows', () => {
  it('calls a PDF thumbnail a rendered page', () => {
    const alt = appliedFixAlt('policy.pdf')
    expect(alt).toMatch(/Rendered page of policy\.pdf/)
    expect(alt).not.toMatch(/^Image in/)
  })

  it('calls an Office thumbnail an image', () => {
    expect(appliedFixAlt('deck.pptx')).toMatch(/^Image in deck\.pptx/)
    expect(appliedFixAlt('policy.docx')).toMatch(/^Image in policy\.docx/)
    expect(appliedFixAlt('sheet.xlsx')).toMatch(/^Image in sheet\.xlsx/)
  })

  it('is case-insensitive about the extension', () => {
    expect(appliedFixAlt('POLICY.PDF')).toMatch(/Rendered page/)
  })

  it('never renders "undefined" or an empty alt', () => {
    for (const f of [undefined, null, '']) {
      const alt = appliedFixAlt(f)
      expect(alt).not.toMatch(/undefined|null/)
      expect(alt.length).toBeGreaterThan(0)
    }
  })
})

describe('every thumbnail goes through the data-URL guard', () => {
  const remediate = code('Remediate.jsx')

  it('Recent AI fixes renders ProposalThumb, not a raw <img src={a.thumb}>', () => {
    expect(remediate).not.toMatch(/<img\s+src=\{a\.thumb\}/)
    expect(remediate).toMatch(/<ProposalThumb thumb=\{a\.thumb\}/)
  })

  it('and passes it alt text derived from the format', () => {
    expect(remediate).toMatch(/alt=\{appliedFixAlt\(a\.file\)\}/)
  })

  it('no component injects an unvalidated thumb into an img src', () => {
    for (const f of ['Remediate.jsx', 'EvidenceCard.jsx']) {
      expect(code(f)).not.toMatch(/<img[^>]*src=\{[^}]*thumb[^}]*\}/)
    }
  })
})
