// Enterprise source connectors. Google Drive is live; the rest are greyed "coming soon"
// (CSS grayscale on .off). Brand marks are simple inline SVG so nothing hotlinks.

function DriveMark() {
  return (
    <svg viewBox="0 0 87 78" width="26" height="26" aria-hidden="true">
      <path fill="#0066da" d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" />
      <path fill="#00ac47" d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9 9 0 0 0-1.2 4.5h27.5z" />
      <path fill="#ea4335" d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.85 11.5z" />
      <path fill="#00832d" d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" />
      <path fill="#2684fc" d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
      <path fill="#ffba00" d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" />
    </svg>
  )
}

function Tile({ bg, children }) {
  return <span style={{ width: 42, height: 42, borderRadius: 10, background: bg, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', flex: '0 0 auto' }}>{children}</span>
}

const G = (d) => <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>

const SOURCES = [
  { name: 'SharePoint', logo: <Tile bg="#036C70"><b style={{ fontSize: 16 }}>S</b></Tile> },
  { name: 'OneDrive', logo: <Tile bg="#0364B8">{G('M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6-1.5A3.5 3.5 0 0 1 19 18z')}</Tile> },
  { name: 'Google Drive', connected: true, logo: <Tile bg="#fff"><DriveMark /></Tile> },
  { name: 'Box', logo: <Tile bg="#0061D5"><b style={{ fontSize: 13 }}>box</b></Tile> },
  { name: 'Confluence', logo: <Tile bg="#1868DB"><b style={{ fontSize: 16 }}>C</b></Tile> },
  { name: 'File Shares', logo: <Tile bg="#E8A400">{G('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z')}</Tile> },
  { name: 'S3 / Blob', logo: <Tile bg="#E25444"><b style={{ fontSize: 13 }}>S3</b></Tile> },
  { name: 'Websites / CMS', logo: <Tile bg="#5F6B7A">{G('M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c2.5 2.5 2.5 15.5 0 18M12 3c-2.5 2.5-2.5 15.5 0 18')}</Tile> },
  { name: 'Git Repos', logo: <Tile bg="#F05133">{G('M6 3v12a3 3 0 0 0 3 3h6M6 6a2 2 0 1 0 0-.01M18 15a2 2 0 1 0 0 .01M9 18a2 2 0 1 0 0 .01')}</Tile> },
]

export default function Integrations({ sources, onScan, busy }) {
  const drive = sources[0]
  return (
    <>
      <p className="muted" style={{ margin: '6px 0 16px' }}>Connect the content stores mova scans. One connector is live today; the rest are on the roadmap.</p>
      <div className="intgrid">
        {SOURCES.map((s) => (
          <div className={s.connected ? 'intcard' : 'intcard off'} key={s.name}>
            <div className="intlogo">{s.logo}</div>
            <div className="intname">{s.name}</div>
            {s.connected ? (
              <span className="intstatus live"><span className="livedot" />connected{drive ? ` · ${drive.files} files` : ''}</span>
            ) : (
              <span className="intstatus">coming soon</span>
            )}
            {s.connected
              ? <button className="intbtn" disabled={busy} onClick={() => onScan('drive')}>{busy ? 'scanning…' : 'Run scan'}</button>
              : <button className="intbtn ghost" disabled>Connect</button>}
          </div>
        ))}
        <div className="intcard off" style={{ justifyContent: 'center' }}>
          <div className="intname" style={{ color: 'var(--muted)' }}>…and more</div>
        </div>
      </div>
    </>
  )
}
