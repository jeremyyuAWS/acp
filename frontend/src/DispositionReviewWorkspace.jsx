import { useEffect, useState } from 'react'
import { getLifecycleFileDetail, getLifecycleFiles } from './api.js'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'

export default function DispositionReviewWorkspace({ scanId, status = '', policyId = '' }) {
  const [rows, setRows] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true; setError(''); setSelected(null)
    getLifecycleFiles(scanId, { status, policyId }).then((r) => { if (live) setRows(r.rows || []) }).catch(() => { if (live) setError('Lifecycle review files could not be loaded.') })
    return () => { live = false }
  }, [scanId, status, policyId])
  const inspect = (row) => getLifecycleFileDetail(scanId, row.file).then(setSelected).catch(() => setError('Lifecycle evidence could not be loaded.'))
  return <section aria-labelledby="disposition-review-heading">
    <h2 id="disposition-review-heading">Disposition review queue</h2>
    <p role="status">{rows.length.toLocaleString()} files in this view{status ? ` · ${status}` : ''}{policyId ? ` · policy ${policyId}` : ''}.</p>
    {error && <p role="alert">{error}</p>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
      <div className="panel" style={{ maxHeight: 520, overflow: 'auto' }}><ul style={{ listStyle: 'none', padding: 0 }}>
        {rows.map((row) => <li key={row.file}><button type="button" className="ghost" style={{ width: '100%', textAlign: 'left', marginBottom: 6 }} aria-pressed={selected?.file === row.file} onClick={() => inspect(row)}><b>{row.file}</b><br /><span className="muted">{row.lifecycle_status || 'Active'} · {row.lifecycle_reason || 'No reason recorded'}</span></button></li>)}
      </ul></div>
      <LifecycleEvidencePanel file={selected} />
    </div>
  </section>
}
