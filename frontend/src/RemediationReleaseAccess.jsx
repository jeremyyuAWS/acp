import { hasSavedCorrectedCopy, deliveryIsCurrent } from './releaseClarityModel.js'

export default function RemediationReleaseAccess({ files = [], readOnly, onNavigate }) {
  const saved = files.filter(file => hasSavedCorrectedCopy(file) && !deliveryIsCurrent(file))
  if (readOnly || !saved.length) return null
  return <section className="panel" aria-label="Publish saved copies" style={{ padding: 14, marginBottom: 12 }}>
    <button className="primary" onClick={() => onNavigate?.('publish')}>Skip inspection and publish · {saved.length} {saved.length === 1 ? 'copy' : 'copies'}</button>
    <p className="muted" style={{ margin: '8px 0 0' }}>Publish available files while other documents continue processing or review. On Publish, choose verified copies or explicitly publish saved copies with remaining issues. Inspection is optional; unresolved findings stay recorded.</p>
  </section>
}
