import ProposalThumb from './ProposalThumb.jsx'
import { thumbAlt } from './reviewCard.js'

// One image, one description. A HITL row carries one proposal per finding instance (ten images
// → ten proposals), and approving now WRITES each value into the document at its own locator.
// A single text box could neither express ten descriptions nor let a reviewer see what they
// were describing — so every proposal gets its picture and its own editor, side by side.
//
// Shared by the Remediate drawer and the Review Center's evidence card: a reviewer must approve
// the same thing on both screens, and the array index IS the contract with the server
// (approved_values[i] is proposal i), so the two must never render a different order.
export default function ProposalEditors({ proposals, values, onChange, file }) {
  if (!proposals?.length) return null
  return (
    <div className="evcard-multi">
      <span className="muted" style={{ fontSize: 12 }}>
        {proposals.length} images — each gets its own description. Edit any before approving;
        approving accepts the drafts shown.
      </span>
      {proposals.map((p, i) => (
        <div className="evcard-multi-row" key={p?.locator || i}>
          <ProposalThumb thumb={p?.thumb} size={56} alt={thumbAlt(p?.kind, file)}
                         className="evcard-multi-thumb" />
          <label style={{ flex: 1, minWidth: 0 }}>
            <span className="muted" style={{ fontSize: 11 }}>{p?.locator || `image ${i + 1}`}</span>
            <textarea className="evcard-rec-input" rows={2} value={values[i] ?? ''}
                      placeholder="Type the value a screen reader should announce…"
                      onChange={(e) => onChange(i, e.target.value)} />
          </label>
        </div>
      ))}
    </div>
  )
}

// The initial text for each editor: this image's own draft, or a value already approved for it.
// Approving without touching anything therefore means "the drafts I was shown are correct".
export const seedValues = (proposals) =>
  (proposals || []).map((p) => p?.approved_value ?? p?.proposed_value ?? '')
