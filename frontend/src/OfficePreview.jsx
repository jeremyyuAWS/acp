import { useState, useEffect } from 'react'
import { extractOfficePreview } from './officePreview.js'

// Renders the real content of an uploaded Office file (DOCX/PPTX/XLSX) — text, headings,
// tables and images extracted from the OOXML in the browser. The injected HTML is built
// from escaped text + our own blob-URL images, so it's safe.
export default function OfficePreview({ blob, name, className = '', highlight = false }) {
  const [html, setHtml] = useState(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    let live = true
    setHtml(null); setErr(false)
    extractOfficePreview(blob, name, { highlight }).then((h) => { if (live) setHtml(h || '') }).catch(() => { if (live) setErr(true) })
    return () => { live = false }
  }, [blob, name, highlight])

  if (err) return <div className="scanplaceholder"><span style={{ fontSize: 46 }} aria-hidden="true">📄</span><div className="muted">{name}</div></div>
  if (html == null) return <div className={`opwrap oploading ${className}`}><span className="spinner" /> <span className="muted">rendering preview…</span></div>
  return <div className={`opwrap ${className}`} role="document" aria-label={`${name} preview`} dangerouslySetInnerHTML={{ __html: html }} />
}
