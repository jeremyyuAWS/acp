import './accepted-remediation-plan.css'

const ruleChoices = ['Review before applying', 'Apply eligible safe fixes automatically', 'Apply supported rule-based fixes automatically']

/** Callers must supply the accepted execution snapshot, never current owner defaults. */
export default function AcceptedRemediationPlanSummary({ policy, authorization, loading = false }) {
  if (loading) return <p role="status">Loading accepted plan…</p>
  if (!policy) return <section className="accepted-remediation-plan" aria-label="Accepted remediation plan">
    <h3>Accepted remediation plan</h3><p>The saved choices for this run are unavailable.</p>
  </section>
  const usesAI = Number.isInteger(policy.ai) && policy.ai > 0
  const tools = policy.ai === 0 ? 'Rules only' : usesAI
    ? policy.ai_zone === 'local' ? 'Rules + Ollama · Local only' : policy.ai_zone === 'any' ? 'Rules + Cloud AI' : 'Rules + configured AI'
    : 'Not recorded'
  const publishing = authorization?.allow_remaining_issues === true ? 'Publish automatically after processing'
    : authorization?.allow_remaining_issues === false ? 'Review in Release before publishing' : 'Not recorded'
  return <section className="accepted-remediation-plan" aria-label="Accepted remediation plan">
    <h3>Accepted remediation plan</h3>
    <p>These are the saved choices for this run.</p>
    <dl>
      <div><dt>Rule-based fixes</dt><dd>{ruleChoices[policy.rule_based] || 'Not recorded'}</dd></div>
      <div><dt>Tools</dt><dd>{tools}</dd></div>
      {usesAI && <>
        <div><dt>AI suggestions</dt><dd>{policy.auto_approve_ai === true ? 'Apply supported suggestions automatically' : 'Review before applying'}</dd></div>
        <div><dt>Document-wide AI</dt><dd>{policy.document_wide_ai === true ? 'Enabled · PDF form-field names, tagged PDF image descriptions, and Word image descriptions' : 'Off'}</dd></div>
        {policy.ai_zone !== 'local' && <div><dt>AI spending limit</dt><dd>{typeof policy.ai_budget_usd === 'string' ? `$${policy.ai_budget_usd} USD` : 'Not recorded'}</dd></div>}
      </>}
      <div><dt>Publishing</dt><dd>{publishing}</dd></div>
    </dl>
    <p>Applied changes count as resolved only after verification.</p>
  </section>
}
