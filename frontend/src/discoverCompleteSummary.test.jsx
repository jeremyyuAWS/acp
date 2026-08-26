/**
 * DiscoverCompleteSummary — the card shown after discovery finishes.
 *
 * Shows an immutable snapshot of what was found (eligible, non-assessable, locked, excluded)
 * plus a prominent "Continue to Assessment →" CTA wired to onAdvance. Tests verify the
 * counts appear correctly and the CTA is disabled when pendingActions or needsAck is set.
 */
import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoverCompleteSummary from './DiscoverCompleteSummary.jsx'

const render = (props) =>
  renderToStaticMarkup(createElement(DiscoverCompleteSummary, props))

const BASE = {
  discoveredCount: 200,
  assessableCount: 170,
  metadataOnlyCount: 10,
  unsupportedCount: 10,
  eligibilityUnknownCount: 0,
  lockedCount: 5,
  excludedCount: 0,
  lifecycleRulesCount: 3,
  onAdvance: null,
  pendingActions: 0,
  needsAck: false,
}

describe('DiscoverCompleteSummary renders completion state', () => {
  it('shows "Discovery complete" heading', () => {
    expect(render(BASE)).toContain('Discovery complete')
  })

  it('shows assessable count with its label', () => {
    const html = render(BASE)
    expect(html).toContain('170')
    expect(html).toContain('assessable')
  })

  it('shows metadata-only count and label when > 0', () => {
    const html = render(BASE)
    expect(html).toContain('10')
    expect(html).toContain('metadata-only')
  })

  it('shows unsupported count and label when > 0', () => {
    const html = render({ ...BASE, unsupportedCount: 8 })
    expect(html).toContain('8')
    expect(html).toContain('unsupported')
  })

  it('shows locked count and label', () => {
    const html = render(BASE)
    expect(html).toContain('5')
    expect(html).toContain('could not be opened')
  })

  it('shows lifecycle rules count', () => {
    const html = render(BASE)
    expect(html).toContain('3 lifecycle rules matched')
  })

  it('omits metadata-only row when count is 0', () => {
    const html = render({ ...BASE, metadataOnlyCount: 0 })
    expect(html).not.toContain('metadata-only')
  })

  it('omits unsupported row when count is 0', () => {
    const html = render({ ...BASE, unsupportedCount: 0 })
    expect(html).not.toContain('unsupported')
  })

  it('omits locked row when count is 0', () => {
    const html = render({ ...BASE, lockedCount: 0 })
    expect(html).not.toContain('could not be opened')
  })

  it('omits lifecycle rules when count is 0', () => {
    const html = render({ ...BASE, lifecycleRulesCount: 0 })
    expect(html).not.toContain('lifecycle rules')
  })

  it('omits lifecycle rules when count is null', () => {
    const html = render({ ...BASE, lifecycleRulesCount: null })
    expect(html).not.toContain('lifecycle rules')
  })

  it('shows "Continue to Assessment" CTA', () => {
    const html = render(BASE)
    expect(html).toContain('Continue to Assessment')
  })

  it('shows elapsed time when startedAt and discoveredAt are provided', () => {
    const html = render({
      ...BASE,
      startedAt: '2026-08-26T10:00:00Z',
      discoveredAt: '2026-08-26T10:03:18Z',
    })
    expect(html).toContain('3m 18s')
  })

  it('omits elapsed time when timestamps are absent', () => {
    const html = render(BASE)
    expect(html).not.toMatch(/\d+m \d+s/)
  })

  it('shows inventory delta when provided', () => {
    const html = render({
      ...BASE,
      inventoryDelta: { new: 224, updated: 61, unchanged: 963 },
    })
    expect(html).toContain('Inventory')
    expect(html).toContain('224')
    expect(html).toContain('new')
    expect(html).toContain('61')
    expect(html).toContain('updated')
    expect(html).toContain('963')
    expect(html).toContain('unchanged')
  })

  it('omits inventory delta section when not provided', () => {
    const html = render(BASE)
    expect(html).not.toContain('Inventory:')
  })
})

describe('CTA gating', () => {
  it('CTA is not disabled when no pending actions and no ack needed', () => {
    const html = render({ ...BASE, pendingActions: 0, needsAck: false })
    expect(html).not.toMatch(/disabled/)
  })

  it('CTA is disabled when pendingActions > 0', () => {
    const html = render({ ...BASE, pendingActions: 3 })
    expect(html).toMatch(/disabled/)
    expect(html).toContain('pending action')
  })

  it('CTA is disabled when needsAck is true', () => {
    const html = render({ ...BASE, needsAck: true })
    expect(html).toMatch(/disabled/)
    expect(html).toContain('recommendations')
  })
})

describe('singular lifecycle rule label', () => {
  it('uses singular "lifecycle rule" when count is 1', () => {
    const html = render({ ...BASE, lifecycleRulesCount: 1 })
    expect(html).toContain('1 lifecycle rule matched')
    expect(html).not.toContain('1 lifecycle rules')
  })
})

describe('lifecycle action breakdown', () => {
  it('shows archive candidates when provided and > 0', () => {
    const html = render({ ...BASE, archiveCandidates: 12 })
    expect(html).toContain('12')
    expect(html).toContain('Archive Candidate')
  })

  it('shows delete candidates when provided and > 0', () => {
    const html = render({ ...BASE, deleteCandidates: 1 })
    expect(html).toContain('1 Delete Candidate')
  })

  it('uses plural Delete Candidates when count > 1', () => {
    const html = render({ ...BASE, deleteCandidates: 5 })
    expect(html).toContain('5 Delete Candidates')
  })

  it('shows tagged count when provided and > 0', () => {
    const html = render({ ...BASE, tagged: 8 })
    expect(html).toContain('8 tagged')
  })

  it('omits action breakdown items when counts are 0 or null', () => {
    const html = render({ ...BASE, archiveCandidates: 0, deleteCandidates: null, tagged: 0 })
    expect(html).not.toContain('Archive Candidate')
    expect(html).not.toContain('Delete Candidate')
    expect(html).not.toContain('tagged')
  })
})

describe('exception summary', () => {
  it('shows inaccessible count when > 0', () => {
    const html = render({ ...BASE, excInaccessible: 3 })
    expect(html).toContain('3 inaccessible')
    expect(html).toContain('skipped')
  })

  it('shows unreadable count when > 0', () => {
    const html = render({ ...BASE, excMetadataFailure: 2 })
    expect(html).toContain('2 unreadable')
  })

  it('shows deleted-during-scan count when > 0', () => {
    const html = render({ ...BASE, excDeleted: 1 })
    expect(html).toContain('1 deleted during scan')
  })

  it('omits exception summary when all exception counts are absent or zero', () => {
    const html = render({ ...BASE, excInaccessible: 0, excMetadataFailure: null, excDeleted: null })
    expect(html).not.toContain('inaccessible')
    expect(html).not.toContain('unreadable')
    expect(html).not.toContain('deleted during scan')
  })
})

describe('folder count in discovered total', () => {
  it('shows folder count when folderCount > 0', () => {
    const html = render({ ...BASE, folderCount: 12 })
    expect(html).toContain('12 folders')
  })

  it('uses singular folder when count is 1', () => {
    const html = render({ ...BASE, folderCount: 1 })
    expect(html).toContain('1 folder')
    expect(html).not.toContain('1 folders')
  })

  it('omits folder count when not provided', () => {
    const html = render(BASE)
    expect(html).not.toContain('folders')
  })
})
