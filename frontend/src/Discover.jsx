// Steps 1-3: Discover & Inventory (live) + Classify & Prioritize + Retain/Archive/Delete.
// Source connection + scan are live; the priority/retention columns are an illustrative
// preview of the governance layer (engines not built yet).
const PRIORITY = { error: ['high', '#FCEBEB', '#A32D2D'], issues: ['high', '#FCEBEB', '#A32D2D'],
  uncertain: ['medium', '#FAEEDA', '#854F0B'], ok: ['low', '#F1EFE8', '#5F5E5A'] }

function classify(f) {
  const st = f.status === 'error' ? 'error' : f.status === 'uncertain' ? 'uncertain' : f.compliant ? 'ok' : 'issues'
  return PRIORITY[st]
}
function retention(name) {
  const n = name.toLowerCase()
  if (/temp|draft|copy|old|backup/.test(n)) return ['delete', '#FCEBEB', '#A32D2D']
  if (/2019|2020|archive|deprecated/.test(n)) return ['archive', '#FAEEDA', '#854F0B']
  return ['keep', '#E7F0DC', '#3B6D11']
}

export default function Discover({ sources, files, busy, onScan }) {
  return (
    <>
      <section className="panel">
        <h2>Connected sources</h2>
        {sources.length === 0 && <p className="muted">No sources connected.</p>}
        {sources.map((s) => (
          <div className="source" key={s.id}>
            <div className="srcleft">
              <span className="srcicon" aria-hidden="true">▦</span>
              <div>
                <div className="srcname">{s.name}</div>
                <div className="muted">Google Drive · {s.files} files · {s.access}</div>
              </div>
            </div>
            <button disabled={busy} onClick={() => onScan('drive')}>{busy ? 'scanning…' : 'Run scan'}</button>
          </div>
        ))}
        <div className="source ghosted">
          <div className="srcleft"><span className="srcicon" aria-hidden="true">＋</span>
            <div><div className="srcname">Connect another source</div><div className="muted">SharePoint · OneDrive · Box · S3 — coming soon</div></div>
          </div>
          <button className="ghost" disabled>Connect</button>
        </div>
        <p className="muted" style={{ marginTop: 14 }}>Or <a href="#" onClick={(e) => { e.preventDefault(); onScan('local') }}>run a scan on the bundled sample corpus</a>.</p>
      </section>

      {files.length > 0 && (
        <section className="panel">
          <h2>Inventory · classified &amp; prioritized</h2>
          <table>
            <thead><tr><th>document</th><th>priority</th><th>retention</th></tr></thead>
            <tbody>
              {files.map((f) => {
                const [p, pbg, pfg] = classify(f); const [r, rbg, rfg] = retention(f.file)
                return (
                  <tr key={f.file}>
                    <td className="fname">{f.file}</td>
                    <td><span className="badge" style={{ background: pbg, color: pfg }}>{p}</span></td>
                    <td><span className="badge" style={{ background: rbg, color: rfg }}>{r}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="muted" style={{ marginTop: 12 }}>AI flags duplicates, superseded, and legal-hold before assessment. <span style={{ color: '#854F0B' }}>Priority &amp; retention are a preview.</span></p>
        </section>
      )}
    </>
  )
}
