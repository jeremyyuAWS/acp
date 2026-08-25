import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'

// The Discover RUNNING screen: a step checklist scoped to inventory only.
// Rule: no assessment content (workers, queues, WCAG, findings) appears here.
// Steps derive from the backend phase; no percentage is fabricated.

const PROG = { phase: 'discovering', files_found: 8420 }
const render = (progress, busy, onStop, sources, inv) =>
  renderToStaticMarkup(createElement(DiscoverRunProgress, { progress, busy, onStop, sources, inv }))

describe('DiscoverRunProgress renders nothing until a scan is live', () => {
  it('renders nothing when busy is false', () => {
    expect(render(PROG, false)).toBe('')
  })

  it('renders nothing when progress is null', () => {
    expect(render(null, true)).toBe('')
  })

  it('renders nothing when both are absent', () => {
    expect(render(null, false)).toBe('')
  })
})

describe('the discovery step checklist', () => {
  it('shows Discovering documents heading', () => {
    const html = render(PROG, true)
    expect(html).toContain('Discovering documents')
  })

  it('marks Connected as done and Listing as active during the discovering phase', () => {
    const html = render(PROG, true)
    expect(html).toContain('Connected to source')
    expect(html).toContain('Listing folders and files')
    expect(html).toContain('8,420 found')
    // Connected must be done (✓), Listing must be active (pulse dot)
    const connectedIdx = html.indexOf('Connected to source')
    const listingIdx = html.indexOf('Listing folders and files')
    // The ✓ mark appears before Connected (they're in the same listitem)
    const checkBefore = html.lastIndexOf('✓', connectedIdx)
    expect(checkBefore).toBeGreaterThan(-1)
    expect(checkBefore).toBeLessThan(connectedIdx)
    // prep-pulse appears before Listing
    const pulseBefore = html.lastIndexOf('prep-pulse', listingIdx)
    expect(pulseBefore).toBeGreaterThan(-1)
    expect(pulseBefore).toBeLessThan(listingIdx)
  })

  it('shows all six steps', () => {
    const html = render(PROG, true)
    expect(html).toContain('Connected to source')
    expect(html).toContain('Listing folders and files')
    expect(html).toContain('Reading document metadata')
    expect(html).toContain('Classifying document types')
    expect(html).toContain('Applying lifecycle rules')
    expect(html).toContain('Saving inventory')
  })

  it('substitutes the single source name into the Connected label', () => {
    const sources = [{ name: 'Google Drive' }]
    const html = render(PROG, true, undefined, sources)
    expect(html).toContain('Connected to Google Drive')
    expect(html).not.toContain('Connected to source')
  })

  it('uses generic label when multiple sources are connected', () => {
    const sources = [{ name: 'Google Drive' }, { name: 'SharePoint' }]
    const html = render(PROG, true, undefined, sources)
    expect(html).toContain('Connected to source')
  })
})

describe('phase-driven step completion', () => {
  it('shows Connected as active during connecting phase', () => {
    const prog = { phase: 'connecting', files_found: 0 }
    const html = render(prog, true)
    // Connected is step 0, doneCount=0, so it is active (pulse)
    const connIdx = html.indexOf('Connected to source')
    const pulseIdx = html.lastIndexOf('prep-pulse', connIdx)
    expect(pulseIdx).toBeGreaterThan(-1)
    expect(pulseIdx).toBeLessThan(connIdx)
    // Listing should be pending (○), not active
    const listingIdx = html.indexOf('Listing folders and files')
    const circleIdx = html.lastIndexOf('○', listingIdx + 40)
    expect(circleIdx).toBeGreaterThan(-1)
  })

  it('shows Classifying as active during tagging phase', () => {
    const prog = { phase: 'tagging', files_found: 500 }
    const html = render(prog, true)
    expect(html).toContain('Classifying document types')
    // Saving should still be pending
    expect(html).toContain('Saving inventory')
    const savingIdx = html.indexOf('Saving inventory')
    const circleIdx = html.lastIndexOf('○', savingIdx + 40)
    expect(circleIdx).toBeGreaterThan(-1)
  })

  it('shows Saving as active during scoring phase', () => {
    const prog = { phase: 'scoring', files_found: 1000 }
    const html = render(prog, true)
    const savingIdx = html.indexOf('Saving inventory')
    const pulseIdx = html.lastIndexOf('prep-pulse', savingIdx)
    expect(pulseIdx).toBeGreaterThan(-1)
    expect(pulseIdx).toBeLessThan(savingIdx)
  })

  it('shows file count only on the Listing step', () => {
    const prog = { phase: 'discovering', files_found: 42 }
    const html = render(prog, true)
    expect(html).toContain('42 found')
    // The count appears in the same listitem as "Listing folders and files" —
    // there's a closing </div> for the listitem before the next step label.
    const listingItemStart = html.indexOf('Listing folders and files')
    const nextStepStart = html.indexOf('Reading document metadata')
    const foundAt = html.indexOf('42 found')
    expect(foundAt).toBeGreaterThan(listingItemStart)
    expect(foundAt).toBeLessThan(nextStepStart)
  })
})

