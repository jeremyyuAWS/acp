import { useEffect, useRef, useState } from 'react'
import { REMEDIATION_CATEGORIES, remediationCategory } from './remediationCategories.js'
import './remediation-category-pills.css'
import './remediation-plan-impact.css'

export function planCategoryCounts(data) {
  if (!Array.isArray(data?.findings) || !Number.isSafeInteger(data?.open?.findings)) return null
  const counts = Object.fromEntries(REMEDIATION_CATEGORIES.map(([key]) => [key, 0]))
  for (const row of data.findings) {
    if (!Number.isSafeInteger(row.finding_count) || row.finding_count < 0) return null
    counts[remediationCategory(row)] += row.finding_count
  }
  return Object.values(counts).reduce((sum, n) => sum + n, 0) === data.open.findings ? counts : null
}
export default function RemediationPlanImpact({ identity, data, ready, loading, policyKey }) {
  const counts = ready ? planCategoryCounts(data) : null
  const signature = JSON.stringify(counts)
  const previous = useRef(null)
  const [flash, setFlash] = useState(null)
  useEffect(() => {
    if (previous.current?.identity !== identity) { previous.current = null; setFlash(null) }
    if (!counts) return
    const before = previous.current
    previous.current = { identity, policyKey, counts, total: data.open.findings }
    if (!before || before.policyKey === policyKey || before.total !== data.open.findings) return
    const deltas = Object.fromEntries(REMEDIATION_CATEGORIES.map(([key]) => [key, counts[key] - before.counts[key]]))
    setFlash({ identity, policyKey, deltas })
  }, [identity, policyKey, signature])
  useEffect(() => {
    if (!flash) return
    const timer = setTimeout(() => setFlash(null), 2600)
    return () => clearTimeout(timer)
  }, [flash])
  const active = counts && flash?.identity === identity && flash?.policyKey === policyKey ? flash.deltas : null
  return <section className="plan-impact" aria-label="Plan classification preview" aria-busy={loading}>
    <h4>How this plan classifies your findings</h4>
    <div className="plan-impact__grid">{REMEDIATION_CATEGORIES.map(([key, label]) => {
      const delta = active?.[key] || 0
      const hardDelta = ['manual', 'blocked', 'unsupported'].reduce((sum, id) => sum + (active?.[id] || 0), 0)
      const direction = key === 'automatic' ? delta : ['manual', 'blocked', 'unsupported'].includes(key) ? -delta
        : ['approval', 'suggestion'].includes(key) && delta * hardDelta < 0 ? delta : 0
      return <div key={key} className={`plan-impact__tile remediation-category-pill--${key}`}>
        <span>{label}</span><strong>{counts ? counts[key] : '—'}</strong>
        {delta !== 0 && <span className={`plan-impact__delta ${direction > 0 ? 'positive' : direction < 0 ? 'negative' : 'neutral'}`}>{delta > 0 ? '+' : '−'}{Math.abs(delta)}</span>}
      </div>
    })}</div>
    <p role="status" aria-live="polite" aria-atomic="true">{loading ? 'Updating…' : counts ? `${data.open.findings} findings across the selected files. ${REMEDIATION_CATEGORIES.filter(([key]) => active?.[key]).map(([key, label]) => `${label}: ${active[key] > 0 ? '+' : ''}${active[key]}`).join('; ')}` : 'Preview unavailable — category counts could not be reconciled.'}</p>
    <small>Plan classification only. Completion requires application and verification.</small>
  </section>
}
