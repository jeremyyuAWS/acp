const explanations = {
  insufficient_visual_evidence: 'Image evidence was unavailable, so ACP did not guess a description.',
  ambiguous_locator: 'ACP could not identify one exact place to change.',
  unsupported_adapter: 'This type of fix is not supported by document-wide AI yet.',
  unsupported_rule: 'This criterion has no document-wide fix yet.',
  findings_omitted: 'Some findings were outside the supported scope or extraction limits.',
  budget_exhausted: 'The remaining spending limit could not cover the request.',
  provider_unavailable: 'The configured AI provider was unavailable.',
  invalid_response: 'The AI response did not pass validation.',
  no_supported_findings: 'No selected findings had a supported document-wide fix.',
  local_unsupported: 'This preview requires Cloud AI; the local-only choice was respected.',
}
const explain = reason => explanations[reason] || (/\s/.test(String(reason)) ? String(reason) : `Recorded reason: ${String(reason).replaceAll('_', ' ')}.`)

export default function DocumentWideAiOutcomes({ snapshot }) {
  if (!snapshot?.enabled) return null
  const files = Array.isArray(snapshot.files) ? snapshot.files : []
  return <section aria-label="Document-wide AI results">
    <h4>Document-wide AI results</h4>
    <p>Suggestions are not applied or verified fixes. Other remediation steps may address the items listed here.</p>
    {!snapshot.complete && <p>Only the most recent retained activity is available.</p>}
    {!files.length && <p>No document-wide result has been recorded for this run yet.</p>}
    {files.map(row => <details key={row.file}>
      <summary>{row.file} · {Number.isSafeInteger(row.suggestions) ? row.suggestions : 'Unknown'} suggestions{row.status === 'deferred' ? ' · Deferred' : ''}</summary>
      {row.reasons?.length > 0 ? <><p>Not addressed by document-wide AI:</p><ul>{row.reasons.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul></> : <p>No additional exception reason was recorded.</p>}
    </details>)}
  </section>
}
