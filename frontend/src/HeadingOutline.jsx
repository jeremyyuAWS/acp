import { useState, useEffect } from 'react'
import { getHeadingOutline } from './api.js'

// The docx heading outline as review evidence: the document's REAL headings (with the level skip)
// beside a corrected, never-skip version — fetched on demand from the document (mirrors Thumbnail's
// geometry fetch). When no outline is available (non-docx, fewer than two headings, an already-clean
// outline, or any failure) it renders the caller's honest fallback (the generic "structure not
// extracted" note) instead — never a fabricated tree.

function Outline({ items, title }) {
  return (
    <div style={{ flex: '1 1 0', minWidth: 0 }}>
      <p className="muted" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', margin: '0 0 6px' }}>{title}</p>
      <ol style={{ listStyle: 'none', margin: 0, padding: 0, border: '1px solid var(--line,#e2dce4)', borderRadius: 8, overflow: 'hidden' }}>
        {items.map((h, i) => (
          <li key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13, padding: '6px 10px',
                               paddingLeft: 10 + (Math.max(1, h.level) - 1) * 16,
                               borderTop: i ? '1px solid var(--line,#e2dce4)' : 'none' }}>
            <span className="muted" style={{ fontFamily: 'var(--mono, ui-monospace, monospace)', fontSize: 11, fontWeight: 700, flex: '0 0 auto' }}>H{h.level}</span>
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {h.text ? h.text : <span className="muted">(empty heading)</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function HeadingOutline({ scanId, file, wcag, fallback = null }) {
  const [outline, setOutline] = useState(undefined)   // undefined = loading, null = none, object = outline
  useEffect(() => {
    let live = true
    setOutline(undefined)
    getHeadingOutline(scanId, file).then((o) => { if (live) setOutline(o || null) })
    return () => { live = false }
  }, [scanId, file])

  if (outline && Array.isArray(outline.before) && Array.isArray(outline.after)) {
    return (
      <div className="ba-evidence ba-heading-outline">
        <p className="muted" style={{ fontSize: 12.5, margin: '0 0 10px' }}>
          {wcag ? `${wcag} — ` : ''}The document's heading outline. The levels skip today; the corrected version nests without gaps:
        </p>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <Outline items={outline.before} title="Before" />
          <span aria-hidden="true" style={{ flex: '0 0 auto', alignSelf: 'center', fontSize: 18, color: 'var(--muted,#8a8f98)' }}>→</span>
          <Outline items={outline.after} title="After (corrected)" />
        </div>
      </div>
    )
  }
  // Loading or no outline → the caller's honest fallback (the generic note), never a blank.
  return fallback
}
