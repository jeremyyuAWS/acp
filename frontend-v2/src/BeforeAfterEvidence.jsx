import ContrastSwatch from './ContrastSwatch.jsx'
import { beforeAfter } from './beforeAfter.js'

// ONE before/after pattern for every finding type (HITL vision — same card anatomy, no per-rule UI).
// Contrast delegates to the colour swatch; heading and language render the same before→after frame.
// The reviewer sees the current state and the expected outcome side by side — Understand + Verify.
const CHIP = (tone) => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 8,
  fontSize: 13, fontWeight: 700,
  ...(tone === 'bad'
    ? { background: '#FBE9E7', color: '#A32D2D', border: '1px solid #E7B4AC' }
    : { background: '#E7F1DA', color: '#2C5209', border: '1px solid #B9D49A' }),
})

function Frame({ before, after }) {
  return (
    <div className="evcard-ba" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', margin: '0 0 12px' }}>
      <div>
        <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: .3, marginBottom: 4 }}>Before</div>
        {before}
      </div>
      <div aria-hidden="true" style={{ fontSize: 18, color: 'var(--muted, #8A8391)' }}>→</div>
      <div>
        <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: .3, marginBottom: 4 }}>After</div>
        {after}
      </div>
    </div>
  )
}

// A heading outline as level pills (H2 · H4), the offending jump marked, next to the corrected step.
function Levels({ levels, badIdx }) {
  return (
    <span style={{ display: 'inline-flex', gap: 6 }}>
      {levels.map((l, i) => (
        <span key={i} style={CHIP(i === badIdx ? 'bad' : 'good')}>H{l}</span>
      ))}
    </span>
  )
}

export default function BeforeAfterEvidence({ card }) {
  const ba = beforeAfter(card)
  if (!ba) return null
  if (ba.kind === 'contrast') return <ContrastSwatch {...ba.contrast} />
  if (ba.kind === 'heading') {
    // before: the outline with the skipped level flagged; after: the corrected consecutive step.
    return <Frame
      before={<Levels levels={ba.before} badIdx={ba.before.length - 1} />}
      after={<Levels levels={ba.after} badIdx={-1} />}
    />
  }
  if (ba.kind === 'lang') {
    // The document's language tag: not set (✗) → the value it will carry. When the concrete tag
    // isn't proposed yet, say what WILL be set — framed as such, never an invented code (ADR 0016).
    return <Frame
      before={<span style={CHIP('bad')}>✗ Not set</span>}
      after={ba.after
        ? <span style={CHIP('good')}>{ba.after}</span>
        : <span className="muted" style={{ fontSize: 12, maxWidth: 220, display: 'inline-block' }}>
            the document’s detected language (e.g. <code>en-US</code>), set on remediation
          </span>}
    />
  }
  return null
}
