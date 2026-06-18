import Drawer from './Drawer.jsx'

export default function ReviewDrawer({ item, onClose, onAct }) {
  if (!item) return null
  return (
    <Drawer title={item.title} subtitle={item.file ? `${item.file}${item.rule ? ` · ${item.rule}` : ''}` : item.meta} onClose={onClose}>
      <div className="conf" style={{ margin: '10px 0 6px' }}>
        <span className="conftrack" style={{ width: 130 }}><i style={{ width: `${item.conf}%`, background: item.conf >= 55 ? '#F5B400' : '#F0524A' }} /></span>
        <span className="muted">{item.conf}% agent confidence</span>
      </div>

      {item.before && (
        <>
          <h4 className="drawerh">Proposed fix · before → after</h4>
          <div className="diffbox before"><span className="difftag">before</span><code>{item.before}</code></div>
          <div className="diffbox after"><span className="difftag">after</span><code>{item.after}</code></div>
        </>
      )}

      <p className="muted" style={{ marginTop: 12 }}>{item.note || 'The agent proposes this fix; a human confirms because confidence is below the auto-apply threshold. Approving re-validates the file against all engines.'}</p>

      <div className="emptyactions" style={{ justifyContent: 'flex-start', marginTop: 16, flexWrap: 'wrap' }}>
        <button onClick={() => onAct(item.id, 'approved')}>✓ approve fix</button>
        <button className="ghost" onClick={() => onAct(item.id, 'self')}>✋ I’ll fix it myself</button>
        <button className="ghost" onClick={() => onAct(item.id, 'rejected')}>✕ reject</button>
      </div>
      <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>Choose “I’ll fix it myself” to take ownership — you remediate in the source, then re-scan to confirm.</p>
    </Drawer>
  )
}
