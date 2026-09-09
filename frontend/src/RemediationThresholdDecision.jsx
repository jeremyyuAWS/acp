const LABELS = {
  explicit_automatic_run_policy: 'Automatic application was explicitly approved for this run',
  permitted_supported_family: 'This change type is permitted and has a supported writer',
  exact_proposal_and_source_identity: 'The exact suggestion and source are identified',
  independent_exact_version_acceptance: 'An independent reviewer accepted this exact version',
  objective_validation_passed: 'Objective checks passed for this version and source',
  required_source_evidence_present: 'All required source evidence is present',
  source_unchanged: 'The source has not changed',
  no_subjective_meaning_change: 'This change does not require a subjective meaning decision',
  no_unresolved_disagreement: 'There is no unresolved reviewer disagreement',
  no_hard_review_conditions: 'There are no conditions requiring a person',
  applicable_fresh_calibration: 'Applicable evaluated results are current and sufficiently sampled',
  validated_reliability_meets_threshold: 'Validated reliability meets the approved minimum',
  exact_version_unchanged_before_write: 'The exact approved version and source are unchanged immediately before writing',
  registered_controlled_writer: 'A supported controlled writer is configured',
}

const CALIBRATION_REASONS = {
  calibration_missing: 'No independent evaluation is configured for this change type and model.',
  calibration_production_approval_missing: 'The evaluation is not approved for production or is owned by a different reviewer.',
  calibration_configuration_mismatch: 'The evaluation was produced with a different model or validator configuration.',
  calibration_sample_size_insufficient: 'The evaluation does not contain enough independent cases yet.',
  calibration_expired_or_future: 'The evaluation is expired or its timestamp is in the future.',
  calibration_invalid: 'The evaluation evidence could not be verified.',
}

export default function RemediationThresholdDecision({ decision }) {
  if (!decision) return <p>Eligibility not yet known. No saved threshold decision is available for this finding.</p>
  const label = decision.approval_kind === 'human' ? 'Approved by you'
    : decision.approval_kind === 'policy' ? 'Approved under your policy'
      : 'Still needs your approval'
  return <section aria-label="AI change approval evidence">
    <p><strong>{label}</strong>{decision.approval_kind === 'policy' && decision.status !== 'fixed_and_checked'
      ? decision.status === 'still_needs_work' ? ' — still needs work' : ' — awaiting completion' : ''}</p>
    {decision.approval_kind === 'policy' && <p>Approval is separate from application and verification. A change is fixed only after the result is checked.</p>}
    {Number.isFinite(decision.minimum_reliability) && <p>Approved minimum validated reliability: {decision.minimum_reliability}%.</p>}
    {Number.isFinite(decision.reliability_lower_bound) && <p>Evaluated reliability lower bound: {(decision.reliability_lower_bound * 100).toFixed(2)}%. This describes evaluated results for this type of change and does not guarantee this change is correct.</p>}
    {decision.evaluation_version && <p>Evaluation version: {decision.evaluation_version}</p>}
    {decision.calibration_reason && <p role="status"><strong>Automatic approval remains unavailable:</strong> {CALIBRATION_REASONS[decision.calibration_reason] || 'The required evaluation evidence is not currently eligible.'}</p>}
    {decision.checks?.length > 0 ? <ul>{decision.checks.map(check => <li key={check.gate}>
      <strong>{check.passed === true ? 'Passed' : 'Not passed'}:</strong> {LABELS[check.gate] || 'A required eligibility check'}
    </li>)}</ul> : <p>Detailed eligibility checks are unavailable for this decision.</p>}
  </section>
}
