// Small, dependency-free progress history for the live stage cards. Values are cumulative
// completed-document counts sampled by useThroughput; the line therefore shows measured movement,
// not a decorative animation or a model-generated estimate.
export default function LiveThroughput({ points = [], ratePerMin = null, label = 'Throughput', unitLabel = 'completed' }) {
  if (points.length < 2) return (
    <div className="muted" style={{ fontSize: 12.5 }}>{label} · calibrating…</div>
  )
  const width = 260, height = 72
  const plot = { left: 30, right: 6, top: 6, bottom: 18 }
  const lo = Math.min(...points), hi = Math.max(...points)
  const range = Math.max(1, hi - lo)
  const coords = points.map((value, index) => {
    const x = plot.left + (index * (width - plot.left - plot.right)) / Math.max(1, points.length - 1)
    const y = height - plot.bottom - ((value - lo) / range) * (height - plot.top - plot.bottom)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const rate = ratePerMin == null ? 'calibrating…' : `${ratePerMin.toLocaleString()} documents/min`
  const deltas = points.slice(1).map((value, index) => Math.max(0, value - points[index]))
  const maxDelta = Math.max(...deltas, 1)
  const bars = deltas.map((value, index) => {
    const available = width - plot.left - plot.right
    const slot = available / Math.max(1, deltas.length)
    const barWidth = Math.max(2, Math.min(16, slot * 0.62))
    const barHeight = (value / maxDelta) * (height - plot.top - plot.bottom)
    return { value, x: plot.left + slot * index + (slot - barWidth) / 2,
      y: height - plot.bottom - barHeight, width: barWidth, height: barHeight }
  })
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <div style={{ minWidth: 145 }}>
        <div className="muted" style={{ fontSize: 12.5 }}>{label}</div>
        <strong style={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>{rate}</strong>
        <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
          {lo.toLocaleString()} → {hi.toLocaleString()} {unitLabel} · {points.length} live updates
        </div>
      </div>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={`${label}: ${rate}; ${unitLabel} count moved from ${lo} to ${hi} across ${points.length} live updates`}>
        <line x1={plot.left} y1={plot.top} x2={plot.left} y2={height - plot.bottom}
              stroke="var(--line,#d9dde3)" />
        <line x1={plot.left} y1={height - plot.bottom} x2={width - plot.right} y2={height - plot.bottom}
              stroke="var(--line,#d9dde3)" />
        <text x={plot.left - 5} y={plot.top + 4} textAnchor="end" fontSize="9" fill="var(--muted,#667085)">{hi}</text>
        <text x={plot.left - 5} y={height - plot.bottom + 3} textAnchor="end" fontSize="9" fill="var(--muted,#667085)">{lo}</text>
        <text x={plot.left} y={height - 4} textAnchor="start" fontSize="9" fill="var(--muted,#667085)">Earlier</text>
        <text x={width - plot.right} y={height - 4} textAnchor="end" fontSize="9" fill="var(--muted,#667085)">Now</text>
        {bars.map((bar, index) => <rect key={index} x={bar.x} y={bar.y} width={bar.width}
          height={Math.max(bar.height, bar.value ? 1 : 0)} rx="1.5" fill="var(--purple-soft,#d9c9df)" />)}
        <polyline points={coords} fill="none" stroke="var(--purple,#6f4a78)" strokeWidth="2.25"
                  strokeLinecap="round" strokeLinejoin="round" />
        <text x={plot.left + 4} y={plot.top + 10} fontSize="8.5" fill="var(--muted,#667085)">bars: movement/update</text>
      </svg>
    </div>
  )
}
