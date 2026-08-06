import { describe, it, expect } from 'vitest'
import { describedImageType } from './reviewCard.js'

const withAlt = (s) => ({ proposals: [{ proposed_value: s }] })

describe('#130 — image kind is read from the model’s own words, never guessed', () => {
  it('recognises the common kinds from the description', () => {
    expect(describedImageType(withAlt('A bar chart showing Q4 revenue by region.')).label).toBe('Chart')
    expect(describedImageType(withAlt('A flowchart of the remediation workflow.')).label).toBe('Diagram')
    expect(describedImageType(withAlt('A screenshot of the settings page.')).label).toBe('Screenshot')
    expect(describedImageType(withAlt('The company logo.')).label).toBe('Logo')
    expect(describedImageType(withAlt('A photo of a clinician at a desk.')).label).toBe('Photo')
    expect(describedImageType(withAlt('A table of quarterly figures.')).label).toBe('Table')
  })

  it('prefers the specific noun — "bar chart" is a Chart, not swallowed by "graphic"', () => {
    expect(describedImageType(withAlt('A line graph of monthly active users.')).label).toBe('Chart')
  })

  it('returns null when no kind is named — no fabricated label, no chip', () => {
    expect(describedImageType(withAlt('Two people shaking hands.'))).toBeNull()
    expect(describedImageType({ proposals: [] })).toBeNull()
    expect(describedImageType(null)).toBeNull()
  })

  it('each kind carries a plain-English hint on what a good description looks like', () => {
    expect(describedImageType(withAlt('A pie chart.')).hint).toMatch(/trend|figure/)
    expect(describedImageType(withAlt('An icon.')).hint).toMatch(/word/)
  })
})
