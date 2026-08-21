import { useState } from 'react'

// K1 · Estate composition treemap — area encodes exactly one thing at a time (file count, or a
// total-pages toggle), with a ranked table alongside for the exact comparison a treemap can't
// give on its own.
//
// The mockup's second dimension — "darker fill = lower classification coverage" — has no real
// source today: discovery does not derive a department or a sensitivity label from any real
// document (see classificationData.js, and the #603 fix for what happens when that gets faked).
// So every tile renders in ONE neutral shade and the Coverage column reads "not measured", not a
// guessed percentage. When a real per-format coverage signal exists, wire it in here — the layout
// and the "greyed when absent" convention are already in place for it to slot into.

// Simple slice-and-dice treemap: recursively split the current rect along its longer axis,
// dividing items into two value-balanced groups. Not squarified, but stable and legible for the
// handful of file-type categories this panel actually has.
function layout(items, x, y, w, h) {
  if (!items.length) return []
  if (items.length === 1) return [{ ...items[0], x, y, w, h }]
  const total = items.reduce((a, i) => a + i.value, 0)
  let acc = 0, splitAt = 1
  for (let i = 0; i < items.length; i++) {
    acc += items[i].value
    if (acc >= total / 2) { splitAt = i + 1; break }
  }
  const groupA = items.slice(0, splitAt)
  const groupB = items.slice(splitAt)
  const aFrac = groupA.reduce((a, i) => a + i.value, 0) / total
  if (w >= h) {
    const wA = w * aFrac
    return [...layout(groupA, x, y, wA, h), ...layout(groupB, x + wA, y, w - wA, h)]
  }
  const hA = h * aFrac
  return [...layout(groupA, x, y, w, hA), ...layout(groupB, x, y + hA, w, h - hA)]
}

const FILL = ['#f1e9ee', '#e3d3df', '#c9a9be', '#a7789e', '#7a5c8e', '#5c4468', '#46303F']

/**
 * @param byCount  [{label, value}] file counts per type — the file-count view. Required.
 * @param byPages  [{label, value}] total pages per type, or null if no file has a page count
 *                 yet (a discover-only estate, or one whose formats don't report pages). When
 *                 null the "By total pages" toggle is not offered at all — there is nothing to
 *                 switch to, and offering it would invite a click that lands on all-absent bars.
 * @param onPick   (label) => void, e.g. to filter the document list by type.
 */
export default function EstateTreemap({ byCount, byPages = null, onPick = null }) {
  const [mode, setMode] = useState('count')
  const canPages = Array.isArray(byPages) && byPages.some((r) => r.value > 0)
  const items = (mode === 'pages' && canPages ? byPages : byCount)
    .filter((r) => r.value > 0)
    .slice()
    .sort((a, b) => b.value - a.value)
  const total = items.reduce((a, i) => a + i.value, 0)
  const W = 640, H = 260
  const rects = layout(items, 0, 0, W, H)

  return (
    <section className="panel">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Estate composition treemap</h2>
        <span role="group" aria-label="Treemap measure" style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button className={mode === 'count' ? 'fchip on' : 'fchip'} onClick={() => setMode('count')}>By file count</button>
          {canPages && (
            <button className={mode === 'pages' ? 'fchip on' : 'fchip'} onClick={() => setMode('pages')}>By total pages</button>
          )}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="muted" style={{ fontSize: 13 }}>No documents to compose yet.</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: `${W}px 1fr`, gap: 20, alignItems: 'start' }}>
          <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="Estate composition by file type">
            {rects.map((r, i) => {
              const label = r.label
              const Tag = onPick ? 'g' : 'g'
              const big = r.w > 70 && r.h > 34
              return (
                <Tag key={label} style={onPick ? { cursor: 'pointer' } : undefined}
                     onClick={onPick ? () => onPick(label) : undefined}>
                  <rect x={r.x} y={r.y} width={Math.max(0, r.w - 1)} height={Math.max(0, r.h - 1)}
                        fill={FILL[i % FILL.length]} />
                  {big && (
                    <>
                      <text x={r.x + 8} y={r.y + 18} fontSize="13" fontWeight="700"
                            fill={i < 3 ? 'var(--ink)' : '#fff'}>{label}</text>
                      <text x={r.x + 8} y={r.y + 34} fontSize="12"
                            fill={i < 3 ? 'var(--muted)' : 'rgba(255,255,255,.85)'}>
                        {r.value.toLocaleString()}
                      </text>
                    </>
                  )}
                </Tag>
              )
            })}
          </svg>

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)', fontSize: 11.5, letterSpacing: '.04em', textTransform: 'uppercase' }}>
                <th style={{ padding: '0 8px 6px 0' }}>#</th>
                <th style={{ padding: '0 8px 6px' }}>Type</th>
                <th style={{ padding: '0 8px 6px', textAlign: 'right' }}>{mode === 'pages' ? 'Pages' : 'Count'}</th>
                <th style={{ padding: '0 0 6px 8px', textAlign: 'right' }}>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, i) => (
                <tr key={r.label} style={{ borderTop: '1px solid var(--line)' }}>
                  <td style={{ padding: '6px 8px 6px 0', color: 'var(--muted)' }}>{i + 1}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2,
                                   background: FILL[i % FILL.length], marginRight: 7, verticalAlign: -1 }} />
                    {r.label}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {r.value.toLocaleString()}
                  </td>
                  <td style={{ padding: '6px 0 6px 8px', textAlign: 'right', color: 'var(--muted)' }}
                      title="No source derives a per-type classification signal yet — shown as absent, not measured.">
                    not measured
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="muted" style={{ fontSize: 11.5, margin: '12px 0 0', lineHeight: 1.5 }}>
        Area encodes exactly one thing ({mode === 'pages' ? 'total pages' : 'file count'}
        {canPages ? ' — toggle to switch' : ''}), out of {total.toLocaleString()} {mode === 'pages' ? 'pages' : 'documents'}.
        Coverage shading is not shown: discovery does not derive a department or sensitivity label
        from any real document today, so there is no real signal to shade by — see it here once
        one exists, rather than a guessed percentage in the meantime.
      </p>
    </section>
  )
}
