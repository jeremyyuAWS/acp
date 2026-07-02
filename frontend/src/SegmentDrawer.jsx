import Drawer from './Drawer.jsx'
import WindowedRows from './WindowedRows.jsx'
import { statusOf, STATUS_BADGE } from './FileDrawer.jsx'

export default function SegmentDrawer({ title, subtitle, files, onClose, onPickFile }) {
  return (
    <Drawer title={title} subtitle={subtitle} onClose={onClose}>
      {files.length === 0 ? <p className="muted" style={{ marginTop: 10 }}>No documents.</p> : (
        <div className="findings" style={{ marginTop: 10 }}>
          <WindowedRows items={files} renderRow={(f) => {
            const st = statusOf(f); const [bg, fg] = STATUS_BADGE[st]
            return (
              <button className="filelistrow" key={f.file} onClick={() => onPickFile(f)}>
                <span className="fname" style={{ fontSize: 13, flex: 1, minWidth: 0 }}>{f.file}</span>
                {f.sourceName && <span className="srcpill">{f.sourceName}</span>}
                <span className="badge" style={{ background: bg, color: fg }}>{st}</span>
                <span className="muted">{f.score == null ? 'n/a' : f.score}</span>
              </button>
            )
          }} />
        </div>
      )}
    </Drawer>
  )
}
