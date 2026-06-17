// Unified compliance across sources. The simulated estate connects several content
// stores; the mova Agent monitors each continuously. (Demo data — no real connections.)

function DriveMark() {
  return (
    <svg viewBox="0 0 87 78" width="24" height="24" aria-hidden="true">
      <path fill="#0066da" d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" />
      <path fill="#00ac47" d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9 9 0 0 0-1.2 4.5h27.5z" />
      <path fill="#ea4335" d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.85 11.5z" />
      <path fill="#00832d" d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" />
      <path fill="#2684fc" d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
      <path fill="#ffba00" d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" />
    </svg>
  )
}
const Tile = ({ bg, children }) => <span style={{ width: 40, height: 40, borderRadius: 10, background: bg, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', flex: '0 0 auto' }}>{children}</span>
const G = (d) => <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
const LOGO = {
  google_drive: <Tile bg="#fff"><DriveMark /></Tile>,
  sharepoint: <Tile bg="#036C70"><b style={{ fontSize: 15 }}>S</b></Tile>,
  confluence: <Tile bg="#1868DB"><b style={{ fontSize: 15 }}>C</b></Tile>,
  box: <Tile bg="#0061D5"><b style={{ fontSize: 12 }}>box</b></Tile>,
  web: <Tile bg="#5F6B7A">{G('M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c2.5 2.5 2.5 15.5 0 18M12 3c-2.5 2.5-2.5 15.5 0 18')}</Tile>,
}
const FUTURE = [
  { name: 'OneDrive', logo: <Tile bg="#0364B8">{G('M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6-1.5A3.5 3.5 0 0 1 19 18z')}</Tile> },
  { name: 'File Shares', logo: <Tile bg="#E8A400">{G('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z')}</Tile> },
  { name: 'S3 / Blob', logo: <Tile bg="#E25444"><b style={{ fontSize: 12 }}>S3</b></Tile> },
  { name: 'Git Repos', logo: <Tile bg="#F05133">{G('M6 3v12a3 3 0 0 0 3 3h6M6 6a2 2 0 1 0 0-.01M18 15a2 2 0 1 0 0 .01M9 18a2 2 0 1 0 0 .01')}</Tile> },
]

export default function Integrations({ sources, onScan, busy }) {
  const total = sources.reduce((a, s) => a + (s.files || 0), 0)
  return (
    <>
      <div className="estatebar">
        <div>
          <b>{sources.length} sources</b> · {total.toLocaleString()} documents under continuous compliance monitoring
          <div className="muted" style={{ marginTop: 2 }}>the mova Agent discovers, classifies, and re-scans across every store</div>
        </div>
        <button disabled={busy} onClick={() => onScan('all')}>{busy ? 'scanning…' : 'Scan all sources'}</button>
      </div>
      <div className="intgrid">
        {sources.map((s) => (
          <div className="intcard" key={s.id}>
            <div className="intlogo">{LOGO[s.type] || LOGO.web}</div>
            <div className="intname">{s.name}</div>
            <div className="muted" style={{ fontSize: 12 }}>{s.dept} · {(s.files || 0).toLocaleString()} docs</div>
            <span className="intstatus live"><span className="livedot" />agent · {s.agent}</span>
            <button className="intbtn" disabled={busy} onClick={() => onScan(s.id)}>{busy ? 'scanning…' : 'Run scan'}</button>
          </div>
        ))}
        {FUTURE.map((s) => (
          <div className="intcard off" key={s.name}>
            <div className="intlogo">{s.logo}</div>
            <div className="intname">{s.name}</div>
            <span className="intstatus">coming soon</span>
            <button className="intbtn ghost" disabled>Connect</button>
          </div>
        ))}
      </div>
    </>
  )
}
