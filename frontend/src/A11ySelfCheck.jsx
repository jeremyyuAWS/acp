import { useState } from 'react'

// Dev/demo-only overlay: runs the bundled axe-core engine against the live app and
// lists any WCAG 2.1 A/AA violations — the product scanning itself, so these gaps
// never regress. Mounted only when import.meta.env.DEV or the ?a11y query flag is set.
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
const IMPACT_COLOR = { critical: '#1F5FA8', serious: '#D85A30', moderate: '#854F0B', minor: '#5F5E5A' }
const fmtSc = (tags) => tags.map((t) => { const d = t.replace(/^wcag/, ''); return /^\d+$/.test(d) && d.length >= 3 ? `${d[0]}.${d[1]}.${d.slice(2)}` : null }).filter(Boolean)

export default function A11ySelfCheck() {
  const [open, setOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState(null)

  const run = async () => {
    setRunning(true); setErr(null)
    try {
      const mod = await import('axe-core'); const axe = mod.default || mod
      const r = await axe.run(document.body, { resultTypes: ['violations'], runOnly: { type: 'tag', values: TAGS } })
      setResult({ at: new Date().toLocaleTimeString(), violations: r.violations })
    } catch (e) { setErr(String(e)) } finally { setRunning(false) }
  }
  const reveal = () => { setOpen(true); if (!result && !running) run() }

  const v = result?.violations || []
  const nodes = v.reduce((a, x) => a + x.nodes.length, 0)

  return (
    <>
      <button className="a11yfab" aria-label="Run an accessibility self-check on this page" title="Accessibility self-check (axe-core)" onClick={() => (open ? setOpen(false) : reveal())}>♿</button>
      {open && (
        <aside className="a11ypanel" role="dialog" aria-label="Accessibility self-check">
          <div className="a11yhd">
            <div><b>♿ a11y self-check</b><span className="muted"> · axe-core · WCAG 2.1 A/AA</span></div>
            <button className="ghost small" aria-label="Close self-check" onClick={() => setOpen(false)}>✕</button>
          </div>
          <div className="a11ybody">
            {running ? <p className="muted"><span className="spinner" /> scanning this view…</p>
              : err ? <p className="lockwarn">scan failed: {err}</p>
                : !result ? <p className="muted">—</p>
                  : v.length === 0
                    ? <div className="a11ypass">✓ No WCAG 2.1 A/AA violations on this view.</div>
                    : (<>
                      <div className="a11ysummary">{v.length} rule{v.length === 1 ? '' : 's'} · {nodes} element{nodes === 1 ? '' : 's'} flagged</div>
                      {v.map((x) => {
                        const scs = fmtSc(x.tags)
                        return (
                          <div className="a11yrow" key={x.id}>
                            <span className="a11yimpact" style={{ background: (IMPACT_COLOR[x.impact] || '#5F5E5A') + '22', color: IMPACT_COLOR[x.impact] || '#5F5E5A' }}>{x.impact}</span>
                            <div className="a11ymain">
                              <div>{x.help} <span className="muted">· {x.nodes.length}×</span></div>
                              <div className="muted a11yid">{x.id}{scs.length ? ` · WCAG ${scs.join(', ')}` : ''}</div>
                            </div>
                          </div>
                        )
                      })}
                    </>)}
          </div>
          <div className="a11yft">
            <button className="ghost small" disabled={running} onClick={run}>↻ Re-scan this view</button>
            <button className="ghost small" onClick={async () => { const { exportConformanceReport } = await import('./pdfReport.js'); exportConformanceReport() }}>⤓ Conformance report (PDF)</button>
            {result && <span className="muted" style={{ fontSize: 11 }}>scanned {result.at}</span>}
          </div>
        </aside>
      )}
    </>
  )
}
