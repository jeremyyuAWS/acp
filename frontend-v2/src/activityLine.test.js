// The concrete progress line: which document, which criterion, what action.
//
// phaseNarration.test.js guards the PHASE narration against fabricated progress — narration
// derived from elapsed time, or vocabulary from a step that isn't running. This file guards the
// same property for the specific line, which is more exposed to it: a filename and a criterion
// look authoritative in a way a general sentence does not, so a fabricated one is believed.
//
// Every assertion below is therefore either "renders exactly what the backend said" or "renders
// nothing". There is deliberately no case where this function composes a sentence of its own.
import { describe, expect, it } from 'vitest'

import { activityLine } from './phaseNarration.js'

describe('activityLine', () => {
  it('renders the backend string verbatim', () => {
    expect(activityLine({ activity: 'benefits.docx · 1.1.1 Non-text Content · describing images' }))
      .toBe('benefits.docx · 1.1.1 Non-text Content · describing images')
  })

  it('unwraps the object form the remediation poll sends', () => {
    // /scans/{id}/remediation-status nests it ({text, file, sc, ...}); the scan progress payload
    // sends the flat string. One renderer has to read both or the line appears on only one path.
    expect(activityLine({ activity: { text: 'a.docx · 1.3.1 Info and Relationships · marking table headers', sc: '1.3.1' } }))
      .toBe('a.docx · 1.3.1 Info and Relationships · marking table headers')
  })

  it('falls back to the filename when there is no activity field', () => {
    // Payloads predating the activity field still carry `current`. A filename alone is less than
    // we now send and more than the phase alone.
    expect(activityLine({ phase: 'analysing', current: 'consent.docx' })).toBe('consent.docx')
  })

  it('prefers the activity string over the bare filename', () => {
    expect(activityLine({ activity: 'x.docx · 2.4.4 Link Purpose (In Context) · drafting', current: 'x.docx' }))
      .toBe('x.docx · 2.4.4 Link Purpose (In Context) · drafting')
  })

  it('renders NOTHING rather than guessing, on every empty shape', () => {
    // The whole contract. A spinner with no line is honest; a spinner with an invented line is
    // the fabricated-progress pattern this codebase has already deleted twice.
    expect(activityLine(null)).toBeNull()
    expect(activityLine(undefined)).toBeNull()
    expect(activityLine({})).toBeNull()
    expect(activityLine({ phase: 'analysing' })).toBeNull()
    expect(activityLine({ activity: '' })).toBeNull()
    expect(activityLine({ activity: '   ' })).toBeNull()
    expect(activityLine({ activity: {} })).toBeNull()
    expect(activityLine({ activity: { text: '' } })).toBeNull()
    expect(activityLine({ current: null })).toBeNull()
    expect(activityLine('analysing')).toBeNull()
  })

  it('does not vary with elapsed time or call count', () => {
    // phaseNarration.js was rewritten because a line was chosen by `elapsed / 5 % n` and cycled
    // through plausible sentences while the backend did something else. Same failure, same guard.
    const p = { activity: 'a.docx · 1.4.5 Images of Text · reading text in images' }
    const seen = new Set(Array.from({ length: 50 }, () => activityLine(p)))
    expect(seen.size).toBe(1)
  })

  it('trims incidental whitespace without altering the text', () => {
    expect(activityLine({ activity: '  a.docx · 3.1.2 Language of Parts · drafting  ' }))
      .toBe('a.docx · 3.1.2 Language of Parts · drafting')
  })
})
