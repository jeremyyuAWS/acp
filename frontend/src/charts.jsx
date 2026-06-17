import { useEffect, useState } from 'react'

// arcs grow from 0 on mount → reads as "live"
export function Donut({ segments, size = 138, thickness = 18, caption }) {
  const [on, setOn] = useState(false)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  const total = segments.reduce((a, s) => a + s.value, 0) || 1
  const r = (size - thickness) / 2
  const C = 2 * Math.PI * r
  let acc = 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flex: '0 0 auto' }} role="img" aria-label={caption}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f0edf2" strokeWidth={thickness} />
        {segments.map((s, i) => {
          const len = on ? (s.value / total) * C : 0
          const rot = (acc / total) * 360 - 90
          acc += s.value
          return <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={s.color}
            strokeWidth={thickness} strokeDasharray={`${len} ${C - len}`}
            transform={`rotate(${rot} ${size / 2} ${size / 2})`}
            style={{ transition: 'stroke-dasharray 0.9s ease' }} />
        })}
        <text x="50%" y="47%" textAnchor="middle" style={{ fontSize: 27, fontWeight: 600, fill: 'var(--ink)' }}>{total}</text>
        <text x="50%" y="61%" textAnchor="middle" style={{ fontSize: 11, fill: 'var(--muted)' }}>{caption}</text>
      </svg>
      <div style={{ flex: 1, minWidth: 0 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '6px 0', fontSize: 13 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, display: 'inline-block', flex: '0 0 auto' }} />
            <span style={{ flex: 1, color: 'var(--ink)' }}>{s.label}</span>
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{s.value}</b>
          </div>
        ))}
      </div>
    </div>
  )
}

// horizontal bars that fill from 0 on mount
export function Bars({ items, cols = '108px 1fr 30px' }) {
  const [on, setOn] = useState(false)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <div>
      {items.map((it, i) => (
        <div key={i} className="critrow" style={{ gridTemplateColumns: cols }}>
          <span className="critlabel" style={{ fontSize: 13 }}>{it.label}</span>
          <span className="track"><i style={{ width: on ? `${(it.value / max) * 100}%` : '0%', background: it.color, transition: 'width 0.9s ease' }} /></span>
          <span className="critn">{it.value}</span>
        </div>
      ))}
    </div>
  )
}

// status / severity helpers from a scan
export function statusSegments(run) {
  const issues = Math.max(0, run.files - run.certifiable - run.uncertain - run.error)
  return [
    { label: 'certifiable', value: run.certifiable, color: '#639922' },
    { label: 'issues', value: issues, color: '#F5B400' },
    { label: 'uncertain', value: run.uncertain, color: '#D85A30' },
    { label: 'unanalysable', value: run.error, color: '#9a948f' },
  ].filter((s) => s.value > 0)
}

const SEV = { CRITICAL: '#A32D2D', SERIOUS: '#E24B4A', MODERATE: '#F5B400', MINOR: '#888780' }
export function severityItems(files) {
  const c = {}
  files.forEach((f) => (f.issues || []).forEach((i) => { c[i.severity] = (c[i.severity] || 0) + 1 }))
  return ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].filter((s) => c[s])
    .map((s) => ({ label: s.toLowerCase(), value: c[s], color: SEV[s] }))
}
