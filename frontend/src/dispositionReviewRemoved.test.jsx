/**
 * The disposition review queue is NOT mounted in Discover, and that is deliberate.
 *
 * Removed on request 2026-09-02. What it showed on a real estate is the argument: 200 rows of
 * `_3d.cpython-314.pyc`, `_a_n_k_r.py`, `.pfb` font files — every one "Active · No reason
 * recorded", grouped under "No rule recorded · no proposed action". A queue whose purpose is
 * deciding disposition was listing the whole estate, none of which any rule had proposed
 * anything for, directly above the "Lifecycle results · supported documents" section that
 * already answers the same question about the files that actually matter.
 *
 * The COMPONENT stays (CLAUDE.md's standing instruction: delete the mount, not the code, so
 * restoring it is one commit). This file exists because the other half of that instruction is
 * that an orphan nobody wrote down reads as shipped: DispositionReviewWorkspace returns markup
 * for any props it is given, so "never mounted" and "mounted with the wrong props" look
 * identical from the outside and every suite stays green either way.
 *
 * If it is mounted again, this test fails — which is the reminder to delete this file rather
 * than a regression.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const sources = readdirSync(here).filter((f) => /\.jsx?$/.test(f) && !/\.test\.jsx?$/.test(f))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('the disposition review queue is deliberately unmounted', () => {
  it('is rendered by no screen', () => {
    const mounts = sources
      .filter((f) => f !== 'DispositionReviewWorkspace.jsx')
      .filter((f) => /<DispositionReviewWorkspace\b/.test(read(f)))
    expect(mounts, `DispositionReviewWorkspace is mounted again by ${mounts.join(', ')} — if that `
      + 'is intended, delete this test; it exists to stop the queue returning by accident')
      .toEqual([])
  })

  it('is imported by no screen either', () => {
    // A live import with no mount is how ScopeFunnel and ProcessingDetails read as wired to
    // anyone grepping, while rendering nothing (CLAUDE.md, 2026-08-30 audit).
    const importers = sources
      .filter((f) => f !== 'DispositionReviewWorkspace.jsx')
      .filter((f) => /from '\.\/DispositionReviewWorkspace\.jsx'/.test(read(f)))
    expect(importers).toEqual([])
  })

  it('kept the component and its evidence panel, so restoring it is one commit', () => {
    // The instruction is delete the MOUNT, not the code. If someone deletes these instead, the
    // reversibility this trade was made for is gone and this says so.
    expect(sources).toContain('DispositionReviewWorkspace.jsx')
    expect(sources).toContain('LifecycleEvidencePanel.jsx')
  })

  it('leaves no control in Discover pointing at the removed section', () => {
    // The estate summary's per-count filter and its "Review disposition queue" button both
    // scrolled to #lifecycle-review. A button that survives its destination is worse than no
    // button: keyboard-reachable, announced as actionable, and it answers nothing.
    const discover = read('DiscoveryLifecycleResults.jsx')
    expect(discover).not.toMatch(/lifecycle-review/)
    expect(discover).not.toMatch(/reviewStatus|reviewPolicy|reviewCandidates/)
  })
})

describe('the summary and ledger degrade to plain figures', () => {
  it('renders counts as text when nothing is listening', async () => {
    const { createElement } = await import('react')
    const { renderToStaticMarkup } = await import('react-dom/server')
    const LifecycleEstateSummary = (await import('./LifecycleEstateSummary.jsx')).default
    const html = renderToStaticMarkup(createElement(LifecycleEstateSummary, {
      summary: {
        total: 10, reconciled_total: 10, assessment_excluded: 3,
        counts: { active: 5, already_archived: 1, archive_candidate: 2, delete_candidate: 0,
          deleted: 0, exempt: 1, reactivated: 0, unevaluable: 1, failed: 0 },
      },
    }))
    // The numbers are still there — this is about the control, not the information.
    expect(html).toContain('Archive candidate')
    expect(html).not.toContain('Review disposition queue')
    expect(html).not.toMatch(/class="linklike"/)
  })

  it('still offers them when a caller does listen, so the component is not crippled', async () => {
    const { createElement } = await import('react')
    const { renderToStaticMarkup } = await import('react-dom/server')
    const LifecycleEstateSummary = (await import('./LifecycleEstateSummary.jsx')).default
    const html = renderToStaticMarkup(createElement(LifecycleEstateSummary, {
      summary: {
        total: 1, reconciled_total: 1, assessment_excluded: 0,
        counts: { active: 1, already_archived: 0, archive_candidate: 0, delete_candidate: 0,
          deleted: 0, exempt: 0, reactivated: 0, unevaluable: 0, failed: 0 },
      },
      onSelect: () => {}, onReview: () => {},
    }))
    expect(html).toContain('Review disposition queue')
    expect(html).toMatch(/class="linklike"/)
  })
})
