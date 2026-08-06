import Drawer from './Drawer.jsx'
import Tag from './Tag.jsx'
import { Donut } from './charts.jsx'
import { statusOf, STATUS_BADGE } from './FileDrawer.jsx'

export default function SourceDrawer({ source, files, onClose, onPickFile }) {
  if (!source) return null
  const certifiable = files.filter((f) => f.compliant).length
  const uncertain = files.filter((f) => f.status === 'uncertain').length
  const error = files.filter((f) => f.status === 'error').length
  const issues = Math.max(0, files.length - certifiable - uncertain - error)
  const segs = [
    { label: 'certifiable', value: certifiable, color: '#639922' },
    { label: 'issues', value: issues, color: '#BF8C00' },
    { label: 'uncertain', value: uncertain, color: '#D85A30' },
    { label: 'unanalysable', value: error, color: '#9a948f' },
  ].filter((s) => s.value > 0)
  const tagCount = {}
  files.forEach((f) => (f.tags || []).forEach((t) => { tagCount[t] = (tagCount[t] || 0) + 1 }))
  const topTags = Object.entries(tagCount).sort((a, b) => b[1] - a[1]).slice(0, 8)
  const flagged = files.filter((f) => (f.issues || []).length || f.status === 'error').sort((a, b) => (a.score ?? 0) - (b.score ?? 0)).slice(0, 6)

  return (
    <Drawer title={source.name} subtitle={`${source.dept} · ${(source.files || 0).toLocaleString()} docs · agent: ${source.agent}`} onClose={onClose}>
      <h4 className="drawerh">Compliance · sampled documents</h4>
      {segs.length ? <Donut segments={segs} caption="scanned" size={118} /> : <p className="muted">No scan data.</p>}

      {topTags.length > 0 && (
        <>
          <h4 className="drawerh">Tag mix · agent-assigned</h4>
          <div className="taglist">{topTags.map(([t, n]) => <span key={t} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}><Tag t={t} /><span className="muted" style={{ fontSize: 11 }}>{n}</span></span>)}</div>
        </>
      )}

      <h4 className="drawerh">Top flagged documents</h4>
      {flagged.length === 0 ? <p className="muted">All clear in this sample.</p> : (
        <div className="findings">
          {flagged.map((f) => {
            const st = statusOf(f); const [bg, fg] = STATUS_BADGE[st]
            return (
              <button className="filelistrow" key={f.file} onClick={() => onPickFile(f)}>
                <span className="fname" style={{ fontSize: 13, flex: 1, minWidth: 0 }}>{f.file}</span>
                <span className="badge" style={{ background: bg, color: fg }}>{st}</span>
                <span className="muted">{f.score == null ? 'n/a' : f.score}</span>
              </button>
            )
          })}
        </div>
      )}

      <h4 className="drawerh">Agent</h4>
      <p className="muted">Monitoring <b>{source.agent}</b> — auto-discovers, tags, and re-scans on change. Last sweep flagged {flagged.length} document(s) for remediation.</p>
    </Drawer>
  )
}
