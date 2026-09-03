// Small, dependency-free progress history for the live stage cards. Values are cumulative
// completed-document counts sampled by useThroughput; the line therefore shows measured movement,
// not a decorative animation or a model-generated estimate.
export default function LiveThroughput({ points = [], ratePerMin = null, label = 'Throughput' }) {
  if (points.length < 2) return (
    <div className="muted" style={{ fontSize: 12.5 }}>{label} · calibrating…</div>
  )
  const width = 180, height = 34, pad = 3
  const lo = Math.min(...points), hi = Math.max(...points)
  const range = Math.max(1, hi - lo)
  const coords = points.map((value, index) => {
    const x = pad + (index * (width - pad * 2)) / Math.max(1, points.length - 1)
    const y = height - pad - ((value - lo) / range) * (height - pad * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const rate = ratePerMin == null ? 'calibrating…' : `${ratePerMin.toLocaleString()} documents/min`
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <span className="muted" style={{ fontSize: 12.5 }}>{label}</span>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={`${label}: ${rate}; completed count moved from ${lo} to ${hi}`}>
        <polyline points={coords} fill="none" stroke="var(--purple,#6f4a78)" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <strong style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>{rate}</strong>
    </div>
  )
}
