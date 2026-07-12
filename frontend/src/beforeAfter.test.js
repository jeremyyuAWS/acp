import { describe, it, expect } from 'vitest'
import { beforeAfter } from './beforeAfter.js'

describe('beforeAfter — one before/after descriptor for every finding type (roadmap #2)', () => {
  it('contrast → swatch descriptor from real colours', () => {
    const ba = beforeAfter({ sc: '1.4.3', detail: 'Text #A0A0A0 on #FFFFFF is 2.6:1 (needs 4.5:1)' })
    expect(ba.kind).toBe('contrast')
    expect(ba.contrast.ratio).toBe(2.6)
  })

  it('heading skip → the real levels, corrected to a consecutive step', () => {
    const ba = beforeAfter({ sc: '2.4.6', detail: 'Heading level jumps from H2 to H4 (should step to H3)' })
    expect(ba).toEqual({ kind: 'heading', before: [2, 4], after: [2, 3] })
  })

  it('heading with no parseable levels → null (card keeps prose, no invented outline)', () => {
    expect(beforeAfter({ sc: '2.4.6', detail: 'Headings must form a logical hierarchy' })).toBeNull()
  })

  it('language → the proposed tag when known, else null after (never an invented code)', () => {
    expect(beforeAfter({ sc: '3.1.1', recommendation: 'en-US' })).toEqual({ kind: 'lang', after: 'en-US' })
    expect(beforeAfter({ sc: '3.1.1' })).toEqual({ kind: 'lang', after: null })
  })

  it('a type with no before/after visual → null (alt/link use the editor, not a redundant strip)', () => {
    expect(beforeAfter({ sc: '1.1.1', detail: '' })).toBeNull()
    expect(beforeAfter({ sc: '2.4.4' })).toBeNull()
  })

  it('reads sc from rule_id when not pre-computed', () => {
    expect(beforeAfter({ rule_id: 'SC_2_4_6', detail: 'Heading level jumps from H1 to H3 (should step to H2)' }))
      .toEqual({ kind: 'heading', before: [1, 3], after: [1, 2] })
  })
})
