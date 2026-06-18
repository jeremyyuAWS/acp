import { useState } from 'react'
import Tag from './Tag.jsx'
import FileDrawer from './FileDrawer.jsx'

// Steps 1-3: Discover & Inventory + Classify & Prioritize + Retain/Archive/Delete.
// The agent auto-tags and classifies every document as it's discovered across sources.
const PRIORITY = { error: ['high', '#FCEBEB', '#A32D2D'], issues: ['high', '#FCEBEB', '#A32D2D'],
  uncertain: ['medium', '#FAEEDA', '#854F0B'], ok: ['low', '#F1EFE8', '#5F5E5A'] }
function classify(f) {
  const st = f.status === 'error' ? 'error' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'ok' : 'issues'
  return PRIORITY[st]
}
function retention(name, tags) {
  const n = name.toLowerCase()
  if (/temp|draft|copy|old|backup|2019|2020/.test(n)) return ['archive', '#FAEEDA', '#854F0B']
  if ((tags || []).includes('legal-hold')) return ['retain (legal hold)', '#EEEDFE', '#3C3489']
  return ['keep', '#E7F0DC', '#3B6D11']
}

export default function Discover({ sources, files, busy, onScan }) {
  const [sel, setSel] = useState(null)
  const tagged = files.filter((f) => (f.tags || []).length).length
  return (
    <>
      <div className="estatebar">
        <div>
          <b>{files.length} documents</b> discovered &amp; classified across {sources.length} sources
          <div className="muted" style={{ marginTop: 2 }}>the agent auto-tags each by content, risk (PII, legal-hold), and public exposure — {tagged} tagged</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Re-scan all sources'}</button>
      </div>

      {files.length === 0 ? (
        <p className="muted">No documents yet — run a scan from Integrations.</p>
      ) : (
        <section className="panel">
          <h2>Inventory · auto-classified &amp; tagged</h2>
          <table>
            <thead><tr><th>document</th><th>priority</th><th>retention</th></tr></thead>
            <tbody>
              {files.map((f) => {
                const [p, pbg, pfg] = classify(f); const [r, rbg, rfg] = retention(f.file, f.tags)
                return (
                  <tr key={f.file} className="filerow" role="button" tabIndex={0}
                    onClick={() => setSel(f)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(f) } }}>
                    <td className="fname">{f.file}
                      <div className="filemeta">
                        {f.sourceName && <span className="srcpill">{f.sourceName}</span>}
                        {(f.tags || []).slice(0, 4).map((t) => <Tag key={t} t={t} />)}
                      </div>
                    </td>
                    <td><span className="badge" style={{ background: pbg, color: pfg }}>{p}</span></td>
                    <td><span className="badge" style={{ background: rbg, color: rfg }}>{r}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="muted" style={{ marginTop: 12 }}>Tags, priority &amp; retention are assigned by the agent — duplicates, superseded, and legal-hold are flagged before assessment.</p>
        </section>
      )}
      {sel && <FileDrawer file={sel} onClose={() => setSel(null)} />}
    </>
  )
}
