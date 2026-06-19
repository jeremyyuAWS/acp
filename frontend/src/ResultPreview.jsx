import { useMemo, useState } from 'react'
import PdfPreview from './PdfPreview.jsx'
import OfficePreview from './OfficePreview.jsx'
import { remediateHtml } from './BeforeAfter.jsx'
import { remediateOffice } from './officeAudit.js'

const isHtml = (n) => /\.html?$/i.test(n || '')
const isPdf = (n) => /\.pdf$/i.test(n || '')

// Side-by-side "as received → remediated" file preview for the certificate page.
// HTML renders both versions live in the browser (fixes like contrast are visible).
// PDF/Office keep the original visual and surface the embedded structural fixes —
// alt text, titles, headers and language are non-visual by nature, so we show what
// changed under the hood honestly rather than fake a different-looking render. For
// Office the remediated file is genuinely produced and downloadable.
export default function ResultPreview({ file, srcText, pdfUrl, officeBlob, issues = [] }) {
  const name = file?.name || ''
  const rem = useMemo(() => (srcText && isHtml(name) ? remediateHtml(srcText) : null), [srcText, name])
  const [busy, setBusy] = useState(false)
  const fixes = issues.map((i) => (i.wcag || '').replace(/^(\d+\.\d+\.\d+)\s*·?\s*/, '$1 · ')).slice(0, 6)
  const ext = (name.split('.').pop() || '').toUpperCase()

  const dl = (blob, fn) => { const u = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = u; a.download = fn; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000) }
  const downloadOffice = async () => { if (!officeBlob || busy) return; setBusy(true); try { dl(await remediateOffice(officeBlob), `remediated-${name}`) } catch (e) { console.error('office remediation failed', e) } finally { setBusy(false) } }
  const downloadHtml = () => { if (rem) dl(new Blob([rem.html], { type: 'text/html' }), `remediated-${name.replace(/\.[^.]+$/, '')}.html`) }

  const docCard = (badge) => (
    <div className="rpdoc"><span className="rpdocicon" aria-hidden="true">{isPdf(name) ? '📕' : '📄'}</span><span className="fname">{name}</span>{badge}</div>
  )

  return (
    <section className="panel rppanel">
      <h2>Your document · before → after <span className="muted" style={{ fontWeight: 400 }}>· rendered in your browser, nothing uploaded</span></h2>
      <div className="baframes">
        <figure>
          <figcaption className="bafcap before">as received</figcaption>
          {isHtml(name) && srcText ? <iframe sandbox="" title="as received" srcDoc={srcText} />
            : isPdf(name) && pdfUrl ? <div className="rppdf"><PdfPreview url={pdfUrl} pages={1} /></div>
              : officeBlob ? <div className="rppdf"><OfficePreview blob={officeBlob} name={name} /></div>
                : docCard()}
        </figure>
        <figure>
          <figcaption className="bafcap after">remediated</figcaption>
          {isHtml(name) && rem ? <iframe sandbox="" title="remediated" srcDoc={rem.html} />
            : isPdf(name) && pdfUrl ? <div className="rppdf rpafter"><PdfPreview url={pdfUrl} pages={1} /><span className="rpbadge">✓ tags · alt · reading order embedded</span></div>
              : docCard(<span className="rpbadge">✓ accessible</span>)}
        </figure>
      </div>
      {!isHtml(name) && (
        <p className="muted rpnote">Accessibility fixes for {isPdf(name) ? 'PDF' : `${ext} (Office)`} files are <b>structural</b> — alt text, document title, table header rows and language are written into the file, so it looks identical but is now machine-readable by assistive technology.{fixes.length > 0 && <> Embedded: {fixes.join(' · ')}.</>}</p>
      )}
      {(rem || officeBlob) && (
        <div className="rpactions">
          {isHtml(name) && rem && <button className="ghost small" onClick={downloadHtml}>⤓ Download the remediated HTML</button>}
          {officeBlob && <button className="ghost small" onClick={downloadOffice} disabled={busy}>{busy ? 'Remediating…' : `⤓ Download the remediated ${ext}`}</button>}
        </div>
      )}
    </section>
  )
}
