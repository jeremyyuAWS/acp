import { hasCorrectedCopy, deliveryIsCurrent } from './releaseClarityModel.js'

export default function RemediationReleaseAccess({ files = [], readOnly, onNavigate }) {
  const verified = files.filter(file => hasCorrectedCopy(file) && file.corrected_sha256 && !deliveryIsCurrent(file))
  if (readOnly || !verified.length) return null
  return <section className="panel" aria-label="Release verified files" style={{ padding: 14, marginBottom: 12 }}>
    <button className="primary" onClick={() => onNavigate?.('publish')}>Open Release · {verified.length} verified {verified.length === 1 ? 'copy' : 'copies'}</button>
    <p className="muted" style={{ margin: '8px 0 0' }}>Publish available files while other documents continue processing or review. Release checks each file’s approvals, current source, and destination before publishing.</p>
  </section>
}
