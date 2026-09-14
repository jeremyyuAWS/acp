import { remainingWorkStatus } from './remainingWorkStatus.js'
import './remaining-work-status.css'

export default function RemainingWorkStatus(props) {
  const { notices, checkpoint, recovery, stalled, humanTotal, statusTotal } = remainingWorkStatus(props)
  if (!notices.length && !checkpoint && !recovery) return null
  return <section className="remaining-work-status" aria-label="Remaining work and recovery">
    <h3>What happens next</h3>
    {(checkpoint || recovery) && <p className={stalled ? 'remaining-work-stalled' : 'muted'} role={stalled ? 'alert' : undefined}>{checkpoint} {recovery}</p>}
    {(humanTotal > 0 || statusTotal > 0) && <p aria-label="Remaining work item counts"><b>{humanTotal.toLocaleString()} need your input</b> · {statusTotal.toLocaleString()} status checks. These are separate item groups; document notices below are not added to either total.</p>}
    {notices.length > 0 && <><p className="muted">Review items and recent image-recovery activity; these are not additional finding totals.</p><ul>{notices.map(notice => <li key={notice.key} className={`remaining-work-${notice.tone}`}><strong>{notice.population === 'status' && <small>Status checks · </small>}{notice.label}</strong><span>{notice.responsibility}</span></li>)}</ul></>}
  </section>
}
