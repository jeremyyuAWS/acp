import { useState, useEffect } from 'react'
import { getFileThumbnail, getFilePage, getFileGeometry } from './api.js'

// A cropped close-up of the bounding box, so the reviewer can inspect the flagged object WITHOUT
// leaving the card (ADR 0018 Slice 3 — zoom-to-object / crop-beside-full). Pure CSS on the page
// render already fetched: the container takes the box's aspect ratio, and the render is used as a
// background scaled so the box fills the frame. No second network call, no new image.
function cropStyle(url, box) {
  const w = Math.min(0.999, Math.max(0.001, box.w))
  const h = Math.min(0.999, Math.max(0.001, box.h))
  return {
    backgroundImage: `url(${url})`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${100 / w}%`,               // width scaled so the box width fills the frame (aspect kept)
    backgroundPosition: `${(box.x / (1 - w)) * 100}% ${(box.y / (1 - h)) * 100}%`,
    aspectRatio: `${w} / ${h}`,
  }
}

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
export default function Thumbnail({ scanId, file, page = 1, locator = null, className = '', maxHeight = 240, kindLabel = null }) {
  const [url, setUrl] = useState(null)
  const [box, setBox] = useState(null)      // {page,x,y,w,h} normalized, or null
  const [geomResolved, setGeomResolved] = useState(false)   // has the geometry fetch settled?
  const [zoom, setZoom] = useState(false)   // Slice 3 — reveal the cropped close-up of the box
  const fallbackPage = Number.isInteger(page) && page > 0 ? page : 1

  // Resolve the box first (if a locator is given) — it may override which page we render.
  useEffect(() => {
    setBox(null)
    setGeomResolved(!locator)               // no locator → nothing to wait for; render immediately
    if (!scanId || !file || !locator) return
    let live = true
    getFileGeometry(scanId, file, locator).then((b) => {
      if (live) { setBox(b || null); setGeomResolved(true) }
    })
    return () => { live = false }
  }, [scanId, file, locator])

  const renderPage = box && box.page ? box.page : fallbackPage

  useEffect(() => {
    setUrl(null)
    if (!scanId || !file) return
    // When a locator is present, wait for the box to resolve before rendering — otherwise we'd
    // render the fallback page, then swap to the box's page (a visible flash of the wrong page).
    if (!geomResolved) return
    let objectUrl = null
    let live = true
    const png = renderPage === 1 ? getFileThumbnail(scanId, file) : getFilePage(scanId, file, renderPage)
    png.then((blob) => {
      if (!live || !blob) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [scanId, file, renderPage, geomResolved])

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
      {box && (
        <div className="thumb-tools">
          {quadrant && <span className="thumb-loc">Flagged object · {quadrant}</span>}
          <button type="button" className="thumb-zoom-btn" aria-pressed={zoom}
                  onClick={() => setZoom((z) => !z)}>
            {zoom
              ? (kindLabel ? `Hide ${kindLabel}` : 'Hide close-up')
              : (kindLabel ? `⤢ Zoom to ${kindLabel}` : '⤢ Zoom to object')}
          </button>
        </div>
      )}
      {box && zoom && (
        <figure className="thumb-crop" aria-label={kindLabel ? `Close-up of the flagged ${kindLabel}` : 'Close-up of the flagged object'}>
          <div className="thumb-crop-img" style={cropStyle(url, box)} />
          <figcaption>Close-up · {quadrant}</figcaption>
        </figure>
      )}
      {!box && quadrant && <figcaption className="thumb-loc">Flagged object · {quadrant}</figcaption>}
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
