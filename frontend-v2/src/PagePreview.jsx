import { useState, useEffect } from 'react'
import { getFilePage } from './api.js'

// "Locate in document" evidence — a rendered PNG of a specific page, so a reviewer never has
// to open the document and hunt. Best-effort and self-hiding: if the backend can't render it
// (non-PDF in phase 1, source unreachable, SIM), it shows a small labelled placeholder rather
// than a broken image. The backend clamps `page` to the document's real range.
export default function PagePreview({ scanId, file, page = 1, className = '', maxHeight = 260 }) {
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setUrl(null); setFailed(false)
    if (!scanId || !file) return
    let objectUrl = null
    let live = true
    getFilePage(scanId, file, page).then((blob) => {
      if (!live) return
      if (!blob) { setFailed(true); return }
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [scanId, file, page])

  if (failed) {
    return (
      <figure className={`pagepreview pagepreview--none ${className}`.trim()}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                       minWidth: 120, minHeight: 90, border: '1px dashed var(--line)',
                       borderRadius: 8, color: 'var(--muted, #6B6670)', fontSize: 11, textAlign: 'center', padding: 8 }}>
        Preview unavailable{page > 1 ? ` · page ${page}` : ''}
      </figure>
    )
  }
  if (!url) return null
  return (
    <figure className={`pagepreview ${className}`.trim()} style={{ margin: 0 }}>
      <img src={url} alt={`${file || 'document'} — page ${page}`} loading="lazy"
           style={{ maxHeight, maxWidth: '100%', borderRadius: 6, border: '1px solid var(--line)', display: 'block' }} />
      {page > 1 && <figcaption className="muted" style={{ fontSize: 11, marginTop: 3, textAlign: 'center' }}>Page {page}</figcaption>}
    </figure>
  )
}
