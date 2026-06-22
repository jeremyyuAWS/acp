import { useEffect, useState } from 'react'

const ringColor = (s) => (s >= 90 ? '#639922' : s >= 50 ? '#BF8C00' : '#2E72C9')

function useCountUp(target, ms = 850) {
  const [v, setV] = useState(0)
  useEffect(() => {
    let raf, start
    const tgt = target ?? 0
    const step = (t) => {
      start ??= t
      const p = Math.min(1, (t - start) / ms)
      setV(Math.round(tgt * (1 - Math.pow(1 - p, 3))))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}

export function ScoreRing({ score, delta, deltaKey }) {
  const v = useCountUp(score ?? 0)
  const [prog, setProg] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setProg((score ?? 0) / 100))
    return () => cancelAnimationFrame(id)
  }, [score])
  const R = 56, C = 2 * Math.PI * R
  return (
    <div className="ring">
      <svg width="150" height="150" viewBox="0 0 150 150" role="img" aria-label={`average compliance score ${score ?? 0} out of 100`}>
        <circle cx="75" cy="75" r={R} fill="none" stroke="#ece7ec" strokeWidth="13" />
        <circle cx="75" cy="75" r={R} fill="none" stroke={ringColor(score ?? 0)} strokeWidth="13"
          strokeLinecap="round" strokeDasharray={`${(C * prog).toFixed(1)} ${C.toFixed(1)}`}
          transform="rotate(-90 75 75)" style={{ transition: 'stroke-dasharray 0.9s ease, stroke 0.4s' }} />
        <text x="75" y="73" textAnchor="middle" fontSize="36" fontWeight="600" fill="#46303F">{v}</text>
        <text x="75" y="93" textAnchor="middle" fontSize="11" fill="#6c6470">avg score / 100</text>
      </svg>
      {delta != null && delta !== 0 && (
        <span key={deltaKey} className={delta > 0 ? 'delta up' : 'delta down'}>
          {delta > 0 ? '+' : ''}{delta} {delta > 0 ? '▲' : '▼'}
        </span>
      )}
    </div>
  )
}

export function Sparkline({ points, width = 200, height = 46, labels }) {
  if (!points || points.length < 2) return null
  const axis = !!labels
  const w = width, h = height, padX = axis ? 14 : 8
  const topPad = axis ? 16 : 8 // room for the value above each point
  const botPad = axis ? 20 : 8 // room for the date below each point
  // scale to the data's own range (not 0-100) so small movements read
  const lo = Math.min(...points), hi = Math.max(...points)
  const range = Math.max(hi - lo, 4)
  const min = lo - range * 0.3, max = hi + range * 0.3
  const xs = points.map((_, i) => padX + (i * (w - 2 * padX)) / (points.length - 1))
  const ys = points.map((p) => (h - botPad) - ((p - min) / (max - min)) * (h - topPad - botPad))
  const line = xs.map((x, i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ')
  const area = `${line} L${xs[xs.length - 1].toFixed(1)},${h - botPad} L${xs[0].toFixed(1)},${h - botPad} Z`
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" className="spark" role="img" aria-label={`Compliance trend: ${points[0]} to ${points[points.length - 1]} over ${points.length} scans`}>
      {axis && <line x1={padX} y1={h - botPad} x2={w - padX} y2={h - botPad} stroke="#ece8ee" strokeWidth="1" />}
      <path d={area} fill="#7a5c8e" opacity="0.12" />
      <path d={line} fill="none" stroke="#7a5c8e" strokeWidth="2" />
      {xs.map((x, i) => (
        <g key={i}>
          <circle cx={x} cy={ys[i]} r={i === xs.length - 1 ? 3.8 : 2.6} fill={i === xs.length - 1 ? ringColor(points[i]) : '#7a5c8e'} />
          {axis && <text x={x} y={ys[i] - 7} textAnchor="middle" fontSize="10.5" fontWeight="600" fill="#6c6470">{points[i]}</text>}
          {axis && <text x={x} y={h - 5} textAnchor="middle" fontSize="10.5" fill="#797470">{labels[i]}</text>}
        </g>
      ))}
    </svg>
  )
}
