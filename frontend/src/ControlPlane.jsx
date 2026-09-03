import { useState, useEffect } from 'react'
import { getEstate } from './api.js'

// The estate, by department and by owner, for the signed-in tenant.
//
// "Filter by dept, user, Enterprise" from the v2 requirements. Enterprise IS the tenant, and it
// is not a control here on purpose: the server takes it from the request, because a
// caller-settable tenant is not a filter but the absence of isolation wearing a filter's
// clothes. What the operator can narrow is their OWN estate.
//
// READ-ONLY, and that is the scope of this slice. Every number is a count the store already
// records; nothing here writes. A control plane that could edit an estate it cannot yet fully
// describe would be the wrong thing to build second.

const fmt = (n) => (n ?? 0).toLocaleString()

export default function ControlPlane() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(true)
  const [dept, setDept] = useState('')
  const [owner, setOwner] = useState('')

  useEffect(() => {
    let live = true
    setBusy(true)
    getEstate(dept, owner)
      .then((d) => { if (live) { setData(d); setErr('') } })
      .catch((e) => { if (live) setErr(e?.message || 'could not load the estate') })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [dept, owner])

  if (err) return <p role="alert" style={{ fontSize: 13, color: 'var(--error-fg-strong)' }}>⚠ {err}</p>
  if (!data && busy) return <p className="muted" style={{ fontSize: 13 }}>Loading the estate…</p>
  if (!data) return null

  const clear = dept || owner
    ? <button className="ghost small" onClick={() => { setDept(''); setOwner('') }}>Clear filter</button>
    : null

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Estate
        <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}> · by department and owner</span>
      </h3>

      {/* WHOSE estate, said before any number. Same rule as ScopeBanner (#164): no total without
          a statement of what it counts. Here the denominator is a tenant, and a reader who
          cannot see which one has no way to know whether a small number is a small estate or
          somebody else's. */}
      <p className="muted" style={{ fontSize: 12.5 }}>
        <b>{fmt(data.documents)}</b> document{data.documents === 1 ? '' : 's'} for <b>{data.tenant}</b>
        {data.filtered
          ? <> · filtered to {data.filters.department ? `department “${data.filters.department}”` : ''}
              {data.filters.department && data.filters.owner ? ' and ' : ''}
              {data.filters.owner ? `owner “${data.filters.owner}”` : ''}</>
          : null}
        {' '}{clear}
      </p>

      {/* An empty estate and an empty FILTER RESULT are different facts that look identical as a
          zero, so they are worded differently. The first also names the likeliest cause: rows
          written before the tenant column existed are excluded rather than shown to everyone
          (#159), which is deliberate and is invisible without saying so. */}
      {data.documents === 0 && (
        <p className="muted" style={{ fontSize: 12.5 }}>
          {data.filtered
            ? 'No documents match this filter. The estate itself is not empty — clear the filter to see it.'
            : 'No documents recorded for this tenant. Scans that ran before documents carried a '
              + 'tenant column are excluded rather than attributed to everyone; they appear once '
              + 'backfilled (ACP_LEGACY_SCAN_OWNER).'}
        </p>
      )}

      {data.departments.length > 0 && (
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%', marginTop: 10 }}>
          <caption className="sronly">Documents per department for this tenant</caption>
          <thead>
            <tr>
              <th scope="col" style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Department</th>
              <th scope="col" style={{ textAlign: 'right', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Documents</th>
              <th scope="col" style={{ textAlign: 'right', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Owners</th>
            </tr>
          </thead>
          <tbody>
            {data.departments.map((r) => (
              <tr key={r.department}>
                <th scope="row" style={{ textAlign: 'left', fontWeight: 400, padding: '3px 8px' }}>
                  <button className="linklike" onClick={() => setDept(r.department === dept ? '' : r.department)}
                          aria-pressed={r.department === dept}>{r.department}</button>
                </th>
                <td style={{ textAlign: 'right', padding: '3px 8px' }}>{fmt(r.documents)}</td>
                <td style={{ textAlign: 'right', padding: '3px 8px' }}>{fmt(r.owners)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data.owners.length > 0 && (
        <>
          <h4 style={{ margin: '16px 0 6px', fontSize: 11, letterSpacing: '.08em',
                       textTransform: 'uppercase', color: 'var(--muted)' }}>By owner</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {data.owners.map((o) => (
              <button key={o.owner} className={owner === o.owner ? 'fchip on' : 'fchip'}
                      aria-pressed={owner === o.owner}
                      onClick={() => setOwner(o.owner === owner ? '' : o.owner)}>
                {o.owner} <span className="muted">· {fmt(o.documents)}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
