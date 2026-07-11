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
// onDraft(i), when given, adds a per-row "Draft with AI" button — for a DEFERRED row whose images
// have no draft yet (the reviewer writes from scratch). Omitted for proposals, which arrive with a
// draft already in the box, so the ReviewDrawer caller is unaffected.
export default function ProposalEditors({ proposals, values, onChange, file, sc, onDraft, draftingIdx = null, onApplyToSimilar = null }) {
  if (!proposals?.length) return null
  const many = proposals.length > 1
  const undrafted = !!onDraft   // an evidence row: no drafts, so the header must not claim any
  // Identical images (same thumbnail bytes = the same embedded picture reused, e.g. a logo on every
  // slide) — count them so one description can be applied to all copies (#132 approve-similar). The
  // key is the exact thumb data URL; only byte-identical images group, never look-alikes.
  const dupCount = {}
  proposals.forEach((p) => { if (p?.thumb) dupCount[p.thumb] = (dupCount[p.thumb] || 0) + 1 })
  return (
    <div className="evcard-multi">
      <span className="muted" style={{ fontSize: 12 }}>
        {undrafted
          ? (many
              ? `${proposals.length} images — each needs its own description. Draft one with AI, or type it.`
              : 'Describe the image — draft it with AI, or type what a screen reader should announce.')
          : (many
              ? `${proposals.length} findings — each gets its own value. Edit any before approving; approving accepts what is shown.`
              : 'Review the value before approving; approving accepts what is shown.')}
      </span>
      {proposals.map((p, i) => {
        const after = formatProposedValue(sc, values[i] ?? '')
        const filled = (values[i] ?? '').trim()
        return (
          <div className={`evcard-multi-row${undrafted && filled ? ' is-described' : ''}`} key={p?.locator || i}>
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
                <span className="muted evcard-multi-loc" style={{ fontSize: 11 }}>
                  {p?.locator ? `becomes · ${p.locator}` : 'becomes'}
                  {undrafted && filled ? <span className="evcard-imagerow-tick" aria-hidden="true"> ✓</span> : null}
                </span>
                <textarea className="evcard-rec-input" rows={2} value={values[i] ?? ''}
                          placeholder="Type the value that should be written…"
                          onChange={(e) => onChange(i, e.target.value)} />
              </label>
              {/* Draft THIS image with the vision model. The model sees one image, so the button
                  lives on the image's own row — there is no "picked" image to get wrong. */}
              {onDraft && (
                <button type="button" className="evcard-draft-btn" disabled={draftingIdx != null}
                        title="Ask the local model to describe this image — you still approve it"
                        onClick={() => onDraft(i)}>
                  {draftingIdx === i ? 'Drafting…' : '✨ Draft with AI'}
                </button>
              )}
              {/* Approve-similar (#132): this exact image appears more than once in the document, so
                  one description can fill every identical copy. Shown only once there's a value to
                  copy and a real duplicate to copy it to — honest, byte-identical grouping. */}
              {onApplyToSimilar && p?.thumb && dupCount[p.thumb] > 1 && filled && (
                <button type="button" className="evcard-similar-btn"
                        title="Copy this description to every identical copy of this image"
                        onClick={() => onApplyToSimilar(i)}>
                  ⧉ Apply to {dupCount[p.thumb]} identical
                </button>
              )}
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
