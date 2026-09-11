import InfoTip from './InfoTip.jsx'
import { useEffect, useRef, useState } from 'react'
import { REMEDIATION_CATEGORIES, remediationCategory } from './remediationCategories.js'
import './remediation-category-pills.css'
import './remediation-plan-impact.css'

const CATEGORY_HELP = {
  automatic: 'ACP can apply this fix under your current choices, then verify the result. Example: set a missing document language when a supported rule is available.',
  approval: 'A fix is available, but your plan requires approval before it is applied. Example: approve a proposed document title.',
  suggestion: 'AI needs to draft a possible fix. A suggestion is not yet an applied or verified fix. Example: draft alternative text for an image.',
  manual: 'A person needs to decide or make the change. Example: rewrite an unclear link label or check whether information relies on colour alone.',
  unsupported: 'ACP has no supported way to apply this fix. Use another tool or edit the source document. Example: a required structural repair that ACP cannot perform for this file format.',
  blocked: 'ACP cannot proceed until an obstacle is resolved. Example: the file cannot be accessed or a required service is unavailable.',
  applied: 'A change was made, but successful verification has not been recorded. Example: a language setting was updated and is waiting for a check.',
  verified: 'ACP applied the fix and recorded a successful verification for that finding. Example: a missing-language check passes after the update. This does not certify the whole document.',
  outside: 'These findings were counted in Assess but have no classification in this plan preview. Examples: a review finding omitted from the preview, or a finding in a file not selected for this plan. These are possible reasons, not confirmed explanations for each finding. Outside the plan does not mean ACP cannot fix it, or that it is fixed. Incomplete checks are separate.',
}

function TileHelp({ category, label }) {
  return <span className="plan-impact__help"><InfoTip label={label} toggleOnClick={false}>{CATEGORY_HELP[category]}</InfoTip></span>
}

export function planCategoryCounts(data) {
  if (!Array.isArray(data?.findings) || !Number.isSafeInteger(data?.open?.findings)) return null
  const counts = Object.fromEntries(REMEDIATION_CATEGORIES.map(([key]) => [key, 0]))
  for (const row of data.findings) {
    if (!Number.isSafeInteger(row.finding_count) || row.finding_count < 0) return null
    counts[remediationCategory(row)] += row.finding_count
  }
  return Object.values(counts).reduce((sum, n) => sum + n, 0) === data.open.findings ? counts : null
}
export default function RemediationPlanImpact({ identity, data, ready, loading, policyKey, assessmentTotal }) {
  const counts = ready ? planCategoryCounts(data) : null
  const assessed = Number.isSafeInteger(assessmentTotal) && assessmentTotal >= 0 ? assessmentTotal : null
  const outside = counts && assessed !== null ? Math.max(0, assessed - data.open.findings) : 0
  const totalText = outside > 0
    ? `${data.open.findings} in this plan + ${outside} outside this plan = ${assessed} assessed findings.`
    : `${data?.open?.findings} findings across the selected files.`
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
        <span>{label}</span><TileHelp category={key} label={label} /><strong>{counts ? counts[key] : '—'}</strong>
        {delta !== 0 && <span className={`plan-impact__delta ${direction > 0 ? 'positive' : direction < 0 ? 'negative' : 'neutral'}`}>{delta > 0 ? '+' : '−'}{Math.abs(delta)}</span>}
      </div>
    })}
      {outside > 0 && <div className="plan-impact__tile plan-impact__outside">
        <span>Outside this plan</span><TileHelp category="outside" label="Outside this plan" /><strong>{outside}</strong>
        <p>Assessed findings without a current plan classification. They may be outside the selected scope or absent from this preview. They are not counted as fixed.</p>
      </div>}
    </div>
    <p role="status" aria-live="polite" aria-atomic="true">{loading ? 'Updating…' : counts ? `${totalText} ${REMEDIATION_CATEGORIES.filter(([key]) => active?.[key]).map(([key, label]) => `${label}: ${active[key] > 0 ? '+' : ''}${active[key]}`).join('; ')}` : 'Preview unavailable — category counts could not be reconciled.'}</p>
    <small>Plan classification only. Completion requires application and verification.</small>
  </section>
}
