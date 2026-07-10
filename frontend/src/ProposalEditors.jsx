import ProposalThumb from './ProposalThumb.jsx'
import { thumbAlt, formatProposedValue } from './reviewCard.js'

// One finding, one editor — and, above it, the evidence for what is actually changing.
//
// A HITL row carries one proposal per finding instance (ten images → ten proposals; three
// foreign passages → three proposals), and approving now WRITES each value into the document at
// its own locator. So the reviewer has to see, per instance: the thing being changed (the image,
// or the passage of text), what it says now, what it will say, and why. A card that showed only
// a page thumbnail and "The AI drafted a fix" left a reviewer approving something they could not
// see — which is what this replaces.
//
// Shared by the Remediate drawer and the Review Center's evidence card: the array index IS the
// contract with the server (approved_values[i] is proposal i), so the two screens must never
// render a different order.
export default function ProposalEditors({ proposals, values, onChange, file, sc }) {
  if (!proposals?.length) return null
  const many = proposals.length > 1
  return (
    <div className="evcard-multi">
      <span className="muted" style={{ fontSize: 12 }}>
        {many
          ? `${proposals.length} findings — each gets its own value. Edit any before approving; approving accepts what is shown.`
          : 'Review the value before approving; approving accepts what is shown.'}
      </span>
      {proposals.map((p, i) => {
        const after = formatProposedValue(sc, values[i] ?? '')
        return (
          <div className="evcard-multi-row" key={p?.locator || i}>
            {p?.thumb && (
              <ProposalThumb thumb={p.thumb} size={56} alt={thumbAlt(p?.kind, file)}
                             className="evcard-multi-thumb" />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              {/* What is being changed. For an image this is the shape's locator; for a text
                  finding it is the passage itself, which is the only way a reviewer can judge
                  the value at all. */}
              {p?.before && (
                <div className="diffbox before evcard-ba">
                  <span className="difftag">current</span><code>{p.before}</code>
                </div>
              )}
              <label style={{ display: 'block' }}>
                <span className="muted" style={{ fontSize: 11 }}>
                  {p?.locator ? `becomes · ${p.locator}` : 'becomes'}
                </span>
                <textarea className="evcard-rec-input" rows={2} value={values[i] ?? ''}
                          placeholder="Type the value that should be written…"
                          onChange={(e) => onChange(i, e.target.value)} />
              </label>
              {/* The raw value can be opaque ("es"). Show the markup it becomes, so the
                  reviewer approves a change they understand. */}
              {after && after !== (values[i] ?? '') && (
                <div className="diffbox after evcard-ba"><span className="difftag">writes</span><code>{after}</code></div>
              )}
              {p?.rationale && (
                <p className="muted evcard-why-draft">{p.rationale}{p?.source ? ` · ${p.source}` : ''}</p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// The initial text for each editor: this instance's own draft, or a value already approved for
// it. Approving without touching anything therefore means "the drafts I was shown are correct".
export const seedValues = (proposals) =>
  (proposals || []).map((p) => p?.approved_value ?? p?.proposed_value ?? '')
