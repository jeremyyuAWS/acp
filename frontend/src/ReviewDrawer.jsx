import Drawer from './Drawer.jsx'

export default function ReviewDrawer({ item, onClose, onAct }) {
  if (!item) return null
  const subtitle = item.file ? item.file + (item.rule ? ' · ' + item.rule : '') : item.meta
  return (
    <Drawer title={item.title} subtitle={subtitle} onClose={onClose}>
      <div className="conf" style={{ margin: '10px 0 6px' }}>
        <span className="conftrack" style={{ width: 130 }}><i style={{ width: `${item.conf}%`, background: item.conf >= 55 ? '#BF8C00' : '#2E72C9' }} /></span>
        <span className="muted">{item.conf}% agent confidence</span>
      </div>

      {item.before && (
        <>
          <h4 className="drawerh">Proposed fix &middot; before &rarr; after</h4>
          <div className="diffbox before"><span className="difftag">before</span><code>{item.before}</code></div>
          <div className="diffbox after"><span className="difftag">after</span><code>{item.after}</code></div>
        </>
      )}

      <p className="muted" style={{ marginTop: 12 }}>{item.note || 'The agent proposes this fix; a human confirms because confidence is below the auto-apply threshold. Approving re-validates the file against all engines.'}</p>

      <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 16, flexWrap: 'wrap' }}>
        <button onClick={() => onAct(item.id, 'approved')}>&#10003; approve fix</button>
        <button className="ghost" onClick={() => onAct(item.id, 'self')}>&#9995; I&apos;ll fix it myself</button>
        <button className="ghost" style={{ color: '#1F5FA8' }} onClick={() => onAct(item.id, 'deferred')}>&#9208; defer to next cycle</button>
        <button className="ghost" onClick={() => onAct(item.id, 'rejected')}>&#10005; reject</button>
      </div>
      <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>Defer if the fix needs more information or belongs in a later remediation batch &mdash; it resurfaces on the next scheduled scan.</p>
    </Drawer>
  )
}
