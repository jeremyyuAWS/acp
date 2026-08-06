import { useState, useEffect, useRef } from 'react'

// Windowed rendering for long row lists: the first ROW_WINDOW render up front, and
// the window grows as the sentinel scrolls into view. At demo scale (a few dozen
// rows) everything fits in the first window and nothing changes; at the 100K-file
// estates the fan-out scan supports (ADR 0007), expanding a department or opening a
// segment drill-down no longer commits six-figure DOM nodes in one go. The button
// does the same thing as the sentinel so keyboard/AT users aren't dependent on
// scroll-driven loading.
const ROW_WINDOW = 150
export default function WindowedRows({ items, renderRow }) {
  const [limit, setLimit] = useState(ROW_WINDOW)
  const moreRef = useRef(null)
  const remaining = items.length - limit
  useEffect(() => {
    const el = moreRef.current
    if (remaining <= 0 || !el) return
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setLimit((l) => l + ROW_WINDOW)
    }, { rootMargin: '600px' })
    io.observe(el)
    return () => io.disconnect()
  }, [remaining > 0]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {items.slice(0, limit).map(renderRow)}
      {remaining > 0 && (
        <div ref={moreRef} style={{ padding: '8px 0', textAlign: 'center' }}>
          <button className="ghost small" onClick={() => setLimit((l) => l + ROW_WINDOW)}>
            Show {Math.min(ROW_WINDOW, remaining)} more · {remaining.toLocaleString()} remaining
          </button>
        </div>
      )}
    </>
  )
}
