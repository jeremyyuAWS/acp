import { docIdentity, locationTrail } from './reviewGrouping.js'
import { locationLabel } from './reviewCard.js'

// WHICH document am I changing? — the one question a review card must answer before any other.
//
// A card reading "HTML — Automatic fix applied — verify the result" names no document, and an
// estate holding Clinical-FAQ-39.html beside Clinical-FAQ-54.html cannot be reviewed from the
// rule name alone. A reviewer approving a change to the wrong file is the worst outcome this
// screen can produce, and it is silent.
//
// Renders the filename as the primary label, then everything else known about WHERE the
// document lives — directory, source, department, owner — and WHERE in it the criterion fails
// (hitl_queue.page/pages, via the shared locationLabel). Every segment is omitted when its
// data is absent: this component never prints a placeholder that reads like a real location.
//
// `size`: 'row' for a card line, 'head' for a document-group heading.
export default function DocIdentity({ item, meta = null, size = 'row', showPage = true }) {
  const id = docIdentity(item, meta)
  const trail = locationTrail(id)
  const page = showPage ? locationLabel(item) : null
  const head = size === 'head'
  // The full locator, for the reviewer who needs to be certain rather than merely confident.
  const title = [id.path, ...(id.owner ? [`owner: ${id.owner}`] : [])].join(' · ')

  return (
    <span className={`docid docid-${size}`} title={title}>
      <span className="docid-line">
        {id.ext && <span className="docid-ext" aria-hidden="true">{id.ext.toUpperCase()}</span>}
        <b className="docid-name">{id.name}</b>
        {page && <span className="docid-page">{page}</span>}
      </span>
      {(trail.length > 0 || id.owner) && (
        <span className="docid-loc muted">
          {trail.map((seg, i) => (
            <span key={`${seg}-${i}`}>
              {i > 0 && <span className="docid-sep" aria-hidden="true"> › </span>}
              {seg}
            </span>
          ))}
          {id.owner && <span className="docid-owner">{trail.length > 0 ? ' · ' : ''}{id.owner}</span>}
        </span>
      )}
      {/* The directory is the segment that most often does not exist: Drive discovery records
          only a file's name and id, never its folder. Saying so once, on the document heading,
          is honest — silently showing a bare filename reads as "this file is at the root". */}
      {head && !id.dir && <span className="docid-nopath muted" title="Drive and SharePoint discovery records a file's name and id, not its folder — so ACP has no directory to show for this document.">no folder recorded</span>}
    </span>
  )
}
