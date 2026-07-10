import { useState, useEffect } from 'react'
import { getFileThumbnail, getFilePage } from './api.js'

// A rendered page of a document (ADR 0015). Best-effort and self-hiding: if the backend has no
// render for this file (unsupported type — api/render.py is PDF-only — source unreachable,
// render failed, SIM mode) it renders nothing at all. A missing preview is never a broken image
// and never a layout hole.
//
// `page` is the page the FINDING sits on (hitl_queue.page), not always the cover. Both the fetch
// and the alt text used to be hardcoded to page 1, so a reviewer judging a finding on page 7 was
// shown page 1 and told, in the alt text, that it was page 1: a picture of the wrong page,
// correctly labelled. Page 1 still takes the cheaper /thumbnail route — the same blob cache the
// certification report warms.
export default function Thumbnail({ scanId, file, page = 1, className = '', maxHeight = 240 }) {
  const [url, setUrl] = useState(null)
  const n = Number.isInteger(page) && page > 0 ? page : 1

  useEffect(() => {
    setUrl(null)
    if (!scanId || !file) return
    let objectUrl = null
    let live = true
    const png = n === 1 ? getFileThumbnail(scanId, file) : getFilePage(scanId, file, n)
    png.then((blob) => {
      if (!live || !blob) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [scanId, file, n])

  if (!url) return null
  return (
    <figure className={`thumb ${className}`.trim()}>
      <img src={url} alt={`Page ${n} of ${file || 'the document'}`} loading="lazy"
           style={{ maxHeight }} />
    </figure>
  )
}
