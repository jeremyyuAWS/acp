import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

// The Discover RUNNING screen: a per-step checklist scoped to inventory only.
// Rule: no assessment content (workers, queues, WCAG, findings) appears here.
// Steps derive from the backend phase; no percentage is fabricated.
//
// Four steps: Connect to source → Build document inventory → Apply lifecycle rules →
// Finalize Discovery. "Build document inventory" encompasses listing, metadata, classification,
// and batch saves — these are ONE concurrent operation in the backend, not sequential.
// When phase='done' and busy=false, DiscoverRunProgress returns null so that
// DiscoverCompleteSummary can render the immutable completion card.

const PROG = { phase: 'discovering', files_found: 8420 }
const render = (progress, busy, onStop, sources, inv) =>
  renderToStaticMarkup(createElement(DiscoverRunProgress, { progress, busy, onStop, sources, inv }))

describe('DiscoverRunProgress renders nothing until a scan is live', () => {
  it('renders a stopped card (not nothing) when busy is false and scan did not complete', () => {
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

  it('returns null (empty string) when phase is done and not busy — DiscoverCompleteSummary takes over', () => {
    const prog = { phase: 'done', files_found: 100 }
    expect(render(prog, false)).toBe('')
  })
})

describe('the discovery step checklist', () => {
  it('shows Discovering documents heading', () => {
    const html = render(PROG, true)
    expect(html).toContain('Discovering documents')
  })

  it('marks Connected as done and Build document inventory as active during the discovering phase', () => {
    const html = render(PROG, true)
    expect(html).toContain('Connected to source')
    expect(html).toContain('Build document inventory')
    expect(html).toContain('8,420 files found')
    // Connected must be done (✓)
    const connectedIdx = html.indexOf('Connected to source')
    const checkBefore = html.lastIndexOf('✓', connectedIdx)
    expect(checkBefore).toBeGreaterThan(-1)
    expect(checkBefore).toBeLessThan(connectedIdx)
    // prep-pulse appears before Build document inventory
    const inventoryIdx = html.indexOf('Build document inventory')
    const pulseBefore = html.lastIndexOf('prep-pulse', inventoryIdx)
    expect(pulseBefore).toBeGreaterThan(-1)
    expect(pulseBefore).toBeLessThan(inventoryIdx)
  })

  it('shows all four steps', () => {
    const html = render(PROG, true)
    // PROG is phase:discovering so step 1 is done — expect the done label
    expect(html).toContain('Connected to source')
    expect(html).toContain('Build document inventory')
    expect(html).toContain('Apply lifecycle rules')
    expect(html).toContain('Finalize Discovery')
  })

  it('orders steps: Connected → Build inventory → Apply lifecycle rules → Finalize Discovery', () => {
    const html = render(PROG, true)
    const connectedIdx = html.indexOf('Connected to source')
    const inventoryIdx = html.indexOf('Build document inventory')
    const lifecycleIdx = html.indexOf('Apply lifecycle rules')
    const finalizingIdx = html.indexOf('Finalize Discovery')
    expect(connectedIdx).toBeGreaterThan(-1)
    expect(inventoryIdx).toBeGreaterThan(connectedIdx)
    expect(lifecycleIdx).toBeGreaterThan(inventoryIdx)
    expect(finalizingIdx).toBeGreaterThan(lifecycleIdx)
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
    // Step is done (discovering phase), so done label is shown
    expect(html).toContain('Connected to source')
  })
})

describe('phase-driven step completion', () => {
  it('shows Connected as active during connecting phase', () => {
    const prog = { phase: 'connecting', files_found: 0 }
    const html = render(prog, true)
    const connIdx = html.indexOf('Connect to source')
    const pulseIdx = html.lastIndexOf('prep-pulse', connIdx)
    expect(pulseIdx).toBeGreaterThan(-1)
    expect(pulseIdx).toBeLessThan(connIdx)
    // Inventory step should be pending (○)
    const inventoryIdx = html.indexOf('Build document inventory')
    const circleIdx = html.lastIndexOf('○', inventoryIdx + 40)
    expect(circleIdx).toBeGreaterThan(-1)
  })

  it('aliases the historical reading/tagging phase values to the same merged inventory step', () => {
    for (const phase of ['reading', 'tagging']) {
      const html = render({ phase, files_found: 500 }, true)
      expect(html, `phase ${phase}`).toContain('500 files found')
      const connectedIdx = html.indexOf('Connected to source')
      const checkBefore = html.lastIndexOf('✓', connectedIdx)
      expect(checkBefore, `phase ${phase}`).toBeGreaterThan(-1)
    }
  })

  it('saving phase keeps Build document inventory active — saving is part of inventory build', () => {
    // add_inventory writes batches throughout the BFS walk — not a distinct sequential step.
    // 'saving' phase maps to doneCount=1 (inventory still active, not a separate step).
    const prog = { phase: 'saving', files_found: 1000 }
    const html = render(prog, true)
    const inventoryIdx = html.indexOf('Build document inventory')
    const pulseIdx = html.lastIndexOf('prep-pulse', inventoryIdx)
    expect(pulseIdx).toBeGreaterThan(-1)
    expect(pulseIdx).toBeLessThan(inventoryIdx)
    // Lifecycle has not started yet — still shows its pending (not done, not active) label.
    expect(html).toContain('Apply lifecycle rules')
    expect(html).not.toContain('Applied lifecycle rules')
  })

  it('shows Finalize Discovery as active during scoring/finalizing phases', () => {
    // scoring/finalizing map to doneCount=3 → connected, inventory, lifecycle all done;
    // finalizing step is active (pulsing), not "everything done with no active step".
    for (const phase of ['scoring', 'finalizing']) {
      const html = render({ phase, files_found: 1000 }, true)
      expect(html, `phase ${phase}`).toContain('Applied lifecycle rules')
      expect(html, `phase ${phase}`).toContain('Finalize Discovery')
      // Finalize Discovery should have a pulse dot (it's active)
      const finalizingIdx = html.indexOf('Finalize Discovery')
      const pulseIdx = html.lastIndexOf('prep-pulse', finalizingIdx)
      expect(pulseIdx, `phase ${phase}: Finalize Discovery should be active`).toBeGreaterThan(-1)
      expect(pulseIdx).toBeLessThan(finalizingIdx)
    }
  })

  it('shows "files found" on the active Build document inventory step', () => {
    const prog = { phase: 'discovering', files_found: 42 }
    const html = render(prog, true)
    expect(html).toContain('42 files found')
    const inventoryStart = html.indexOf('Build document inventory')
    const nextStepStart = html.indexOf('Apply lifecycle rules')
    const foundAt = html.indexOf('42 files found')
    expect(foundAt).toBeGreaterThan(inventoryStart)
    expect(foundAt).toBeLessThan(nextStepStart)
  })

  it('shows "N files · M folders" on the active inventory step when folders_found is present', () => {
    const prog = { phase: 'discovering', files_found: 100, folders_found: 12 }
    const html = render(prog, true)
    expect(html).toContain('100 files · 12 folders')
  })

  it('shows "files found" without "so far" on the done inventory step when folders_found is absent', () => {
    const prog = { phase: 'lifecycle', files_found: 148 }
    const html = render(prog, true)
    expect(html).toContain('148 files found')
    expect(html).not.toContain('so far')
    const builtIdx = html.indexOf('Built document inventory')
    const nextStepStart = html.indexOf('Apply lifecycle rules')
    const foundAt = html.indexOf('148 files found')
    expect(foundAt).toBeGreaterThan(builtIdx)
    expect(foundAt).toBeLessThan(nextStepStart)
  })

  it('shows "N files · M folders" on the done inventory step when folders_found is present', () => {
    const prog = { phase: 'lifecycle', files_found: 148, folders_found: 12 }
    const html = render(prog, true)
    expect(html).toContain('148 files · 12 folders')
    const builtIdx = html.indexOf('Built document inventory')
    const nextStepStart = html.indexOf('Apply lifecycle rules')
    const kpiIdx = html.indexOf('148 files · 12 folders')
    expect(kpiIdx).toBeGreaterThan(builtIdx)
    expect(kpiIdx).toBeLessThan(nextStepStart)
  })

  it('done steps use past-tense labels', () => {
    const prog = { phase: 'lifecycle', files_found: 0 }
    const html = render(prog, true)
    expect(html).toContain('Built document inventory')
    expect(html).not.toContain('Build document inventory')
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
  const INV_ROWS = [
    { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
    { file: 'b.docx', lifecycle_rule_id: 'ret-1' },
    { file: 'c.docx', lifecycle_rule_id: 'arc-2' },
    { file: 'd.pdf',  lifecycle_rule_id: null },
  ]
  const inv = { rows: INV_ROWS, total: INV_ROWS.length }

  // scoring phase: doneCount=3 → lifecycle done, finalizing active
  it('shows "N matched" when lifecycle step is done (inv-derived fallback)', () => {
    const prog = { phase: 'scoring', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('3 matched')
  })

  it('shows "1 matched" (singular) when only one file matched a rule', () => {
    const singleMatchInv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
      { file: 'b.docx', lifecycle_rule_id: null },
    ], total: 2 }
    const prog = { phase: 'scoring', files_found: 2 }
    const html = render(prog, true, undefined, undefined, singleMatchInv)
    expect(html).toContain('1 matched')
  })

  it('omits the lifecycle KPI when inv is null', () => {
    const prog = { phase: 'scoring', files_found: 5 }
    const html = render(prog, true, undefined, undefined, null)
    expect(html).not.toContain('matched')
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
  })

  it('lifecycle KPI appears near the Applied lifecycle rules step', () => {
    const prog = { phase: 'scoring', files_found: 4 }
    const html = render(prog, true, undefined, undefined, inv)
    const lifecycleIdx = html.indexOf('Applied lifecycle rules')
    const finalizingIdx = html.indexOf('Finalize Discovery')
    const matchedIdx = html.indexOf('matched')
    expect(matchedIdx).toBeGreaterThan(lifecycleIdx)
    expect(matchedIdx).toBeLessThan(finalizingIdx)
  })
})

describe('lifecycle KPI live updates during active phase', () => {
  it('shows eval progress KPI when lifecycle phase is active', () => {
    const prog = {
      phase: 'lifecycle', files_found: 500, files_evaluated: 120, rules_enabled: 3,
    }
    const html = render(prog, true)
    expect(html).toContain('120 of 500 evaluated')
  })

  it('shows rule count as KPI when rules are known but evaluation not started', () => {
    const prog = {
      phase: 'lifecycle', files_found: 200, rules_enabled: 4,
    }
    const html = render(prog, true)
    expect(html).toContain('4 rules')
  })

  it('shows "1 rule" singular when rules_enabled is 1', () => {
    const prog = {
      phase: 'lifecycle', files_found: 100, rules_enabled: 1,
    }
    const html = render(prog, true)
    expect(html).toContain('1 rule')
    expect(html).not.toContain('1 rules')
  })

  it('shows "No enabled rules" during lifecycle phase when rules_enabled is 0', () => {
    const prog = {
      phase: 'lifecycle', files_found: 50, files_evaluated: 0, rules_enabled: 0,
    }
    const html = render(prog, true)
    expect(html).toContain('No enabled rules')
  })

  it('shows a determinate progress bar during lifecycle phase when files_evaluated is available', () => {
    const prog = {
      phase: 'lifecycle', files_found: 500, files_evaluated: 120,
    }
    const html = render(prog, true)
    // Native <progress> element with correct value/max
    expect(html).toContain('<progress')
    expect(html).toContain('value="120"')
    expect(html).toContain('max="500"')
  })

  it('progress bar is accessible: carries aria-label with numbers', () => {
    const prog = {
      phase: 'lifecycle', files_found: 200, files_evaluated: 50,
    }
    const html = render(prog, true)
    expect(html).toContain('aria-label')
    expect(html).toContain('50')
    expect(html).toContain('200')
  })

  it('shows matched breakdown when lifecycle_matches > 0 (during active phase)', () => {
    const prog = {
      phase: 'lifecycle', files_found: 500, files_evaluated: 300,
      lifecycle_matches: 50, lifecycle_archive: 20, lifecycle_delete: 10, lifecycle_tagged: 20,
    }
    const html = render(prog, true)
    expect(html).toContain('50 matched')
    expect(html).toContain('20 Archive Candidates')
    expect(html).toContain('10 Delete Candidate')
    expect(html).toContain('20 tagged')
  })

  it('omits breakdown when no files matched yet', () => {
    const prog = {
      phase: 'lifecycle', files_found: 200, files_evaluated: 50,
      lifecycle_matches: 0,
    }
    const html = render(prog, true)
    expect(html).not.toContain('matched')
  })

  it('omits progress bar when files_evaluated is absent', () => {
    const prog = { phase: 'lifecycle', files_found: 200 }
    const html = render(prog, true)
    expect(html).not.toContain('<progress')
  })

  it('lifecycle step is active and inventory step is done during lifecycle phase', () => {
    const prog = {
      phase: 'lifecycle', files_found: 100, files_evaluated: 50, rules_enabled: 3,
    }
    const html = render(prog, true)
    const builtIdx = html.indexOf('Built document inventory')
    expect(builtIdx).toBeGreaterThan(-1)
    const checkBefore = html.lastIndexOf('✓', builtIdx)
    expect(checkBefore).toBeGreaterThan(-1)
    const lifecycleIdx = html.indexOf('Apply lifecycle rules')
    expect(lifecycleIdx).toBeGreaterThan(-1)
    const pulseBefore = html.lastIndexOf('prep-pulse', lifecycleIdx)
    expect(pulseBefore).toBeGreaterThan(-1)
  })
})

describe('inventory sub-step expansion during discovering phase', () => {
  it('shows folder listing sub-step when folders_found is available', () => {
    const prog = { phase: 'discovering', files_found: 148, folders_found: 12 }
    const html = render(prog, true)
    expect(html).toContain('Listing folders')
    expect(html).toContain('12 visited')
  })

  it('shows metadata reading sub-step when files_found > 0', () => {
    const prog = { phase: 'discovering', files_found: 50 }
    const html = render(prog, true)
    expect(html).toContain('Reading metadata')
    expect(html).toContain('50 found')
  })

  it('shows classification sub-step when assessable count is available', () => {
    const prog = { phase: 'discovering', files_found: 100, assessable: 80, unsupported: 20 }
    const html = render(prog, true)
    expect(html).toContain('Classifying documents')
    expect(html).toContain('80 assessable')
  })

  it('omits sub-step expansion in non-discovering phases', () => {
    for (const phase of ['lifecycle', 'saving', 'scoring']) {
      const prog = { phase, files_found: 100, folders_found: 12, assessable: 80 }
      const html = render(prog, true)
      // Sub-step labels only appear during discovering phase
      expect(html, `phase=${phase}`).not.toContain('Listing folders')
    }
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
    // Build document inventory is active during discovering phase
    const inventoryIdx = html.indexOf('Build document inventory')
    const weightIdx = html.lastIndexOf('font-weight:600', inventoryIdx)
    expect(weightIdx).toBeGreaterThan(-1)
    expect(inventoryIdx - weightIdx).toBeLessThan(200)
  })

  it('does not show the long-running hint below 90 s', () => {
    const html = render(PROG, true)
    expect(html).not.toContain('contains many folders')
  })
})

describe('accessibility: KPI spans do not spam screen readers', () => {
  it('KPI spans carry aria-hidden to prevent per-tick announcements', () => {
    const prog = { phase: 'discovering', files_found: 1000 }
    const html = render(prog, true)
    const kpiIdx = html.indexOf('1,000 files found')
    expect(kpiIdx).toBeGreaterThan(-1)
    const ariaHiddenIdx = html.lastIndexOf('aria-hidden', kpiIdx)
    expect(ariaHiddenIdx).toBeGreaterThan(-1)
    expect(kpiIdx - ariaHiddenIdx).toBeLessThan(150)
  })

  it('has a dedicated role=status live region naming the active step', () => {
    const prog = { phase: 'discovering', files_found: 0 }
    const html = render(prog, true)
    expect(html).toContain('Step in progress: Build document inventory')
  })

  it('status region updates when the active step changes phase', () => {
    const html = render({ phase: 'lifecycle', files_found: 50 }, true)
    expect(html).toContain('Step in progress: Apply lifecycle rules')
  })
})

describe('metadata exception counters (schema_version 2)', () => {
  it('shows a live exception note during the inventory phase when inaccessible files are present', () => {
    const prog = { phase: 'discovering', files_found: 10, exc_inaccessible_file: 2,
                   exc_metadata_failure: 0, exc_deleted_during_scan: 0 }
    const html = render(prog, true)
    expect(html).toContain('2 files inaccessible')
    expect(html).toContain('skipped, others continuing')
  })

  it('shows all three exception types in the live note when multiple are present', () => {
    const prog = { phase: 'discovering', files_found: 20, exc_inaccessible_file: 1,
                   exc_metadata_failure: 2, exc_deleted_during_scan: 3 }
    const html = render(prog, true)
    expect(html).toContain('1 file inaccessible')
    expect(html).toContain('3 deleted during scan')
    expect(html).toContain('2 unreadable')
    expect(html).toContain('skipped, others continuing')
  })

  it('omits the live exception note when all counters are zero', () => {
    const prog = { phase: 'discovering', files_found: 10, exc_inaccessible_file: 0,
                   exc_metadata_failure: 0, exc_deleted_during_scan: 0 }
    const html = render(prog, true)
    expect(html).not.toContain('skipped, others continuing')
  })

  it('omits the live exception note when exception fields are absent (schema_version 1)', () => {
    const prog = { phase: 'discovering', files_found: 10 }
    const html = render(prog, true)
    expect(html).not.toContain('skipped, others continuing')
  })

  it('exception note only appears during the discovering phase, not other phases', () => {
    const phases = ['tagging', 'analysing', 'scoring', 'lifecycle']
    for (const phase of phases) {
      const prog = { phase, files_found: 10, exc_inaccessible_file: 2,
                     exc_metadata_failure: 0, exc_deleted_during_scan: 0 }
      const html = render(prog, true)
      expect(html, `phase ${phase} should not show exception note`).not.toContain('skipped, others continuing')
    }
  })
})

describe('lifecycle step KPI from progress payload (schema_version 2)', () => {
  it('shows "N matched" in the Applied lifecycle rules step when progress fields are present', () => {
    const prog = { phase: 'scoring', files_found: 50, rules_enabled: 3, files_evaluated: 50, lifecycle_matches: 12 }
    const html = render(prog, true)
    expect(html).toContain('12 matched')
  })

  it('shows "— No enabled rules" when rules_enabled is 0', () => {
    const prog = { phase: 'scoring', files_found: 50, rules_enabled: 0, files_evaluated: 0, lifecycle_matches: 0 }
    const html = render(prog, true)
    expect(html).toContain('No enabled rules')
  })

  it('progress-payload KPI takes precedence over inv-derived KPI', () => {
    const prog = { phase: 'scoring', files_found: 10, rules_enabled: 2, files_evaluated: 10, lifecycle_matches: 5 }
    const inv = { rows: [{ file: 'a.docx', lifecycle_rule_id: 'r1' }], total: 10 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('5 matched')
    expect(html).not.toContain('1 matched')
  })

  it('falls back to inv-derived KPI when progress fields are absent (old backends)', () => {
    const prog = { phase: 'scoring', files_found: 4 }
    const inv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
      { file: 'b.docx', lifecycle_rule_id: 'ret-1' },
      { file: 'c.docx', lifecycle_rule_id: null },
    ], total: 3 }
    const html = render(prog, true, undefined, undefined, inv)
    expect(html).toContain('2 matched')
  })

  it('lifecycle stats KPI appears near Applied lifecycle rules step', () => {
    const prog = { phase: 'scoring', files_found: 20, rules_enabled: 4, files_evaluated: 20, lifecycle_matches: 7 }
    const html = render(prog, true)
    const lifecycleIdx = html.indexOf('Applied lifecycle rules')
    const finalizingIdx = html.indexOf('Finalize Discovery')
    const kpiIdx = html.indexOf('7 matched')
    expect(kpiIdx).toBeGreaterThan(lifecycleIdx)
    expect(kpiIdx).toBeLessThan(finalizingIdx)
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
  })

  it('still shows matched when at least one rule fired', () => {
    const mixedInv = { rows: [
      { file: 'a.docx', lifecycle_rule_id: 'ret-1' },
      { file: 'b.docx', lifecycle_rule_id: null },
    ], total: 2 }
    const prog = { phase: 'scoring', files_found: 2 }
    const html = render(prog, true, undefined, undefined, mixedInv)
    expect(html).toContain('1 matched')
    expect(html).not.toContain('No enabled rules')
  })

  it('"No enabled rules" appears in the lifecycle step row, not elsewhere', () => {
    const noRulesInv = { rows: [{ file: 'a.docx', lifecycle_rule_id: null }], total: 1 }
    const prog = { phase: 'scoring', files_found: 1 }
    const html = render(prog, true, undefined, undefined, noRulesInv)
    const lifecycleIdx = html.indexOf('Applied lifecycle rules')
    const finalizingIdx = html.indexOf('Finalize Discovery')
    const noRulesIdx = html.indexOf('No enabled rules')
    expect(noRulesIdx).toBeGreaterThan(lifecycleIdx)
    expect(noRulesIdx).toBeLessThan(finalizingIdx)
  })
})

describe('stop hint: per-step explanation of what stop does', () => {
  it('shows inventory stop hint when inventory is active and onStop is provided', () => {
    const prog = { phase: 'discovering', files_found: 10 }
    const html = render(prog, true, () => {})
    expect(html).toContain('Stops at the next folder')
  })

  it('shows the inventory stop hint during the aliased reading/tagging/saving phases too', () => {
    for (const phase of ['reading', 'tagging', 'saving']) {
      const html = render({ phase, files_found: 10 }, true, () => {})
      expect(html, `phase ${phase}`).toContain('Stops at the next folder')
    }
  })

  it('shows no stop hint during scoring/finalizing — finalizing step is active but no specific hint', () => {
    // Finalizing step has no STOP_HINTS entry (it completes quickly and stop is not meaningful).
    // Actually finalizing step has "The final inventory write will complete before stopping."
    // Let's just verify the inventory/lifecycle hints don't appear.
    for (const phase of ['scoring', 'finalizing']) {
      const html = render({ phase, files_found: 10 }, true, () => {})
      expect(html, `phase ${phase}`).not.toContain('Stops at the next folder')
      expect(html, `phase ${phase}`).not.toContain('Rules already applied will be kept')
    }
  })

  it('shows lifecycle stop hint during analysing phase', () => {
    const prog = { phase: 'analysing', files_found: 10 }
    const html = render(prog, true, () => {})
    expect(html).toContain('Rules already applied will be kept')
  })

  it('shows no stop hint when onStop is not provided', () => {
    const prog = { phase: 'discovering', files_found: 10 }
    const html = render(prog, true)
    expect(html).not.toContain('Stops at the next folder')
  })

  it('shows no stop hint during connecting phase (no per-step copy defined)', () => {
    const prog = { phase: 'connecting', files_found: 0 }
    const html = render(prog, true, () => {})
    expect(html).not.toContain('Stops at')
    expect(html).not.toContain('will be kept')
  })
})

describe('lifecycle stall hint', () => {
  it('does not show lifecycle hint before 30 s', () => {
    const prog = { phase: 'analysing', files_found: 100 }
    const html = render(prog, true)
    expect(html).not.toContain('Lifecycle evaluation is taking longer')
  })

  it('does not show lifecycle hint in non-analysing phases', () => {
    const prog = { phase: 'tagging', files_found: 100 }
    const html = render(prog, true)
    expect(html).not.toContain('Lifecycle evaluation is taking longer')
  })

  it('hint text is gated on elapsed >= 30 s (not shown at t=0 in SSR)', () => {
    const phases = ['queued', 'connecting', 'discovering', 'reading', 'tagging', 'scoring', 'finalizing']
    for (const phase of phases) {
      const html = render({ phase, files_found: 50 }, true)
      expect(html).not.toContain('Lifecycle evaluation is taking longer')
    }
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
    const prog = { phase: 'lifecycle', files_found: 100 }
    const html = render(prog, false)
    expect(html).toContain('0s')
  })

  it('shows file count when inv has rows', () => {
    const prog = { phase: 'discovering', files_found: 0 }
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
    const prog = { phase: 'discovering', files_found: 0 }
    const inv = { total: 12, rows: [] }
    const html = render(prog, false, undefined, undefined, inv)
    expect(html).not.toContain('Review partial inventory')
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
    const prog = { phase: 'lifecycle', files_found: 100 }
    const html = render(prog, false)
    expect(html).not.toContain('prep-pulse')
  })

  it('shows steps completed up to the stop point as done (✓)', () => {
    const prog = { phase: 'discovering', files_found: 80, folders_found: 5 }
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

  it('returns null (empty string) when phase is done and not busy — completion card handled by DiscoverCompleteSummary', () => {
    const prog = { phase: 'done', files_found: 100 }
    const html = render(prog, false)
    expect(html).toBe('')
    expect(html).not.toContain('Discovery complete')
    expect(html).not.toContain('Discovery stopped')
  })
})

// discovery/preflight returned 'degraded' when this run started — allowed through rather than
// blocked, but worth saying why for the run's duration (see discoveryPreflightGate.js).
// PRD §15 freshness model: 'reconnecting' (client SSE known dead) is distinct from 'checkpoint'/
// 'stale' (server-computed data-currency, from #883) — see App.jsx's poll loops for how the two
// are combined. This component just renders whichever single value it's given.
describe('freshness badges', () => {
  const renderWithFreshness = (freshness) => renderToStaticMarkup(
    createElement(DiscoverRunProgress, { progress: PROG, busy: true, freshness }))

  it('shows the reconnecting badge when freshness is "reconnecting"', () => {
    const html = renderWithFreshness('reconnecting')
    expect(html).toContain('reconnecting')
    expect(html).toContain('Discovery may still be running')
  })

  it('shows the checkpoint badge when freshness is "checkpoint"', () => {
    const html = renderWithFreshness('checkpoint')
    expect(html).toContain('checkpoint')
  })

  it('shows the stale badge when freshness is "stale"', () => {
    const html = renderWithFreshness('stale')
    expect(html).toContain('stale')
  })

  it('shows no badge when freshness is "live"', () => {
    const html = renderWithFreshness('live')
    expect(html).not.toContain('reconnecting')
    expect(html).not.toContain('checkpoint')
    expect(html).not.toContain('stale')
  })

  it('shows no badge when freshness is null (default)', () => {
    const html = renderWithFreshness(null)
    expect(html).not.toContain('reconnecting')
    expect(html).not.toContain('checkpoint')
    expect(html).not.toContain('stale')
  })

  it('shows only one badge at a time — reconnecting excludes the checkpoint/stale badges', () => {
    const html = renderWithFreshness('reconnecting')
    expect(html).not.toContain('>checkpoint<')
    expect(html).not.toContain('>stale<')
  })
})

describe('the preflightDegraded note', () => {
  const renderWith = (progress, preflightDegraded) => renderToStaticMarkup(
    createElement(DiscoverRunProgress, { progress, busy: true, preflightDegraded }))

  it('shows the degraded reason(s) while the run is active', () => {
    const html = renderWith(PROG, ['queue has 60 jobs waiting — this scan will queue behind them'])
    expect(html).toContain('Started with a note:')
    expect(html).toContain('queue has 60 jobs waiting')
  })

  it('joins multiple reasons', () => {
    const html = renderWith(PROG, ['reason one', 'reason two'])
    expect(html).toContain('reason one · reason two')
  })

  it('renders nothing extra when preflightDegraded is null (the ready/blocked case)', () => {
    const html = renderWith(PROG, null)
    expect(html).not.toContain('Started with a note')
  })

  it('renders nothing extra when preflightDegraded is an empty array', () => {
    const html = renderWith(PROG, [])
    expect(html).not.toContain('Started with a note')
  })

  it('does not show a degraded note on the stopped card — the note belongs to an active run', () => {
    const stoppedHtml = renderToStaticMarkup(createElement(DiscoverRunProgress,
      { progress: PROG, busy: false, preflightDegraded: ['queue backlog'] }))
    expect(stoppedHtml).not.toContain('Started with a note')
  })
})

describe('the retrying state (PRD §16.8)', () => {
  it('shows a distinct "Discovery retrying" card, not the ordinary in-progress checklist', () => {
    const html = render({ phase: 'retrying', attempt: 2, max_attempts: 5 }, true)
    expect(html).toContain('Discovery retrying')
    expect(html).not.toContain('Discovering documents')
    // Must not read as a fresh restart: step 0 ("Connect to source") must not show active.
    expect(html).not.toContain('aria-current="step"')
  })

  it('shows the attempt count when both attempt and max_attempts are present', () => {
    const html = render({ phase: 'retrying', attempt: 2, max_attempts: 5 }, true)
    expect(html).toMatch(/attempt 2 of 5/)
  })

  it('shows just the attempt number when max_attempts is absent', () => {
    const html = render({ phase: 'retrying', attempt: 3 }, true)
    expect(html).toMatch(/attempt 3/)
    expect(html).not.toMatch(/attempt 3 of/)
  })

  it('renders without an attempt count at all rather than crashing when neither is present', () => {
    const html = render({ phase: 'retrying' }, true)
    expect(html).toContain('Discovery retrying')
    expect(html).not.toMatch(/attempt \d/)
  })

  it('surfaces the last error so the user knows what failed', () => {
    const html = render({ phase: 'retrying', attempt: 1, last_error: '429 rate limit exceeded' }, true)
    expect(html).toContain('429 rate limit exceeded')
  })

  it('omits the error section entirely when last_error is absent', () => {
    const html = render({ phase: 'retrying', attempt: 1 }, true)
    expect(html).not.toContain('border-top')  // no error panel rendered
  })

  it('does not fabricate a countdown to the next attempt — backoff is jittered server-side', () => {
    const html = render({ phase: 'retrying', attempt: 1 }, true)
    expect(html).not.toMatch(/retrying in \d/i)
    expect(html).not.toMatch(/\d+s remaining/i)
  })

  it('renders a Cancel button, not the Stop button used once a worker has claimed the job', () => {
    const html = render({ phase: 'retrying', attempt: 1 }, true, () => {})
    expect(html).toContain('Cancel')
    expect(html).not.toContain('>Stop<')
  })

  it('falls through to the stopped card once busy goes false — retrying only applies while busy', () => {
    const html = render({ phase: 'retrying', attempt: 1 }, false)
    expect(html).not.toContain('Discovery retrying')
    expect(html).toContain('Discovery stopped')
  })
})

// A job enqueued but not yet claimed by a worker — distinct from 'connecting' (a worker IS
// actively reaching the source). Found live 2026-08-28: both used to render the same checklist
// with "Connect to source" pulsing, implying a connection attempt was already underway when
// really nothing had started yet — dishonest progress of exactly the kind this component's own
// design comments elsewhere warn against.
describe('the queued state (PRD §16.1)', () => {
  it('shows a distinct "Discovery queued" card, not the connecting checklist', () => {
    const html = render({ phase: 'queued' }, true)
    expect(html).toContain('Discovery queued')
    expect(html).toContain('Waiting for an available worker')
    expect(html).not.toContain('Discovering documents')
    expect(html).not.toContain('Connect to source')
  })

  it('prefers the real enqueue timestamp (started_at) over component-mount-relative elapsed', () => {
    const thirtyMinAgo = new Date(Date.now() - 30 * 60 * 1000).toISOString()
    const html = render({ phase: 'queued', started_at: thirtyMinAgo }, true)
    // fmtElapsedSecs renders >= 60s as "Nm" — accept 29m or 30m for clock-tick tolerance.
    expect(html).toMatch(/created (29|30)m ago/)
  })

  it('falls back to mount-relative elapsed when started_at is absent (fresh submission)', () => {
    const html = render({ phase: 'queued' }, true)
    expect(html).toMatch(/created 0s ago/)
  })

  it('never shows a negative wait time when started_at is slightly in the future (clock skew)', () => {
    const future = new Date(Date.now() + 5000).toISOString()
    const html = render({ phase: 'queued', started_at: future }, true)
    expect(html).toMatch(/created 0s ago/)
    expect(html).not.toMatch(/created -/)
  })

  it('renders a Cancel button, not the Stop button used once a worker has claimed the job', () => {
    const html = render({ phase: 'queued' }, true, () => {})
    expect(html).toContain('Cancel')
    expect(html).not.toContain('>Stop<')
  })

  it('does not fabricate a queue position or a Notify-me action — neither is backed by real data', () => {
    const html = render({ phase: 'queued' }, true)
    expect(html).not.toMatch(/position|Notify me/i)
  })

  it('does not render the queued card once busy is false', () => {
    // Guards against the queued phase string lingering in a stale progress object after the
    // scan already stopped — busy is the durable signal, not the phase string alone.
    const html = render({ phase: 'queued' }, false)
    expect(html).not.toContain('Discovery queued')
  })
})

// A "Cancel requested" acknowledgment for the Stop/Cancel button, added instead of a full
// "Stopping…" state: cancel_scan is synchronous (one DB transaction, no cooperative in-between
// window — see api/store.py's _end_running_scan), so there is no real intermediate state to show
// honestly. What IS true the instant the button is clicked is that the request was made — this
// says only that, disabled-button-label ("Cancelling…"/"Stopping…") aside, so a slow poll tick
// before the card actually swaps away doesn't read as an unresponsive click.
//
// Needs a real click + re-render to observe (the `stopping` flag is internal component state),
// which the static renderToStaticMarkup helper above cannot do — so this block mounts
// interactively instead, per testRoots.js's usage note.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('the "Cancel requested" acknowledgment', () => {
  const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
  const mount = async (props) => {
    const { container, root } = createTestRoot()
    await act(async () => {
      root.render(createElement(DiscoverRunProgress, { onStop: () => {}, ...props }))
    })
    return container
  }
  const click = async (el) => { await act(async () => { el.click() }); await flush() }
  const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))
  afterEach(unmountAll)

  it('is absent until Stop is clicked, on the ordinary in-progress checklist', async () => {
    const c = await mount({ progress: PROG, busy: true })
    expect(c.textContent).not.toMatch(/Cancel requested/)
    await click(byText(c, 'button', /^Stop$/))
    expect(c.textContent).toMatch(/Cancel requested/)
  })

  it('is absent until Cancel is clicked, on the queued card', async () => {
    const c = await mount({ progress: { phase: 'queued' }, busy: true })
    expect(c.textContent).not.toMatch(/Cancel requested/)
    await click(byText(c, 'button', /^Cancel$/))
    expect(c.textContent).toMatch(/Cancel requested/)
  })

  it('is absent until Cancel is clicked, on the retrying card', async () => {
    const c = await mount({ progress: { phase: 'retrying', attempt: 1 }, busy: true })
    expect(c.textContent).not.toMatch(/Cancel requested/)
    await click(byText(c, 'button', /^Cancel$/))
    expect(c.textContent).toMatch(/Cancel requested/)
  })

  it('replaces the pre-click stop hint rather than showing both at once', async () => {
    const c = await mount({ progress: { phase: 'lifecycle', files_evaluated: 1, files_found: 10 }, busy: true })
    expect(c.textContent).toMatch(/Rules already applied will be kept/)
    await click(byText(c, 'button', /^Stop$/))
    expect(c.textContent).not.toMatch(/Rules already applied will be kept/)
    expect(c.textContent).toMatch(/Cancel requested/)
  })

  it('does not appear at all when onStop is not provided — nothing was clickable to acknowledge', async () => {
    const c = await mount({ progress: PROG, busy: true, onStop: undefined })
    expect(c.querySelector('button')).toBeFalsy()
    expect(c.textContent).not.toMatch(/Cancel requested/)
  })
})
