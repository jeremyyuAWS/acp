// Lightweight CSS word cloud — each term sized by its count (sqrt scale) and colored
// by tier. Biggest terms land toward the center for a cloud-like feel.
export default function WordCloud({ items }) {
  if (!items.length) return <p className="muted">No findings.</p>
  const vals = items.map((i) => i.value)
  const max = Math.max(...vals), min = Math.min(...vals)
  const fs = (v) => {
    const t = max === min ? 1 : (Math.sqrt(v) - Math.sqrt(min)) / (Math.sqrt(max) - Math.sqrt(min))
    return Math.round(15 + t * 24)
  }
  const color = (v) => {
    const t = max === min ? 1 : (v - min) / (max - min)
    return t > 0.66 ? '#A32D2D' : t > 0.33 ? '#E24B4A' : '#EF9F27'
  }
  // big terms toward the middle, smaller toward the edges
  const ordered = [...items].sort((a, b) => b.value - a.value)
  const arr = []
  ordered.forEach((it, i) => (i % 2 ? arr.push(it) : arr.unshift(it)))

  return (
    <div className="wordcloud" role="img" aria-label="Word cloud of WCAG violations sized by count">
      {arr.map((it) => (
        <span key={it.text} className="wcword" style={{ fontSize: fs(it.value), color: color(it.value) }} title={`${it.full} · ${it.value} documents`}>{it.text}</span>
      ))}
    </div>
  )
}
