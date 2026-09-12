import { useId } from 'react'
import './ReleaseDeliveryCard.css'

export default function ReleaseDeliveryCard({ ready = [], scopeCount = 0, publishedCount = 0,
  deliveringCount = 0, failedCount = 0, publishing = false, loading = false, readOnly = false,
  allowRemainingIssues = false, onRemainingIssuesChange, onPublish, onOpenDetails,
  destinationLabel, announcement, error, folders = [], children }) {
  const headingId = useId()
  const unavailable = readOnly || loading || publishing
  return <section className="panel release-delivery-card" aria-labelledby={headingId}>
    <div className="release-delivery-card__heading">
      <div><h3 id={headingId}>Publish corrected copies</h3>
        <p>Continue from saved fixes to delivery without leaving remediation.</p></div>
      {onOpenDetails && <button className="ghost" type="button" onClick={onOpenDetails}>Release details</button>}
    </div>
    <div className="release-delivery-card__counts" aria-label="Delivery progress">
      <span><strong>{ready.length}</strong> ready</span>
      <span><strong>{deliveringCount}</strong> delivering</span>
      <span><strong>{publishedCount}</strong> published</span>
      {failedCount > 0 && <span><strong>{failedCount}</strong> delivery failed</span>}
    </div>
    {destinationLabel && <p className="release-delivery-card__destination">Destination: {destinationLabel}</p>}
    {onRemainingIssuesChange && <label className="release-delivery-card__option">
      <input type="checkbox" checked={allowRemainingIssues} disabled={unavailable}
        onChange={event => onRemainingIssuesChange(event.target.checked)} />
      Include saved copies with remaining work
    </label>}
    <p className="muted">{allowRemainingIssues
      ? 'Unresolved work stays in the checklist. Unapproved suggestions are not applied.'
      : 'Only copies that pass release checks are included. You can include remaining work above.'}</p>
    <button className="primary" type="button" disabled={unavailable || !ready.length || !onPublish}
      onClick={() => onPublish?.(ready.map(file => file.file))}>
      {publishing ? 'Publishing copies…' : loading ? 'Checking release…'
        : `Publish ${ready.length} saved ${ready.length === 1 ? 'copy' : 'copies'}`}
    </button>
    {!loading && !publishing && !ready.length && !deliveringCount && !publishedCount &&
      <p>{scopeCount ? 'Copies appear here after remediation saves them and release eligibility is confirmed.' : 'Choose documents to remediate first.'}</p>}
    {readOnly && <p>Publishing is unavailable in this view.</p>}
    {(announcement || deliveringCount > 0) && <p role="status">{announcement || 'Delivery continues in the background. The receipt appears here when confirmed.'}</p>}
    {error && <div role="alert"><strong>{error.summary || 'Delivery needs attention'}</strong>
      <p>{error.details}</p>
      {error.retry && <button type="button" className="ghost" disabled={unavailable} onClick={error.retry}>{error.retryLabel || 'Refresh delivery status'}</button>}
    </div>}
    {folders.filter(folder => folder.url).map(folder => <p key={folder.id || folder.url}>
      <a href={folder.url} target="_blank" rel="noopener noreferrer">Open published folder ↗</a>
    </p>)}
    {children}
  </section>
}
