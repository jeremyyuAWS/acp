import { useEffect, useState } from 'react'
import { statusOf } from './docStatus.js'

// arcs grow from 0 on mount → reads as "live"
export function Donut({ segments, size = 138, thickness = 18, caption, onPick }) {
  const [on, setOn] = useState(false)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  const total = segments.reduce((a, s) => a + s.value, 0) || 1
  const r = (size - thickness) / 2
  const C = 2 * Math.PI * r
  let acc = 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flex: '0 0 auto' }} role="img" aria-label={`${caption || 'breakdown'}: ${segments.map((s) => `${s.value} ${s.label}`).join(', ')}`}>
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
        {segments.map((s, i) => {
          const sx = { display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0', fontSize: 13, width: '100%' }
          const inner = (<>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, display: 'inline-block', flex: '0 0 auto' }} />
            <span style={{ flex: 1, color: 'var(--ink)', textAlign: 'left' }}>{s.label}</span>
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{s.value}</b>
          </>)
          return onPick
            ? <button key={i} className="pickrow" style={sx} onClick={() => onPick(s)}>{inner}</button>
            : <div key={i} style={sx}>{inner}</div>
        })}
      </div>
    </div>
  )
}

// horizontal bars that fill from 0 on mount
export function Bars({ items, cols = '108px 1fr 30px', onPick, max, suffix }) {
  const [on, setOn] = useState(false)
  useEffect(() => { const t = setTimeout(() => setOn(true), 80); return () => clearTimeout(t) }, [])
  const mx = max || Math.max(1, ...items.map((i) => i.value))
  return (
    <div>
      {items.map((it, i) => {
        const inner = (<>
          <span className="critlabel" style={{ fontSize: 13, textAlign: 'left' }}>{it.label}</span>
          <span className="track"><i style={{ width: on ? `${(it.value / mx) * 100}%` : '0%', background: it.color, transition: 'width 0.9s ease' }} /></span>
          <span className="critn">{it.value}{suffix || ''}</span>
        </>)
        return onPick
          ? <button key={i} className="critrow pickrow" style={{ gridTemplateColumns: cols, width: '100%' }} onClick={() => onPick(it)}>{inner}</button>
          : <div key={i} className="critrow" style={{ gridTemplateColumns: cols }}>{inner}</div>
      })}
    </div>
  )
}

// status / severity helpers from a scan
//
// COUNT THE DOCUMENTS, DON'T SUBTRACT THEM. This used to derive the amber bucket as
// `run.files - run.certifiable - run.uncertain - run.error`, which is wrong twice over:
//
//   • It has no 'clean' bucket, so a not-certifiable document with ZERO findings landed in
//     "issues" by elimination — even though statusOf() and the certification PDF (report.py
//     `_status`) have both called that case 'clean' for exactly this reason.
//   • The run counters are NULL on a scan that never reached finalize_scan_run (cancelled, or
//     a worker lost mid-deploy). JS coerces those nulls to 0, so the subtraction quietly
//     returned the whole estate: a 258-document scan with no findings at all reported
//     "issues 258" beside a "No open findings." severity panel.
//
// So classify each file with the SAME statusOf() the drill-in filters by — the donut and the
// list it opens can no longer disagree, and a bucket is only shown if a document is really in it.
export function statusSegments(run, files) {
  const c = {}
  ;(files || []).forEach((f) => { const s = statusOf(f); c[s] = (c[s] || 0) + 1 })
  return [
    { label: 'certifiable', value: c.certifiable || 0, color: '#639922' },
    { label: 'issues', value: c.issues || 0, color: '#BF8C00' },
    { label: 'clean', value: c.clean || 0, color: '#2A5E9E' },
    { label: 'uncertain', value: c.uncertain || 0, color: '#D85A30' },
    { label: 'unanalysable', value: c.unanalysable || 0, color: '#9a948f' },
  ].filter((s) => s.value > 0)
}

const SEV = { CRITICAL: '#1F5FA8', SERIOUS: '#4A8FE0', MODERATE: '#BF8C00', MINOR: '#888780' }
export function severityItems(files) {
  const c = {}
  files.forEach((f) => (f.issues || []).forEach((i) => { c[i.severity] = (c[i.severity] || 0) + 1 }))
  return ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR'].filter((s) => c[s])
    .map((s) => ({ label: s.toLowerCase(), value: c[s], color: SEV[s] }))
}
