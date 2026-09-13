import WorkflowOutcomeTiles from './WorkflowOutcomeTiles.jsx'
import { releaseBatchDomain, releaseBatchProgress } from './releaseBatchProgress.js'

/** Read-only saved-plan presentation; never authorizes or enqueues publication. */
export default function AutomaticPublicationStatus({ authorization, pending = false, error = '', destinationLabel, onOpen, compact = false, onFilter }) {
  const raw = authorization?.batch_progress
  const batch = raw?.authorization_id === authorization?.id ? releaseBatchProgress({stage:'release',release_batch_progress:raw}) : null
  const domain = releaseBatchDomain(batch)
  const active = authorization?.id
  const complete = batch?.available === true && batch.remaining === 0 && batch.status === 'completed'
  return <section className="panel" aria-label="Automatic publication status" data-scope-id={batch?.scope_id} data-snapshot-revision={batch?.revision}>
    <h3>{pending ? 'Checking automatic publication' : active ? 'Automatic publication' : 'Publication'}</h3>
    <p role="status">{pending ? 'ACP is checking the saved publishing permission. Wait before starting another delivery.' : active
      ? complete ? 'All authorized copies are confirmed at the destination.'
        : authorization.status === 'stopped' ? 'Automatic publishing is stopped. Existing delivery results remain available.'
          : 'Automatic publishing is on. No Publish click is needed for covered copies.'
      : error ? 'Automatic publication status is unavailable. ACP must confirm the saved permission before another delivery.' : 'Automatic publishing is off. Choose copies and confirm publication in Release.'}</p>
    {active && <p>{authorization.requires_reconnect ? 'Sign-in is required to resume the saved delivery.' : authorization.needs_attention || ['blocked', 'failed'].includes(authorization.status) ? 'Delivery needs recovery. Check the specific issue below.' : 'ACP delivers eligible saved copies after processing and release checks.'}</p>}
    {(authorization?.destination_label || destinationLabel) && <p><b>Destination:</b> {authorization?.destination_label || destinationLabel}</p>}
    {batch?.available === true && <p><b>{batch.delivered.toLocaleString()} of {batch.total.toLocaleString()} authorized copies delivered</b> · {batch.remaining.toLocaleString()} awaiting confirmation</p>}
    {active && batch?.available !== true && <p>Confirmed delivery totals are unavailable; this release is not shown as complete.</p>}
    {!compact && domain && <WorkflowOutcomeTiles stage="release" domain={domain} executionId={batch.scope_id} scopeLabel={`${batch.total.toLocaleString()} authorized files · entire saved plan`} onFilter={onFilter} />}
    {!compact && batch?.available === true && !domain && <p>Delivery classifications are being reconciled. Outstanding copies are not assumed to be queued.</p>}
    {error && <p>{error}</p>}
    {onOpen && <button type="button" className="linklike" onClick={onOpen}>Open Release →</button>}
  </section>
}
