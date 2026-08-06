import { useEffect, useRef, useState } from 'react'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

// Renders the first page(s) of a PDF to a <canvas> via pdf.js — works in any
// browser regardless of an inline-PDF viewer, so the user always sees their
// actual document. pdf.js is lazy-loaded so it doesn't weigh down the bundle.
export default function PdfPreview({ url, pages = 2 }) {
  const wrapRef = useRef(null)
  const [state, setState] = useState('loading')
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
        const pdf = await pdfjs.getDocument({ url }).promise
        if (cancelled) return
        const wrap = wrapRef.current; if (!wrap) return
        wrap.innerHTML = ''
        const n = Math.min(pages, pdf.numPages)
        for (let p = 1; p <= n; p++) {
          const page = await pdf.getPage(p)
          const base = page.getViewport({ scale: 1 })
          const scale = Math.min(1.5, (wrap.clientWidth || 600) / base.width)
          const vp = page.getViewport({ scale })
          const canvas = document.createElement('canvas')
          canvas.width = vp.width; canvas.height = vp.height; canvas.className = 'pdfpage'
          wrap.appendChild(canvas)
          await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise
          if (cancelled) return
        }
        if (!cancelled) setState('ready')
      } catch { if (!cancelled) setState('error') }
    })()
    return () => { cancelled = true }
  }, [url, pages])
  return (
    <div className="pdfpreview">
      {state === 'loading' && <div className="muted" style={{ padding: 24 }}>Rendering preview…</div>}
      {state === 'error' && <div className="bapdffallback"><span className="muted">Couldn’t render inline.</span> <a href={url} target="_blank" rel="noreferrer">Open the document ↗</a></div>}
      <div ref={wrapRef} className="pdfpages" />
    </div>
  )
}
