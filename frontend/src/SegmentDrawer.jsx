import Drawer from './Drawer.jsx'
import WindowedRows from './WindowedRows.jsx'
import SearchFilterBar, { useSearchFilter, matchesFilters } from './SearchFilterBar.jsx'
import { statusOf, STATUS_BADGE } from './FileDrawer.jsx'

// Facets on the drawer are light — the segment is already one slice (a status,
// a risk tag, a type), so type + department narrow within it and search does
// the pinpoint work. useSearchFilter state lives per-drawer-instance and
// resets when the drawer unmounts, which is the intuitive behavior.
const FACETS = [
  { key: 'type', label: 'Type', get: (f) => (f.type || f.file?.split('.').pop() || '').toUpperCase() },
  { key: 'department', label: 'Dept', get: (f) => f.department },
]

export default function SegmentDrawer({ title, subtitle, files, onClose, onPickFile }) {
  const sf = useSearchFilter()
  const shown = sf.active ? files.filter(matchesFilters(sf, FACETS, (f) => f.file)) : files
  return (
    <Drawer title={title} subtitle={subtitle} onClose={onClose}>
      {files.length === 0 ? <p className="muted" style={{ marginTop: 10 }}>No documents.</p> : (
        <>
          {files.length > 8 && (
            <SearchFilterBar ctl={sf} items={files} facets={FACETS} noun="documents"
                             placeholder="Search this list by filename…" />
          )}
          {shown.length === 0 ? <p className="muted" style={{ marginTop: 10 }}>No documents match — <button className="ghost small" onClick={sf.clear}>clear the filters</button>.</p> : (
            <div className="findings" style={{ marginTop: 10 }}>
              <WindowedRows items={shown} renderRow={(f) => {
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
        </>
      )}
    </Drawer>
  )
}
