import { integrityAffects } from './remediationSnapshot.js'

const valid = value => Number.isSafeInteger(value) && value >= 0
const number = value => valid(value) ? value.toLocaleString() : 'Unavailable'
const dollars = value => valid(value) ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(value / 1000000) : 'Unavailable'

// A terminal document run is not a claim that all findings were fixed or delivered.
export default function RemediationCompletionSummary({ snapshot, view, exact = false, reviewHref, releaseHref, onInspect }) {
  if (!snapshot?.terminal) return null
  const rec = snapshot.finding_reconciliation || {}
  const verified = exact ? rec.resolved_verified : integrityAffects(snapshot, 'fixes') ? undefined : snapshot.fixes?.verified
  const review = exact ? rec.awaiting_review : integrityAffects(snapshot, 'review') ? undefined : snapshot.review?.items
  const failed = integrityAffects(snapshot, 'documents') ? undefined : snapshot.documents?.failed
  const awaitingRelease = integrityAffects(snapshot, 'delivery') ? undefined : snapshot.delivery?.awaiting_release
  const spending = view?.available === true ? view.spending : null
  const stopped = ['failed', 'cancelled'].includes(snapshot.state)
  const next = stopped || failed > 0
    ? 'Inspect unsuccessful work before deciding what to retry.'
    : review > 0 ? 'Review the proposed changes and provide any missing content.'
      : awaitingRelease > 0 ? 'Inspect corrected copies in Release before delivery.'
        : 'Inspect the recorded outcomes for any remaining or unassessed work.'
  return <section className="wf-completion" aria-label="Remediation run summary">
    <div className="wf-section-head"><h4>{stopped ? 'Run stopped · results retained' : 'Automatic processing finished'}</h4><span>Recorded results</span></div>
    <div className="wf-metrics">
      <div><span>{exact ? 'Fixed and checked · findings' : 'Verified changes · all origins'}</span><strong>{number(verified)}</strong></div>
      <div><span>{exact ? 'Awaiting your review · findings' : 'Review items · not findings'}</span><strong>{number(review)}</strong></div>
      <div><span>Settled AI charges</span><strong>{dollars(spending?.spent_units)}</strong></div>
    </div>
    <p>{valid(failed) && failed > 0 && <span>{number(failed)} failed documents. </span>}{valid(awaitingRelease) && awaitingRelease > 0 && <span>{number(awaitingRelease)} corrected copies awaiting Release. </span>}Finished processing does not mean every finding was fixed.</p>
    {(spending?.held_units > 0 || spending?.blocked) && <p className="wf-note">{spending?.held_units > 0 && <>{dollars(spending.held_units)} remains reserved; the final charge is not settled. </>}{spending?.blocked && 'Further AI spending is on hold pending reconciliation.'}</p>}
    <div className="wf-completion-next"><div><strong>Next action</strong><p>{next}</p></div><div className="wf-completion-actions">
      {review > 0 && reviewHref && <a href={reviewHref}>Open Review</a>}
      {awaitingRelease > 0 && releaseHref && <a href={releaseHref}>Inspect Release</a>}
      {onInspect && <button type="button" onClick={onInspect}>Inspect outcomes</button>}
    </div></div>
  </section>
}