describe('never shows assessment content', () => {
  it('does not mention assessment workers, queues, or WCAG evaluation', () => {
    const html = render(PROG, true)
    expect(html).not.toMatch(/assessment worker/i)
    expect(html).not.toMatch(/document queue/i)
    expect(html).not.toMatch(/WCAG/i)
    expect(html).not.toMatch(/need.attention/i)
    expect(html).not.toMatch(/unable to assess/i)
    expect(html).not.toMatch(/findings/i)
    expect(html).not.toMatch(/Preparing assessment/i)
  })
})

describe('lifecycle rules count on the lifecycle step', () => {
  const INV_ROWS = [
    { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
    { file: 'b.docx', lifecycle_rule_id: 'ret-1' },
    { file: 'c.docx', lifecycle_rule_id: 'arc-2' },
    { file: 'd.pdf',  lifecycle_rule_id: null },
  ]
  const inv = { rows: INV_ROWS, total: INV_ROWS.length }

  it('shows "2 rules applied" on the lifecycle step when inv has 2 distinct rule ids', () => {
    const prog = { phase: 'tagging', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('2 rules applied')
  })

  it('shows "1 rule applied" (singular) when only one rule id is present', () => {
    const singleRuleInv = { rows: [{ file: 'a.docx', lifecycle_rule_id: 'ret-1' }], total: 1 }
    const prog = { phase: 'tagging', files_found: 1 }
    const html = render(prog, true, undefined, undefined, singleRuleInv)
    expect(html).toContain('1 rule applied')
  })

  it('omits the rule count detail when inv is null', () => {
    const prog = { phase: 'tagging', files_found: 5 }
    const html = render(prog, true, undefined, undefined, null)
    expect(html).not.toContain('rules applied')
    expect(html).not.toContain('rule applied')
  })

  it('ignores rows with null lifecycle_rule_id when counting', () => {
    const nullRuleInv = { rows: [{ file: 'a.docx', lifecycle_rule_id: null }, { file: 'b.docx', lifecycle_rule_id: null }], total: 2 }
    const prog = { phase: 'tagging', files_found: 2 }
    const html = render(prog, true, undefined, undefined, nullRuleInv)
    expect(html).not.toContain('rules applied')
  })

  it('rule count detail appears near the Applying lifecycle rules step, not on other steps', () => {
    const prog = { phase: 'tagging', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    const lifecycleIdx = html.indexOf('Applying lifecycle rules')
    const nextStepIdx = html.indexOf('Saving inventory')
    const rulesIdx = html.indexOf('rules applied')
    expect(rulesIdx).toBeGreaterThan(lifecycleIdx)
    expect(rulesIdx).toBeLessThan(nextStepIdx)
  })
})

describe('Stop button placement', () => {
  it('shows Stop only when both busy and an onStop handler are provided', () => {
    expect(render(PROG, true, () => {})).toContain('>Stop<')
    expect(render(PROG, true, undefined)).not.toContain('>Stop<')
    expect(render(PROG, false, () => {})).not.toContain('>Stop<')
  })

  it('uses the discovery-specific stop message', () => {
    const html = render(PROG, true, () => {})
    expect(html).toContain('Partial inventory will be retained')
    expect(html).toContain('Source files will not be changed')
    expect(html).not.toContain('documents already assessed')
  })

  it('Stop is inside the card header alongside the elapsed timer', () => {
    const html = render(PROG, true, () => {})
    const stopAt = html.indexOf('>Stop<')
    const elapsedAt = html.indexOf('elapsed')
    // Both appear in the same header region — Stop comes shortly after elapsed
    expect(stopAt).toBeGreaterThan(-1)
    expect(elapsedAt).toBeGreaterThan(-1)
    expect(Math.abs(stopAt - elapsedAt)).toBeLessThan(300)
  })
})

describe('active step accessibility and visual treatment', () => {
  it('gives the active step aria-current="step"', () => {
    const html = render(PROG, true)
    expect(html).toContain('aria-current="step"')
  })

  it('gives each status an accessible aria-label', () => {
    const html = render(PROG, true)
    expect(html).toContain('aria-label="Completed"')
    expect(html).toContain('aria-label="In progress"')
    expect(html).toContain('aria-label="Not started"')
  })

  it('active step label has bold font-weight', () => {
    const html = render(PROG, true)
    // Listing is active during discovering phase; its label span must carry font-weight:600
    const listingIdx = html.indexOf('Listing folders and files')
    const weightIdx = html.lastIndexOf('font-weight:600', listingIdx)
    expect(weightIdx).toBeGreaterThan(-1)
    expect(listingIdx - weightIdx).toBeLessThan(200)
  })

  it('does not show the long-running hint below 90 s', () => {
    const html = render(PROG, true)
    expect(html).not.toContain('contains many folders')
  })
})
