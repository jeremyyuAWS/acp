// A small inline gauge for CPU/Memory utilization. "CPU 18%" as plain text reads slower at a
// glance than a bar does — this pairs the number with one. Color bands reuse
// workerDiagnosis.js's own HIGH_UTILIZATION_PCT threshold, so the bar and the diagnosis text
// never disagree about what counts as "hot".
import { HIGH_UTILIZATION_PCT } from './workerDiagnosis.js'

// Below HIGH_UTILIZATION_PCT: worth a glance, not yet the diagnosis layer's own warning line.
const WARN_UTILIZATION_PCT = 60

function barColor(percent) {
  if (percent >= HIGH_UTILIZATION_PCT) return '#8A2A20'   // matches this app's existing critical red
  if (percent >= WARN_UTILIZATION_PCT) return 'var(--warn-fg)'   // matches this app's existing warning amber
  return '#1a7f37'                                        // matches this app's existing healthy green
}

export default function UtilizationBar({ label, percent }) {
  if (percent == null) return null
  const clamped = Math.max(0, Math.min(100, percent))
  const color = barColor(clamped)
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span>{label} {percent}%</span>
      <span
        role="img"
        aria-label={`${label} utilization ${percent}%`}
        style={{ display: 'inline-block', width: 36, height: 6, borderRadius: 3,
                 background: 'var(--line)', overflow: 'hidden', flexShrink: 0 }}
      >
        <span style={{ display: 'block', width: `${clamped}%`, height: '100%', background: color }} />
      </span>
    </span>
  )
}
