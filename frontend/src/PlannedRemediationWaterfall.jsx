const stages = [
  ['Rules', 'Apply supported automatic fixes', '#246b79'],
  ['AI models', 'Use the enabled local or cloud models and configured fallbacks', '#5269a8'],
  ['Apply', 'Follow the approval choices saved in your remediation plan', '#a65a2e'],
  ['Verify', 'Check the corrected copies and record remaining work', '#356b3f'],
  ['Publish', 'Deliver corrected copies and reports to the selected destination', '#7b4d91'],
]

export default function PlannedRemediationWaterfall() {
  return <section className="panel" aria-label="Planned remediation waterfall">
    <h3>AI waterfall · Plan preview</h3>
    <p className="muted">Start remediation to see recorded model attempts, applied changes, and verification. These stages describe the workflow; no fixes have been recorded yet.</p>
    <ol style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, padding: 0, listStyle: 'none' }}>
      {stages.map(([title, detail, color], index) => <li key={title} style={{ border: `2px solid ${color}`, borderRadius: 12, padding: 16, background: `color-mix(in srgb, ${color} 7%, var(--surface, white))` }}>
        <span style={{ color, fontWeight: 700 }}>{String(index + 1).padStart(2, '0')} →</span>
        <h4>{title}</h4><p>{detail}</p><small className="muted">Planned · not yet recorded</small>
      </li>)}
    </ol>
  </section>
}
