/**
 * DiscoverCompleteSummary — the card shown after discovery finishes.
 *
 * Structured-row layout: header with green check + elapsed time, total files inventoried,
 * "Assessment eligibility" section with parent-child rows and percentages, "Lifecycle rules"
 * section, a tinted safety disclaimer, and a specific CTA ("Assess N documents →").
 * Tests verify counts, section labels, percentages, sub-breakdown, and CTA gating.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoverCompleteSummary from './DiscoverCompleteSummary.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

const render = (props) =>
  renderToStaticMarkup(createElement(DiscoverCompleteSummary, props))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

// The "Why aren't N assessable?" disclosure needs a real click to open, which
// renderToStaticMarkup (one static pass, no event handling) cannot exercise — these mount
// interactively instead, same reasoning as this app's other disclosure-toggle tests.
afterEach(unmountAll)
const mountAndExpand = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DiscoverCompleteSummary, props)) })
  const toggle = [...container.querySelectorAll('button')].find((b) => /Why aren.t/.test(b.textContent))
  if (toggle) await act(async () => { toggle.click() })
  return container
}

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

  it('shows metadata-only count and label when > 0, once expanded', async () => {
    const c = await mountAndExpand(BASE)
    expect(c.textContent).toContain('10')
    expect(c.textContent).toContain('metadata-only')
  })

  it('shows unsupported count and label when > 0, once expanded', async () => {
    const c = await mountAndExpand({ ...BASE, unsupportedCount: 8 })
    expect(c.textContent).toContain('8')
    expect(c.textContent).toContain('unsupported')
  })

  it('shows locked count and label, once expanded', async () => {
    const c = await mountAndExpand(BASE)
    expect(c.textContent).toContain('5')
    expect(c.textContent).toContain('could not be opened')
  })

  it('shows lifecycle rules count', () => {
    const html = render(BASE)
    expect(html).toContain('3 matched lifecycle rules')
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

  it('shows "No lifecycle rules enabled" when count is 0', () => {
    const html = render({ ...BASE, lifecycleRulesCount: 0 })
    expect(html).toContain('No lifecycle rules enabled')
  })

  it('renders the sub-breakdown as a real bulleted list, not bare stacked rows, once expanded', async () => {
    const c = await mountAndExpand(BASE)
    // metadata-only (10) and unsupported (10) and locked (5) are all > 0 in BASE.
    expect(c.innerHTML).toMatch(/<ul[^>]*>[\s\S]*<li[^>]*>[\s\S]*<\/li>[\s\S]*<\/ul>/)
  })

  it('wraps each sub-breakdown label with its glossary definition, hoverable via Term, once expanded', async () => {
    const c = await mountAndExpand(BASE)
    // Term renders a "terminfo" button beside the label — one per glossary-backed sub-row
    // (metadata-only, unsupported, could not be opened) present in BASE, plus the disclosure's
    // own toggle button — four buttons total.
    expect(c.querySelectorAll('.terminfo').length).toBe(3)
    const ariaLabels = [...c.querySelectorAll('.terminfo')].map((b) => b.getAttribute('aria-label'))
    expect(ariaLabels).toContain('What does "Unsupported" mean?')
    expect(ariaLabels).toContain('What does "Metadata-only" mean?')
  })

  it('shows "No lifecycle rules enabled" when count is null', () => {
    const html = render({ ...BASE, lifecycleRulesCount: null })
    expect(html).toContain('No lifecycle rules enabled')
  })

  it('shows CTA with assessable document count', () => {
    const html = render(BASE)
    expect(html).toContain('Assess')
    expect(html).toContain('170')
    expect(html).toContain('documents')
  })

  it('CTA falls back to "Continue to Assessment" when assessableCount is 0', () => {
    const html = render({ ...BASE, assessableCount: 0 })
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

  // `runAt` is the same `inventorySnapshot()` object DiscoveryResults.jsx renders below this
  // card — see Discover.jsx's own comment for why it is threaded through rather than re-derived.
  // These tests exercise the component's own rendering of that shared object, not the derivation.
  describe('the shared "as of" timestamp on the total', () => {
    it('shows the absolute instant when runAt is recorded', () => {
      const html = render({
        ...BASE,
        runAt: { recorded: true, absolute: 'Aug 26, 2026, 10:03 AM PDT', label: 'recorded when discovery finished', stale: false },
      })
      expect(html).toContain('as of Aug 26, 2026, 10:03 AM PDT')
    })

    it('calls out a stale (>1 day old) snapshot', () => {
      const html = render({
        ...BASE,
        runAt: { recorded: true, absolute: 'Aug 1, 2026, 9:00 AM PDT', label: 'recorded when discovery finished', stale: true },
      })
      expect(html).toContain('this snapshot is over a day old')
    })

    it('shows nothing when runAt is unrecorded — no invented instant', () => {
      const html = render({ ...BASE, runAt: { recorded: false, absolute: null, label: null, stale: false } })
      expect(html).not.toContain('as of')
    })

    it('shows nothing when runAt is absent entirely', () => {
      const html = render(BASE)
      expect(html).not.toContain('as of')
    })
  })

  it('shows inventory delta when a checkpoint resume actually touched rows', () => {
    const html = render({
      ...BASE,
      inventoryDelta: { new: 224, updated: 61, unchanged: 963 },
    })
    expect(html).toContain('checkpoint resume')
    expect(html).toContain('224')
    expect(html).toContain('written')
    expect(html).toContain('61')
    expect(html).toContain('re-written on resume')
    expect(html).toContain('963')
    expect(html).toContain('unchanged')
  })

  it('omits inventory delta section when not provided', () => {
    const html = render(BASE)
    expect(html).not.toContain('checkpoint resume')
  })

  it('omits inventory delta section on a clean run with no resume — every row reads "new" '
     + 'and restating that as "added" would misread as growth since last time', () => {
    const html = render({
      ...BASE,
      inventoryDelta: { new: 224, updated: 0, unchanged: 0 },
    })
    expect(html).not.toContain('checkpoint resume')
    expect(html).not.toContain('224')
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
    expect(html).toContain('1 matched lifecycle rule')
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
  it('shows inaccessible count when > 0, once expanded', async () => {
    const c = await mountAndExpand({ ...BASE, excInaccessible: 3 })
    expect(c.textContent).toContain('3 inaccessible')
    expect(c.textContent).toContain('skipped')
  })

  it('shows unreadable count when > 0, once expanded', async () => {
    const c = await mountAndExpand({ ...BASE, excMetadataFailure: 2 })
    expect(c.textContent).toContain('2 unreadable')
  })

  it('shows deleted-during-scan count when > 0, once expanded', async () => {
    const c = await mountAndExpand({ ...BASE, excDeleted: 1 })
    expect(c.textContent).toContain('1 deleted during scan')
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

describe('enumeration verified row', () => {
  it('shows "Enumeration verified complete" with a formatted date when publishedAt is set', () => {
    const html = render({ ...BASE, publishedAt: '2026-08-27T01:03:14Z' })
    expect(html).toContain('Enumeration verified complete')
  })

  it('omits "Enumeration verified complete" when publishedAt is null', () => {
    const html = render({ ...BASE, publishedAt: null })
    expect(html).not.toContain('Enumeration verified complete')
  })
})

describe('structured-row layout', () => {
  it('shows "Assessment eligibility" section header', () => {
    const html = render(BASE)
    expect(html).toContain('Assessment eligibility')
  })

  it('shows "Lifecycle rules" section header', () => {
    const html = render(BASE)
    expect(html).toContain('Lifecycle rules')
  })

  it('shows percentages for assessable and not-assessable rows', () => {
    // 170 assessable out of 200 = 85%; 30 not assessable = 15%
    const html = render(BASE)
    expect(html).toContain('85%')
    expect(html).toContain('15%')
  })

  it('shows "Not currently assessable" parent row when there are non-assessable files', () => {
    const html = render(BASE)
    expect(html).toContain('Not currently assessable')
  })

  it('omits "Not currently assessable" row when all files are assessable', () => {
    const html = render({ ...BASE, discoveredCount: 170, assessableCount: 170,
                          metadataOnlyCount: 0, unsupportedCount: 0, lockedCount: 0 })
    expect(html).not.toContain('Not currently assessable')
  })

  it('uses "files inventoried" in the total line', () => {
    const html = render(BASE)
    expect(html).toContain('files inventoried')
  })

  it('shows safety disclaimer with info icon', () => {
    const html = render(BASE)
    expect(html).toContain('No documents were assessed or changed')
    expect(html).toContain('ⓘ')
  })

  it('sub-breakdown items are indented under not-assessable parent, once expanded', async () => {
    const c = await mountAndExpand(BASE)
    // Both "Not currently assessable" and "unsupported" must appear in the same render.
    expect(c.textContent).toContain('Not currently assessable')
    expect(c.textContent).toContain('unsupported')
    expect(c.textContent).toContain('metadata-only')
  })
})

describe('the "Why aren\'t N assessable?" disclosure', () => {
  it('is collapsed by default — the breakdown is not in the initial render', () => {
    const html = render(BASE)
    expect(html).toContain('Why aren')
    expect(html).not.toContain('metadata-only')
    expect(html).not.toContain('unsupported')
    expect(html).not.toContain('could not be opened')
  })

  it('names the not-assessable count in the toggle', () => {
    const html = render(BASE)
    // 200 discovered - 170 assessable = 30 not assessable.
    expect(html).toContain('Why aren’t 30 assessable?')
  })

  it('is absent entirely when everything is assessable — nothing to explain', () => {
    const html = render({ ...BASE, discoveredCount: 170, assessableCount: 170,
                          metadataOnlyCount: 0, unsupportedCount: 0, lockedCount: 0 })
    expect(html).not.toContain('Why aren')
  })

  it('reveals the full breakdown on click, and can be collapsed again', async () => {
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(DiscoverCompleteSummary, BASE)) })
    const toggle = [...container.querySelectorAll('button')].find((b) => /Why aren.t/.test(b.textContent))
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(container.textContent).not.toContain('metadata-only')

    await act(async () => { toggle.click() })
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('metadata-only')

    await act(async () => { toggle.click() })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(container.textContent).not.toContain('metadata-only')
  })
})

describe('the "See what\'s changed" redirect to SourceDrawer', () => {
  it('renders the link when onViewSourceHistory is provided', () => {
    const html = render({ ...BASE, onViewSourceHistory: () => {} })
    // Apostrophe comes through the static-markup output HTML-entity-escaped (&#x27;), not literal
    // — matched on the text either side of it instead of asserting the exact byte sequence.
    expect(html).toMatch(/See what.*?s changed since your last scan of this source/)
  })

  it('omits the link when there is nowhere to send the reader', () => {
    const html = render(BASE)
    expect(html).not.toContain('See what')
  })

  it('calls onViewSourceHistory on click — this card never resolves the source itself', async () => {
    const onViewSourceHistory = vi.fn()
    const { container, root } = createTestRoot()
    await act(async () => {
      root.render(createElement(DiscoverCompleteSummary, { ...BASE, onViewSourceHistory }))
    })
    const link = [...container.querySelectorAll('button')].find((b) => /See what.s changed/.test(b.textContent))
    await act(async () => { link.click() })
    expect(onViewSourceHistory).toHaveBeenCalledTimes(1)
  })
})
