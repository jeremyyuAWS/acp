import { useState } from 'react'
import ProposalThumb from './ProposalThumb.jsx'
import { thumbAlt, formatProposedValue } from './reviewCard.js'
import { speakAsScreenReader, srSupported } from './srPreview.js'

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
// onDraft(i), when given, adds a per-row "↻ Draft this image" retry button — for a DEFERRED row
// whose images the auto-draft couldn't fill. Omitted for proposals, which arrive with a draft
// already in the box, so the ReviewDrawer caller is unaffected.
export default function ProposalEditors({ proposals, values, onChange, file, sc, onDraft, draftingIdx = null, onApplyToSimilar = null, onCrossCheck = null }) {
  const [checks, setChecks] = useState({})       // idx → {verdict, second_opinion, …} | 'loading'
  if (!proposals?.length) return null
  const many = proposals.length > 1
  const undrafted = !!onDraft   // an evidence row: no drafts, so the header must not claim any
  const runCheck = (i) => {
    setChecks((c) => ({ ...c, [i]: 'loading' }))
    Promise.resolve(onCrossCheck && onCrossCheck(i)).then((v) => setChecks((c) => ({ ...c, [i]: v || 'none' })))
  }
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
              {/* Retry drafting THIS image. Descriptions generate automatically when the card comes
                  into view; this per-image button is the recovery path for an image the auto-draft
                  couldn't fill (vision was unavailable) — not a primary "Draft with AI" action. The
                  model sees one image, so the button lives on the image's own row. */}
              {onDraft && (
                <button type="button" className="evcard-draft-btn" disabled={draftingIdx != null}
                        title="Draft a description for this image — you still approve it"
                        onClick={() => onDraft(i)}>
                  {draftingIdx === i ? 'Drafting…' : '↻ Draft this image'}
                </button>
              )}
              {/* Refine the draft (#131, extended P1) — re-ask the vision model with an extra steer:
                  a shorter/fuller take, a fresh regenerate, or one of the four content/tone steers
                  (mention the numbers · ignore colours · professional tone · plain language). Each is
                  a bounded steer, not a free prompt; shown only once there's a draft to refine, and
                  disabled while a draft is in flight exactly as the original three are. The reviewer
                  still approves the result. */}
              {onDraft && filled && (
                <span className="evcard-refine">
                  {[['numbers', 'Mention the numbers'], ['no_colour', 'Ignore colours'],
                    ['professional', 'Professional tone'], ['plain', 'Plain language'],
                    ['shorter', 'Shorter'], ['detailed', 'More detail'], ['regenerate', '↻ Regenerate']].map(([k, label]) => (
                    <button key={k} type="button" className="evcard-refine-btn" disabled={draftingIdx != null}
                            title={`Re-draft this description — ${label.toLowerCase()}`}
                            onClick={() => onDraft(i, k)}>{label}</button>
                  ))}
                </span>
              )}
              {/* Hear it (trust): play this value through the browser's LOCAL speech synthesis
                  with the screen-reader announcement ("Image, …"), so the reviewer judges by
                  EAR whether the description actually conveys the image. Private, on-device. */}
              {srSupported() && filled && (
                <button type="button" className="evcard-similar-btn"
                        title="Hear this read aloud the way a screen reader announces it"
                        onClick={() => speakAsScreenReader(sc, values[i])}>🔊 Hear it</button>
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
              {/* Cross-check (#123): a second, independent AI look confirms the description matches the
                  image (or flags a mismatch + shows what it saw) — a real verification, not a score. */}
              {onCrossCheck && filled && (
                <button type="button" className="evcard-similar-btn" disabled={checks[i] === 'loading'}
                        title="Have the AI independently re-describe this image and compare"
                        onClick={() => runCheck(i)}>
                  {checks[i] === 'loading' ? 'Cross-checking…' : '⚖ Cross-check'}
                </button>
              )}
              {checks[i] && checks[i] !== 'loading' && (
                checks[i] === 'none' ? (
                  <p className="muted" style={{ fontSize: 11.5, margin: '4px 0 0' }}>Cross-check unavailable for this image.</p>
                ) : checks[i].verdict === 'consistent' ? (
                  <p style={{ fontSize: 11.5, margin: '4px 0 0', color: '#0F6E56' }}>✓ Cross-checked — a second independent look agrees with this description.</p>
                ) : (
                  <p style={{ fontSize: 11.5, margin: '4px 0 0', color: '#BA7517' }}>
                    ⚠ Second opinion differs — the AI independently saw: “{checks[i].second_opinion}”. Confirm the wording.
                  </p>
                )
              )}
              {/* Consensus computed at draft time (two models already ran) — shown automatically
                  so the reviewer sees agreement without clicking Cross-check. On-demand check wins. */}
              {!checks[i] && p?.agreement && (
                p.agreement.verdict === 'consistent' ? (
                  <p style={{ fontSize: 11.5, margin: '4px 0 0', color: '#0F6E56' }}>✓ Two models agree on this description{p.agreement.validator_model ? ` (${p.agreement.validator_model} confirmed)` : ''}.</p>
                ) : (
                  <p style={{ fontSize: 11.5, margin: '4px 0 0', color: '#BA7517' }}>
                    ⚠ A second model saw it differently: “{p.agreement.second_opinion}”. Confirm the wording.
                  </p>
                )
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
