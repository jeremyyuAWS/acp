import { useState, useEffect } from 'react'
import { getFileThumbnail } from './api.js'

// Page-1 preview of a document (ADR 0015). Best-effort and self-hiding: if the backend has
// no thumbnail for this file (unsupported type, source unreachable, render failed, SIM mode)
// it renders nothing at all — a missing preview is never a broken image and never a layout hole.
export default function Thumbnail({ scanId, file, className = '', maxHeight = 240 }) {
  const [url, setUrl] = useState(null)

  useEffect(() => {
    setUrl(null)
    if (!scanId || !file) return
    let objectUrl = null
    let live = true
    getFileThumbnail(scanId, file).then((blob) => {
      if (!live || !blob) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [scanId, file])

  if (!url) return null
  return (
    <figure className={`thumb ${className}`.trim()}>
      <img src={url} alt={`Preview of ${file || 'document'} — page 1`} loading="lazy"
           style={{ maxHeight }} />
    </figure>
  )
}
