import { useEffect, useState } from 'react'
import { getLifecycleFileDetail, getLifecycleFiles } from './api.js'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'

export default function DispositionReviewWorkspace({ scanId, status = '', policyId = '', candidateOnly = false }) {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true; setError(''); setSelected(null); setRows([]); setOffset(0); setLoading(true)
    getLifecycleFiles(scanId, { status, policyId, candidateOnly, offset: 0 }).then((r) => { if (live) { setRows(r.rows || []); setTotal(r.total ?? (r.rows || []).length); setLoading(false) } }).catch(() => { if (live) { setError('Lifecycle review files could not be loaded.'); setLoading(false) } })
    return () => { live = false }
  }, [scanId, status, policyId, candidateOnly])
  const loadMore = () => {
    const next = offset + 200; setLoading(true)
    getLifecycleFiles(scanId, { status, policyId, candidateOnly, offset: next }).then((r) => { setRows((old) => [...old, ...(r.rows || [])]); setTotal(r.total ?? total); setOffset(next) }).catch(() => setError('More lifecycle files could not be loaded.')).finally(() => setLoading(false))
  }
  const inspect = (row) => getLifecycleFileDetail(scanId, row.file).then(setSelected).catch(() => setError('Lifecycle evidence could not be loaded.'))
  return <section aria-labelledby="disposition-review-heading">
    <h2 id="disposition-review-heading">Disposition review queue</h2>
    <p role="status">{loading && rows.length === 0 ? 'Loading lifecycle files…' : `${total.toLocaleString()} files in this view${candidateOnly ? ' · disposition candidates' : ''}${status ? ` · ${status}` : ''}${policyId ? ` · policy ${policyId}` : ''}. Showing ${rows.length.toLocaleString()}.`}</p>
    {error && <p role="alert">{error}</p>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
      <div className="panel" style={{ maxHeight: 520, overflow: 'auto' }}><ul style={{ listStyle: 'none', padding: 0 }}>
        {rows.map((row) => <li key={row.file}><button type="button" className="ghost" style={{ width: '100%', textAlign: 'left', marginBottom: 6 }} aria-pressed={selected?.file === row.file} onClick={() => inspect(row)}><b>{row.file}</b><br /><span className="muted">{row.lifecycle_status || 'Active'} · {row.lifecycle_reason || 'No reason recorded'}</span></button></li>)}
      </ul></div>
      <LifecycleEvidencePanel file={selected} />
    </div>
    {rows.length < total && <button type="button" className="ghost" onClick={loadMore} disabled={loading}>{loading ? 'Loading…' : `Load 200 more (${(total - rows.length).toLocaleString()} remaining)`}</button>}
  </section>
}
