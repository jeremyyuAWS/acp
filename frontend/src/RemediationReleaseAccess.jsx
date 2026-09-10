import { hasSavedCorrectedCopy, deliveryIsCurrent } from './releaseClarityModel.js'

export default function RemediationReleaseAccess({ files = [], readOnly, onNavigate }) {
  const saved = files.filter(file => hasSavedCorrectedCopy(file) && !deliveryIsCurrent(file))
  if (readOnly || !files.length) return null
  return <section className="panel" aria-label="Publish saved copies" style={{ padding: 14, marginBottom: 12 }}>
    <button className="primary" onClick={() => onNavigate?.('publish')}>Continue to Release</button>
    {saved.length > 0 && <p>{saved.length} saved {saved.length === 1 ? 'copy' : 'copies'} available to publish.</p>}
    <p className="muted" style={{ margin: '8px 0 0' }}>Approve eligible changes directly in Release or publish saved copies with remaining issues. You do not need to open the HITL panel. Remaining issues stay in the follow-up checklist.</p>
  </section>
}
