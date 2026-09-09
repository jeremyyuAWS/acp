import { useId } from 'react'

const REASONS = {
  stale_evidence: 'The matching evaluation has expired.',
  insufficient_samples: 'Too few independent evaluated findings are available.',
  out_of_population: 'The evaluation does not match these formats, change types and models.',
  missing_or_conflicting_lineage: 'Finding outcomes cannot be linked reliably to evaluated attempts.',
  eligible_population_unknown: 'The applicable finding population has not been established.',
}
const range = value => Array.isArray(value) && value.length === 2 && value.every(v => v !== null && Number.isFinite(Number(v)))
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(Number(value))

export default function RemediationEstimateDisclosure({ estimate, aiEnabled, loading = false }) {
  const id = useId()
  if (!aiEnabled) return null
  const available = !loading && estimate?.available === true && range(estimate?.additional_usable_suggestions_range)
  return <details className="remediation-impact__providers" aria-labelledby={id}>
    <summary id={id}>Estimated extra AI help and cost</summary>
    {!available ? <p>{loading ? 'Updating estimate for this plan.' : <>
      <strong>Not enough applicable evidence for an estimate.</strong>{' '}
      {REASONS[estimate?.reason] || 'Representative evaluated outcomes for this plan are not available.'}
    </>}</p> : <>
      <p><strong>{estimate.additional_usable_suggestions_range.join('–')} additional usable suggestions</strong>{' '}
        across {estimate.eligible_findings} eligible findings. Suggestions still require the approved review and verification process.</p>
      <p>{estimate.uncertainty}</p>
      <p>Applies to {estimate.applicability?.format} · {estimate.applicability?.change_family} · configuration {estimate.applicability?.config_id}.</p>
      <p>Based on {estimate.sample_size} evaluated findings · evaluation {estimate.evaluation_version} · evaluated {estimate.evaluated_at} · expires {estimate.expires_at}.</p>
      {range(estimate.expected_provider_cost_range_usd) ? <>
        <p>Estimated provider cost: {estimate.expected_provider_cost_range_usd.map(money).join('–')}.</p>
        <p>{estimate.cost_uncertainty}</p>
        {estimate.observed_cost_per_usable_outcome_usd != null && <p>Observed cost per usable outcome: {money(estimate.observed_cost_per_usable_outcome_usd)}.</p>}
      </> : <p>Provider cost estimate unavailable: complete, settled charges are required.</p>}
      {estimate.cohort_spending && <p>Evaluation charges: generation {money(estimate.cohort_spending.generation_usd)}, review {money(estimate.cohort_spending.review_usd)}, final review or revision {money(estimate.cohort_spending.adjudication_usd)}.
        {' '}Held {money(estimate.cohort_spending.held_usd)}; unknown charges {estimate.cohort_spending.unknown_charges}; operations missing charges {estimate.cohort_spending.unattributed_operations}.</p>}
    </>}
    <p>Opening this preview makes no paid AI requests. These estimates do not promise completed fixes or compliance.</p>
  </details>
}
