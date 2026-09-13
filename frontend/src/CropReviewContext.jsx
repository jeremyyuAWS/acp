import ProposalThumb, { isSafeThumb } from './ProposalThumb.jsx'
import { isReviewedCropEvidence } from './reviewCard.js'
import './crop-review-context.css'

// The stored thumbnail was produced from the same visible pixels as the OCR draft.
// No image fetch or AI request is made here, and older reviews do not acquire a new choice.
export default function CropReviewContext({ evidence, thumb, locator, draft, sourceUrl }) {
  if (!isReviewedCropEvidence(evidence)) return null
  const safeSourceUrl = typeof sourceUrl === 'string' && /^https:\/\//i.test(sourceUrl) ? sourceUrl : null
  return (
    <section className="crop-review-context" aria-label={`Visible crop review${locator ? ` for ${locator}` : ''}`}>
      <figure>
        {isSafeThumb(thumb)
          ? <ProposalThumb thumb={thumb} size={96} alt={`Saved visible crop${locator ? ` for ${locator}` : ''}`} />
          : <p className="muted">Visible-crop preview unavailable. Open the source document to inspect the picture.</p>}
        {isSafeThumb(thumb) && <figcaption>Saved visible-crop thumbnail · up to 96px. Check the source document for fine detail.</figcaption>}
      </figure>
      <div>
        <div className="crop-review-context-draft">
          <b>Visible-crop OCR draft</b>
          {typeof draft === 'string' && draft.trim()
            ? <pre>{draft}</pre>
            : <p>No visible-crop transcription is available. Inspect the source before describing it.</p>}
          {safeSourceUrl && <a href={safeSourceUrl} target="_blank" rel="noopener noreferrer">Open source document ↗</a>}
        </div>
        <b>Review the visible picture and its description</b>
        <p>The draft contains text read from the visible crop. Confirm those words and describe any useful diagram content in your own words.</p>
        <p><b>Keep image and describe:</b> the image stays. Your explicitly reviewed description is added beside it as selectable text and as alt text.</p>
        <p><b>Replacing the image:</b> automatic replacement is unavailable for this crop. A replacement must preserve its meaning and useful visual content.</p>
        <p className="crop-review-context-warning">Keeping and describing the image does not verify that the image-of-text finding is cleared.</p>
      </div>
    </section>
  )
}
