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
  it('renders a stopped card (not nothing) when busy is false and scan did not complete', () => {
    // Pre-fix this returned ''. Now it shows the stopped summary — the card should NOT vanish.
    const html = render(PROG, false)
    expect(html).toContain('Discovery stopped')
    expect(html).not.toBe('')
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
    expect(html).toContain('Stopping keeps the inventory collected so far')
    expect(html).toContain('No documents are opened, assessed, moved, or changed in the source')
    expect(html).not.toContain('documents already assessed')
  })

  it('Stop sits beside the stop message, not far away', () => {
    const html = render(PROG, true, () => {})
    const stopAt = html.indexOf('>Stop<')
    const msgAt = html.indexOf('Stopping keeps the inventory')
    expect(stopAt).toBeGreaterThan(-1)
    expect(msgAt).toBeGreaterThan(-1)
    expect(msgAt - stopAt).toBeLessThan(400)
  })
})

// ── §9 failure states: stopped / failed card ─────────────────────────────────

describe('stopped card (§9): scan ended before completion', () => {
  it('renders "Discovery stopped" when busy is false and scan is not done', () => {
    const prog = { phase: 'discovering', files_found: 42 }
    const html = render(prog, false)
    expect(html).toContain('Discovery stopped')
    expect(html).not.toBe('')
  })

  it('renders nothing when both busy and progress are absent (pre-scan)', () => {
    expect(render(null, false)).toBe('')
  })

  it('shows elapsed time in stopped card', () => {
    const prog = { phase: 'reading', files_found: 100 }
    const html = render(prog, false)
    // elapsed renders as "0s" immediately in SSR (no timer has fired)
    expect(html).toContain('0s')
  })

  it('shows file count when inv has rows', () => {
    const prog = { phase: 'reading', files_found: 0 }
    const inv = { total: 88, rows: [] }
    const html = render(prog, false, undefined, undefined, inv)
    expect(html).toContain('88 files catalogued')
  })

  it('falls back to files_found for the catalogued count when inv is absent', () => {
    const prog = { phase: 'discovering', files_found: 53 }
    const html = render(prog, false)
    expect(html).toContain('53 files catalogued')
  })

  it('shows "Discovery could not complete" when progress.error is set', () => {
    const prog = { phase: 'connecting', files_found: 0, error: 'Authorization expired — re-connect the source.' }
    const html = render(prog, false)
    expect(html).toContain('Discovery could not complete')
    expect(html).toContain('Authorization expired')
  })

  it('shows the error message in a separate element', () => {
    const prog = { phase: 'connecting', files_found: 0, error: 'Source unreachable.' }
    const html = render(prog, false)
    expect(html).toContain('Source unreachable.')
  })

  it('shows "Review partial inventory" button when inv has rows and onReview is provided', () => {
    const prog = { phase: 'reading', files_found: 0 }
    const inv = { total: 12, rows: [] }
    const html = render(prog, false, undefined, undefined, inv)
    // onReview not passed — button absent
    expect(html).not.toContain('Review partial inventory')
    // Pass onReview
    const html2 = renderToStaticMarkup(createElement(DiscoverRunProgress, {
      progress: prog, busy: false, onReview: () => {}, inv,
    }))
    expect(html2).toContain('Review partial inventory')
  })

  it('omits Review button when inv has no rows', () => {
    const prog = { phase: 'discovering', files_found: 0 }
    const html = renderToStaticMarkup(createElement(DiscoverRunProgress, {
      progress: prog, busy: false, onReview: () => {},
    }))
    expect(html).not.toContain('Review partial inventory')
  })

  it('no pulse dot appears in the stopped card (active step demoted to pending)', () => {
    const prog = { phase: 'reading', files_found: 100 }
    const html = render(prog, false)
    expect(html).not.toContain('prep-pulse')
  })

  it('shows steps completed up to the stop point as done (✓)', () => {
    // phase=reading → doneCount=2 → Connected and Listing are done
    const prog = { phase: 'reading', files_found: 80, folders_found: 5 }
    const html = render(prog, false)
    const connectedIdx = html.indexOf('Connected to source')
    const checkBefore = html.lastIndexOf('✓', connectedIdx)
    expect(checkBefore).toBeGreaterThan(-1)
  })

  it('includes "Partial inventory retained" footer', () => {
    const prog = { phase: 'discovering', files_found: 0 }
    const html = render(prog, false)
    expect(html).toContain('Partial inventory retained')
  })

  it('still renders completion summary when phase is done and busy is false', () => {
    const prog = { phase: 'done', files_found: 100 }
    const html = render(prog, false)
    expect(html).toContain('Discovery complete')
    expect(html).not.toContain('Discovery stopped')
  })
})
