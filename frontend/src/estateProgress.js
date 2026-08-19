// Estate coverage FUNNEL PROGRESS (funnel stages 4–9) computed from the scored file rows — each a
// REAL count, never a projection. Shared by the Overview and Discover tabs so their funnels can never
// disagree about the same estate. Kept out of estateFunnel.js on purpose: that module is pure and
// dependency-free; this one depends on the file-shape helpers (docStatus / assessCoverage).
import { analysedCount } from './docStatus.js'
import { remediationEligibleCount } from './assessCoverage.js'

const isReview = (i) => String(i?.severity || '').toUpperCase() === 'REVIEW'

/** Funnel progress from the file rows.
 *  - assessed: documents actually opened & scored (a Discover-only scan leaves this low).
 *  - remediation_eligible: FINDING-level — documents with at least one auto/AI-fixable finding. A
 *    document whose every open finding is human-only is assessable but NOT remediable.
 *  - human_review: documents carrying at least one REVIEW-lane finding (assessed-for-review). */
export function estateProgressFromFiles(files) {
  const fs = files || []
  return {
    assessed: analysedCount(fs),
    issues: fs.filter((f) => (f.issues || []).length).length,
    remediation_eligible: remediationEligibleCount(fs),
    remediated: fs.filter((f) => f.remediated_at || f.drive_write_url).length,
    human_review: fs.filter((f) => (f.issues || []).some(isReview)).length,
    published: fs.filter((f) => f.published_at).length,
  }
}
