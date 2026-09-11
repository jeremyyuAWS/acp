import { WCAG } from './wcagCatalog.js'
const names = Object.fromEntries(WCAG.map(row => [row.sc, row.name]))
const reasonNames = {
  model_not_installed: 'The selected model is not installed',
  circuit_open: 'Provider temporarily paused after repeated failures',
  transport: 'Provider could not be reached',
  budget_exhausted: 'The run spending limit was reached',
  unusable: 'The response could not be used',
}

export default function AssessmentEvidenceDetails({ scope, activity }) {
  const selected = scope?.scan_scope
  const codes = selected && typeof selected === 'object'
    ? Object.keys(selected).filter(sc => Array.isArray(selected[sc]) && selected[sc].length > 0)
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true })) : []
  return <div style={{ padding: '8px 0', fontSize: 13, lineHeight: 1.5 }}>
    <strong>Selected WCAG criteria for this assessment</strong>
    {codes.length ? <>
      <ul style={{ margin: '6px 0 12px', paddingLeft: 22 }}>{codes.map(sc =>
        <li key={sc}>SC {sc} — {names[sc] || 'Criterion name unavailable'}</li>)}</ul>
      <p className="muted">This saved selection also applies to remediation, verification, and reports. File-specific scope rules may narrow it further.</p>
    </> : <p className="muted">No explicit criterion selection was recorded for this scan. This does not mean every criterion was assessed.</p>}
    <strong>Recorded AI activity for this scan</strong>
    {!activity?.available ? <p className="muted">AI activity records are unavailable in this snapshot.</p>
      : activity.records === 0 ? <p className="muted">No AI activity has been recorded. Selecting an AI mode permits its use; it does not establish that a model ran.</p>
      : <>
        <ul style={{ margin: '6px 0', paddingLeft: 22 }}>{activity.groups.map((group, index) =>
          <li key={index}>{group.zone === 'local' ? 'Local' : group.zone === 'cloud' ? 'Cloud' : 'Unspecified location'} · {group.provider || 'Unknown provider'} / {group.model || 'Unknown model'}: {group.succeeded} successful responses; {group.records - group.succeeded} unsuccessful or blocked records</li>)}</ul>
        {activity.reasons?.length > 0 && <ul style={{ margin: '6px 0', paddingLeft: 22 }}>{activity.reasons.map((row, index) =>
          <li key={index}>{row.records} · {reasonNames[row.reason] || (row.reason ? row.reason.replaceAll('_', ' ') : 'Reason not recorded')}</li>)}</ul>}
        <p className="muted">Successful responses confirm model use. Unsuccessful records can include requests blocked before a provider was contacted. These are activity counts, not findings or verified fixes.</p>
      </>}
  </div>
}
