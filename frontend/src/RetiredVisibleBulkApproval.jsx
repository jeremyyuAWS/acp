// RETIRED: the former visible-view approve-all flow, retained by project agreement.
// Removed from the UI by PR #1877. This historical implementation approves a live
// filtered population and must NOT be mounted: use BatchReviewSelection instead.
// Restoring it requires frozen proposal/source guards and explicit selected scope.
import { useMemo, useRef, useState } from 'react'
import { isResolved, laneOf } from './remediationInboxModel.js'
import { scOf } from './fixSummary.js'
const scKeyOf = f => scOf(f?.rule_id || f?.ruleId || f?.wcag)
export default function RetiredVisibleBulkApproval({ visible = [], decisions = {}, onDecide,
  setSelectedId = () => {}, setSavedMessage = () => {} }) {
  const [bulkPreviewOpen, setBulkPreviewOpen] = useState(false)
  const [bulkError, setBulkError] = useState('')
  const [savingId, setSavingId] = useState(null)
  const savedTimerRef = useRef(null)
  const visibleBulkTargets = useMemo(() => visible.filter((f) => {
    const key = laneOf(f).key
    return !isResolved(f, decisions) && (key === 'apply' || key === 'review') && f.after != null && f.after !== ''
  }), [visible, decisions])
  async function applyVisibleBulk() {
    if (savingId != null || visibleBulkTargets.length === 0) return
    setSavingId('visible-bulk'); setBulkError('')
    const results = await Promise.allSettled(visibleBulkTargets.map((f) =>
      onDecide?.(f, { state: 'accepted', value: f.after })))
    const failed = visibleBulkTargets.filter((_, i) => results[i].status === 'rejected')
    setSavingId(null)
    if (failed.length) {
      setBulkError(`${visibleBulkTargets.length - failed.length} of ${visibleBulkTargets.length} fixes saved. ${failed.length} still need attention.`)
      setSelectedId(failed[0].id)
      return
    }
    setBulkPreviewOpen(false)
    setSavedMessage(`${visibleBulkTargets.length} visible fixes approved and applied.`)
    clearTimeout(savedTimerRef.current)
    savedTimerRef.current = setTimeout(() => setSavedMessage(''), 2400)
  }

  const visibleBulkFiles = new Set(visibleBulkTargets.map((f) => f.file)).size
  const visibleBulkCriteria = new Set(visibleBulkTargets.map(scKeyOf).filter(Boolean)).size

  return <>
    <button type="button" onClick={() => setBulkPreviewOpen(open => !open)}>Bulk actions · {visibleBulkTargets.length} visible fixes</button>
{bulkPreviewOpen && visibleBulkTargets.length > 1 && (
        <div role="region" aria-label="Bulk approval summary"
             style={{ position: 'sticky', bottom: 0, zIndex: 5, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14,
                      padding: '12px 16px', border: '1px solid var(--accent,#3b6fd6)', background: 'var(--bg,#fff)', boxShadow: '0 -5px 18px rgba(31,43,58,.14)' }}>
          <span style={{ fontSize: 13, lineHeight: 1.45 }}>
            <b>Apply every actionable fix in this view</b>
            <span style={{ display: 'block' }}>{visibleBulkTargets.length} fixes · {visibleBulkFiles} file{visibleBulkFiles === 1 ? '' : 's'} · {visibleBulkCriteria} WCAG {visibleBulkCriteria === 1 ? 'criterion' : 'criteria'}</span>
            <span className="muted" style={{ display: 'block' }}>Each file keeps its own proposal. Manual, blocked, handed-off, and decided work is excluded.</span>
            {bulkError && <span role="alert" style={{ display: 'block', color: 'var(--error-fg-strong,#9f221c)', marginTop: 3 }}>{bulkError}</span>}
          </span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flex: '0 0 auto' }}>
            <button type="button" className="ghost" onClick={() => setBulkPreviewOpen(false)}>Cancel</button>
            <button type="button" className="primary" disabled={savingId != null} onClick={applyVisibleBulk}
                    style={{ fontWeight: 750, padding: '10px 16px' }}>
              {savingId === 'visible-bulk' ? 'Applying visible fixes…' : `Approve & apply all ${visibleBulkTargets.length}`}
            </button>
          </div>
        </div>
      )}
  </>
}
