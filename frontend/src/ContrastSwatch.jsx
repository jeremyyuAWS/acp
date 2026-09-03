// Visual evidence for a contrast finding (HITL vision — "see it, don't read a number"). Renders
// the ACTUAL foreground text on the ACTUAL background at a legible size, so the reviewer instantly
// SEES that it's too faint, alongside the measured ratio and the required ratio. Every value is a
// real measurement from the document (api/office_structure), never fabricated.
export default function ContrastSwatch({ fg, bg, ratio, needs, passes }) {
  if (!fg || !bg) return null
  const chip = (bgc, fgc, border) => ({
    display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px',
    borderRadius: 20, fontSize: 12, fontWeight: 700, background: bgc, color: fgc,
    border: `1px solid ${border}`,
  })
  return (
    <div className="evcard-contrast" style={{ margin: '0 0 12px' }}>
      {/* The offending pairing, shown as it appears in the document. */}
      <div style={{ background: bg, color: fg, borderRadius: 10, border: '1px solid var(--line)',
                    padding: '18px 20px', lineHeight: 1.35 }}>
        <div style={{ fontSize: 20, fontWeight: 600 }}>The quick brown fox</div>
        <div style={{ fontSize: 13 }}>jumps over the lazy dog — sample body text as it appears.</div>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
        <span style={chip(passes ? '#E7F1DA' : '#FBE9E7', passes ? '#2C5209' : 'var(--error-fg-strong)',
                          passes ? '#B9D49A' : '#E7B4AC')}>
          {passes ? '✓' : '✗'} measured {ratio.toFixed(1)}:1
        </span>
        <span style={chip('var(--card, #f7f4fb)', 'var(--fg, #1c1620)', 'var(--line)')}>
          needs {needs % 1 === 0 ? needs : needs.toFixed(1)}:1
        </span>
        <span className="muted" style={{ fontSize: 12 }}>
          {fg} on {bg}
        </span>
      </div>
    </div>
  )
}
