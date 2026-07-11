import { useState, useEffect } from 'react'
import { getFileThumbnail, getFilePage, getFileGeometry } from './api.js'

// A rendered page of a document (ADR 0015). Best-effort and self-hiding: if the backend has no
// render for this file (unsupported type, source unreachable, render failed, SIM mode) it renders
// nothing at all. A missing preview is never a broken image and never a layout hole.
//
// `page` is the page the FINDING sits on (hitl_queue.page), not always the cover. Both the fetch
// and the alt text used to be hardcoded to page 1, so a reviewer judging a finding on page 7 was
// shown page 1 and told, in the alt text, that it was page 1: a picture of the wrong page,
// correctly labelled. Page 1 still takes the cheaper /thumbnail route — the same blob cache the
// certification report warms.
//
// ADR 0018 Slice 2 — when a `locator` (a finding's `part#rId`) is given, the component asks the
// backend for that shape's normalized bounding box and draws a red overlay on the render, so the
// reviewer sees *where* the issue is in <10s. The box carries its OWN page, so we render the page
// the geometry reports (not the `page` prop) to guarantee the box and the picture always agree.
// No box (non-pptx, grouped/inherited transform, SIM, any failure) → the plain large preview at
// the `page` prop, exactly as before. Honesty (ADR 0016): the box is a measured rect or absent.
export default function Thumbnail({ scanId, file, page = 1, locator = null, className = '', maxHeight = 240 }) {
  const [url, setUrl] = useState(null)
  const [box, setBox] = useState(null)      // {page,x,y,w,h} normalized, or null
  const fallbackPage = Number.isInteger(page) && page > 0 ? page : 1

  // Resolve the box first (if a locator is given) — it may override which page we render.
  useEffect(() => {
    setBox(null)
    if (!scanId || !file || !locator) return
    let live = true
    getFileGeometry(scanId, file, locator).then((b) => { if (live) setBox(b || null) })
    return () => { live = false }
  }, [scanId, file, locator])

  const renderPage = box && box.page ? box.page : fallbackPage

  useEffect(() => {
    setUrl(null)
    if (!scanId || !file) return
    let objectUrl = null
    let live = true
    const png = renderPage === 1 ? getFileThumbnail(scanId, file) : getFilePage(scanId, file, renderPage)
    png.then((blob) => {
      if (!live || !blob) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [scanId, file, renderPage])

  if (!url) return null
  const quadrant = box ? quad(box) : null
  return (
    <figure className={`thumb ${box ? 'thumb-boxed' : ''} ${className}`.trim()}>
      <span className="thumb-imgwrap">
        <img src={url} alt={`Page ${renderPage} of ${file || 'the document'}`} loading="lazy"
             style={{ maxHeight }} />
        {box && (
          <span className="evidence-box" aria-hidden="true"
                style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`,
                         width: `${box.w * 100}%`, height: `${box.h * 100}%` }} />
        )}
      </span>
      {quadrant && <figcaption className="thumb-loc">Flagged object · {quadrant}</figcaption>}
    </figure>
  )
}

// Derived location string ("top-right") — computed from the real box, never stored or guessed.
function quad(b) {
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2
  const v = cy < 0.4 ? 'top' : cy > 0.6 ? 'bottom' : 'middle'
  const h = cx < 0.35 ? 'left' : cx > 0.65 ? 'right' : 'center'
  return v === 'middle' && h === 'center' ? 'center' : `${v}-${h}`
}
