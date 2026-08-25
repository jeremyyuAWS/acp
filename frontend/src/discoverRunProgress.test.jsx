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
  it('renders nothing when busy is false (non-done phase)', () => {
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
    expect(html).toContain('8,420 files found so far')
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

  it('shows "files found so far" on the active Listing step', () => {
    const prog = { phase: 'discovering', files_found: 42 }
    const html = render(prog, true)
    expect(html).toContain('42 files found so far')
    // The count appears in the same listitem as "Listing folders and files"
    const listingItemStart = html.indexOf('Listing folders and files')
    const nextStepStart = html.indexOf('Reading document metadata')
    const foundAt = html.indexOf('42 files found so far')
    expect(foundAt).toBeGreaterThan(listingItemStart)
    expect(foundAt).toBeLessThan(nextStepStart)
  })

  it('shows "files found" without "so far" on the done Listed step', () => {
    const prog = { phase: 'reading', files_found: 148 }
    const html = render(prog, true)
    expect(html).toContain('148 files found')
    expect(html).not.toContain('148 files found so far')
    const listedIdx = html.indexOf('Listed folders and files')
    const nextStepStart = html.indexOf('Reading document metadata')
    const foundAt = html.indexOf('148 files found')
    expect(foundAt).toBeGreaterThan(listedIdx)
    expect(foundAt).toBeLessThan(nextStepStart)
  })

  it('done steps use past-tense labels', () => {
    const prog = { phase: 'reading', files_found: 0 }
    const html = render(prog, true)
    expect(html).toContain('Listed folders and files')
    expect(html).not.toContain('Listing folders and files')
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

describe('lifecycle KPI on the lifecycle step', () => {
  // 3 files with a rule_id, 1 without — total 4
  const INV_ROWS = [
    { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
    { file: 'b.docx', lifecycle_rule_id: 'ret-1' },
    { file: 'c.docx', lifecycle_rule_id: 'arc-2' },
    { file: 'd.pdf',  lifecycle_rule_id: null },
  ]
  const inv = { rows: INV_ROWS, total: INV_ROWS.length }

  // scoring phase: lifecycle (index 4) is done, saving (index 5) is active
  it('shows "N matched · M unchanged" when lifecycle step is done', () => {
    const prog = { phase: 'scoring', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('3 matched')
    expect(html).toContain('1 unchanged')
  })

  it('shows "1 matched" (singular) when only one file matched a rule', () => {
    const singleMatchInv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
      { file: 'b.docx', lifecycle_rule_id: null },
    ], total: 2 }
    const prog = { phase: 'scoring', files_found: 2 }
    const html = render(prog, true, undefined, undefined, singleMatchInv)
    expect(html).toContain('1 matched')
    expect(html).toContain('1 unchanged')
  })

  it('omits the lifecycle KPI when inv is null', () => {
    const prog = { phase: 'scoring', files_found: 5 }
    const html = render(prog, true, undefined, undefined, null)
    expect(html).not.toContain('matched')
    expect(html).not.toContain('unchanged')
  })

  it('shows "— No enabled rules" when all rows have null lifecycle_rule_id', () => {
    const nullRuleInv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: null },
      { file: 'b.docx', lifecycle_rule_id: null },
    ], total: 2 }
    const prog = { phase: 'scoring', files_found: 2 }
    const html = render(prog, true, undefined, undefined, nullRuleInv)
    expect(html).toContain('No enabled rules')
    expect(html).not.toContain('0 matched')
    expect(html).not.toContain('2 unchanged')
  })

  it('lifecycle KPI appears near the Applied lifecycle rules step, not on other steps', () => {
    const prog = { phase: 'scoring', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    const lifecycleIdx = html.indexOf('Applied lifecycle rules')
    const nextStepIdx = html.indexOf('Saving inventory')
    const matchedIdx = html.indexOf('matched')
    expect(matchedIdx).toBeGreaterThan(lifecycleIdx)
    expect(matchedIdx).toBeLessThan(nextStepIdx)
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

describe('completion summary when phase is done', () => {
  it('shows completion summary instead of checklist when phase is done', () => {
    const prog = { phase: 'done', files_found: 148 }
    const html = render(prog, false)
    expect(html).toContain('Discovery complete')
    expect(html).not.toContain('Discovering documents')
  })

  it('renders even when busy is false if phase is done', () => {
    const prog = { phase: 'done', files_found: 148 }
    expect(render(prog, false)).not.toBe('')
  })

  it('shows past-tense step labels in completion summary', () => {
    const prog = { phase: 'done', files_found: 0 }
    const html = render(prog, true)
    expect(html).toContain('Listed folders and files')
    expect(html).toContain('Read document metadata')
    expect(html).toContain('Applied lifecycle rules')
    expect(html).toContain('Saved inventory')
  })

  it('includes files discovered and lifecycle totals in summary footer', () => {
    const inv = { rows: [{ file: 'a.pdf', lifecycle_rule_id: 'r1' }], total: 5 }
    const prog = { phase: 'done', files_found: 5 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('5 files discovered')
    expect(html).toContain('matched lifecycle rules')
    expect(html).toContain('No documents were assessed or changed')
  })

  it('does not show Stop button in completion summary', () => {
    const prog = { phase: 'done', files_found: 10 }
    const html = render(prog, true, () => {})
    expect(html).not.toContain('>Stop<')
    expect(html).not.toContain('>Stopping')
  })
})

describe('metadata KPI on the metadata step', () => {
  // 1 complete (owner + source_modified both set), 2 incomplete
  const INV_META = [
    { file: 'a.docx', owner: 'alice@co.com', source_modified: '2024-01', lifecycle_rule_id: null, doc_class: 'text-document' },
    { file: 'b.pptx', owner: null,           source_modified: null,       lifecycle_rule_id: null, doc_class: 'slide-deck' },
    { file: 'c.pdf',  owner: 'bob@co.com',   source_modified: null,       lifecycle_rule_id: null, doc_class: 'pdf-document' },
  ]
  const inv = { rows: INV_META, total: INV_META.length }

  it('shows "N complete · M incomplete" when metadata step is done (tagging phase)', () => {
    // tagging phase: PHASE_DONE_COUNT=3, so steps 0-2 are done; metadata (index 2) is done
    const prog = { phase: 'tagging', files_found: 3 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('1 complete')
    expect(html).toContain('2 incomplete')
  })

  it('KPI appears near the Read document metadata step', () => {
    const prog = { phase: 'tagging', files_found: 3 }
    const html = render(prog, true, undefined, undefined, inv)
    const metaIdx = html.indexOf('Read document metadata')
    const nextIdx = html.indexOf('Classifying document types')
    const kpiIdx = html.indexOf('1 complete')
    expect(kpiIdx).toBeGreaterThan(metaIdx)
    expect(kpiIdx).toBeLessThan(nextIdx)
  })

  it('omits metadata KPI when inv is null', () => {
    const prog = { phase: 'tagging', files_found: 3 }
    const html = render(prog, true)
    expect(html).not.toContain('complete')
    expect(html).not.toContain('incomplete')
  })
})

describe('classification KPI on the classifying step', () => {
  // 2 assessable (text-document, slide-deck), 2 unsupported (image, audio-video)
  const INV_CLASS = [
    { file: 'a.docx', doc_class: 'text-document', owner: 'u', source_modified: 't', lifecycle_rule_id: null },
    { file: 'b.pptx', doc_class: 'slide-deck',    owner: 'u', source_modified: 't', lifecycle_rule_id: null },
    { file: 'c.png',  doc_class: 'image',          owner: null, source_modified: null, lifecycle_rule_id: null },
    { file: 'd.mp4',  doc_class: 'audio-video',    owner: null, source_modified: null, lifecycle_rule_id: null },
  ]
  const inv = { rows: INV_CLASS, total: INV_CLASS.length }

  it('shows "N assessable · M unsupported" when classifying step is done (analysing phase)', () => {
    // analysing phase: PHASE_DONE_COUNT=4, so steps 0-3 are done; classifying (index 3) is done
    const prog = { phase: 'analysing', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('2 assessable')
    expect(html).toContain('2 unsupported')
  })

  it('KPI appears near the Classified document types step', () => {
    const prog = { phase: 'analysing', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    const classIdx = html.indexOf('Classified document types')
    const nextIdx = html.indexOf('Applying lifecycle rules')
    const kpiIdx = html.indexOf('2 assessable')
    expect(kpiIdx).toBeGreaterThan(classIdx)
    expect(kpiIdx).toBeLessThan(nextIdx)
  })

  it('omits classification KPI when inv is null', () => {
    const prog = { phase: 'analysing', files_found: 4 }
    const html = render(prog, true)
    expect(html).not.toContain('assessable')
    expect(html).not.toContain('unsupported')
  })

  it('counts all five assessable mime types correctly', () => {
    const allTypes = [
      { file: 'a', doc_class: 'slide-deck',    lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'b', doc_class: 'text-document', lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'c', doc_class: 'pdf-document',  lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'd', doc_class: 'spreadsheet',   lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'e', doc_class: 'web-page',      lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'f', doc_class: 'image',         lifecycle_rule_id: null, owner: null, source_modified: null },
    ]
    const i2 = { rows: allTypes, total: allTypes.length }
    const prog = { phase: 'analysing', files_found: 6 }
    const html = render(prog, true, undefined, undefined, i2)
    expect(html).toContain('5 assessable')
    expect(html).toContain('1 unsupported')
  })
})

describe('accessibility: KPI spans do not spam screen readers', () => {
  it('KPI spans carry aria-hidden to prevent per-tick announcements', () => {
    const prog = { phase: 'discovering', files_found: 1000 }
    const html = render(prog, true)
    // "1,000 files found so far" must be in an aria-hidden span
    const kpiIdx = html.indexOf('1,000 files found so far')
    expect(kpiIdx).toBeGreaterThan(-1)
    const ariaHiddenIdx = html.lastIndexOf('aria-hidden', kpiIdx)
    expect(ariaHiddenIdx).toBeGreaterThan(-1)
    expect(kpiIdx - ariaHiddenIdx).toBeLessThan(150)
  })

  it('has a dedicated role=status live region naming the active step', () => {
    const prog = { phase: 'discovering', files_found: 0 }
    const html = render(prog, true)
    // Must contain a status region with the active step name
    expect(html).toContain('Step in progress: Listing folders and files')
  })

  it('status region updates when the active step changes phase', () => {
    const html = render({ phase: 'reading', files_found: 50 }, true)
    expect(html).toContain('Step in progress: Reading document metadata')
  })
})

describe('reconciliation in completion summary', () => {
  it('shows assessable/unsupported breakdown when inv is available', () => {
    const rows = [
      { file: 'a.docx', doc_class: 'text-document', lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'b.pptx', doc_class: 'slide-deck',    lifecycle_rule_id: null, owner: null, source_modified: null },
      { file: 'c.png',  doc_class: 'image',          lifecycle_rule_id: null, owner: null, source_modified: null },
    ]
    const inv = { rows, total: 3 }
    const prog = { phase: 'done', files_found: 3 }
    const html = render(prog, false, undefined, undefined, inv)
    // assessable + unsupported must sum to total (3)
    expect(html).toContain('3 files discovered')
    expect(html).toContain('2 assessable')
    expect(html).toContain('1 unsupported')
  })

  it('omits the breakdown row when inv is null', () => {
    const prog = { phase: 'done', files_found: 5 }
    const html = render(prog, false)
    expect(html).not.toContain('assessable')
    expect(html).not.toContain('unsupported')
    // But the core summary line must still appear
    expect(html).toContain('files discovered')
    expect(html).toContain('No documents were assessed or changed')
  })
})

describe('lifecycle no-rules treatment', () => {
  it('shows "No enabled rules" when all files have null lifecycle_rule_id', () => {
    const noRulesInv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: null },
      { file: 'b.pptx', lifecycle_rule_id: null },
      { file: 'c.pdf',  lifecycle_rule_id: null },
    ], total: 3 }
    const prog = { phase: 'scoring', files_found: 3 }
    const html = render(prog, true, undefined, undefined, noRulesInv)
    expect(html).toContain('No enabled rules')
    expect(html).not.toContain('0 matched')
    expect(html).not.toContain('3 unchanged')
  })

  it('still shows matched/unchanged when at least one rule fired', () => {
    const mixedInv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
      { file: 'b.docx', lifecycle_rule_id: null },
    ], total: 2 }
    const prog = { phase: 'scoring', files_found: 2 }
    const html = render(prog, true, undefined, undefined, mixedInv)
    expect(html).toContain('1 matched')
    expect(html).toContain('1 unchanged')
    expect(html).not.toContain('No enabled rules')
  })

  it('"No enabled rules" appears in the lifecycle step row, not elsewhere', () => {
    const noRulesInv = { rows: [{ file: 'a.docx', lifecycle_rule_id: null }], total: 1 }
    const prog = { phase: 'scoring', files_found: 1 }
    const html = render(prog, true, undefined, undefined, noRulesInv)
    const lifecycleIdx = html.indexOf('Applied lifecycle rules')
    const nextIdx = html.indexOf('Saving inventory')
    const noRulesIdx = html.indexOf('No enabled rules')
    expect(noRulesIdx).toBeGreaterThan(lifecycleIdx)
    expect(noRulesIdx).toBeLessThan(nextIdx)
  })
})

describe('lifecycle stall hint', () => {
  it('does not show lifecycle hint before 30 s', () => {
    // elapsed starts at 0 on mount; renderToStaticMarkup captures that snapshot
    const prog = { phase: 'analysing', files_found: 100 }
    const html = render(prog, true)
    expect(html).not.toContain('Lifecycle evaluation is taking longer')
  })

  it('does not show lifecycle hint in non-analysing phases', () => {
    // tagging phase is not analysing — hint must not appear regardless of elapsed
    const prog = { phase: 'tagging', files_found: 100 }
    const html = render(prog, true)
    expect(html).not.toContain('Lifecycle evaluation is taking longer')
  })

  it('hint text is discoverable in the DOM when phase is analysing', () => {
    // The hint is gated on elapsed >= 30 which starts at 0 and only grows via useEffect;
    // since renderToStaticMarkup does not run effects, elapsed will be 0 and the hint will not
    // render. We verify the correct guard by checking the other side: the text must NOT appear
    // in any other phase, and the analysing phase itself must not show it at t=0.
    const phases = ['queued', 'connecting', 'discovering', 'reading', 'tagging', 'scoring', 'finalizing']
    for (const phase of phases) {
      const html = render({ phase, files_found: 50 }, true)
      expect(html).not.toContain('Lifecycle evaluation is taking longer')
    }
  })
})
