import { useEffect, useMemo, useState } from 'react'
import { approveDispositionBatch, getLifecycleFileDetail, getLifecycleFiles } from './api.js'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'

// PRD §7.4 default sort. Conflicts first because they are the only state where NO rule won and
// the estate is waiting on a person; holds next because approving around one is the costliest
// mistake available here; then delete above archive, because a trash recommendation should never
// be the thing a tired reviewer reaches the bottom of the list to find.
const RANK = {
  'Conflict — review required': 0, Unevaluable: 1, Exempted: 2,
  'Delete Candidate': 3, 'Archive Candidate': 4,
}
const rank = (row) => (RANK[row.lifecycle_status] ?? 9)

// A batch may only cover rows sharing a policy, its VERSION and its action (PRD §8). That is the
// server's rule; grouping by exactly that key is what stops the UI ever offering a selection the
// server would have to refuse.
const groupKey = (row) => [row.policy_id || row.lifecycle_rule_id || 'none',
                           row.policy_version ?? 'none', row.action || 'none'].join(' ')

const RISK = { delete: 'Moves files to source trash', archive: 'Recoverable move' }

export default function DispositionReviewWorkspace({ scanId, status = '', policyId = '' }) {
  const [rows, setRows] = useState([])
  const [selected, setSelected] = useState(null)
  const [picked, setPicked] = useState(() => new Set())
  const [reviewed, setReviewed] = useState(() => new Set())
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [owner, setOwner] = useState('')

  useEffect(() => {
    let live = true
    setError(''); setNotice(''); setSelected(null); setPicked(new Set())
    getLifecycleFiles(scanId, { status, policyId })
      .then((r) => { if (live) setRows(r.rows || []) })
      .catch(() => { if (live) setError('Lifecycle review files could not be loaded.') })
    return () => { live = false }
  }, [scanId, status, policyId])

  const owners = useMemo(
    () => [...new Set(rows.map((r) => r.owner).filter(Boolean))].sort(), [rows])

  const groups = useMemo(() => {
    const filtered = owner ? rows.filter((r) => r.owner === owner) : rows
    const by = new Map()
    for (const row of [...filtered].sort((a, b) => rank(a) - rank(b)
      || String(a.file).localeCompare(String(b.file)))) {
      const key = groupKey(row)
      if (!by.has(key)) {
        by.set(key, {
          key,
          policyId: row.policy_id || row.lifecycle_rule_id || null,
          policyVersion: row.policy_version ?? null,
          action: row.action || null,
          rule: row.lifecycle_rule_id || 'No rule recorded',
          rows: [],
        })
      }
      by.get(key).rows.push(row)
    }
    return [...by.values()].sort((a, b) => rank(a.rows[0]) - rank(b.rows[0]))
  }, [rows, owner])

  // Only rows the server could actually accept are selectable: a pending audit id, a policy
  // version, and an action. A row without them is still shown and still reviewable one at a
  // time — hiding it would make the queue disagree with the estate counts above it.
  const approvable = (row) => Boolean(row.audit_id && row.policy_version != null && row.action)

  const inspect = (row) => {
    setReviewed((seen) => new Set(seen).add(row.file))
    return getLifecycleFileDetail(scanId, row.file).then(setSelected)
      .catch(() => setError('Lifecycle evidence could not be loaded.'))
  }

  const toggle = (group, row) => setPicked((old) => {
    const next = new Set(old)
    // Selection is bounded to ONE group. Crossing into another clears the first rather than
    // silently accumulating a batch the server would reject as heterogeneous.
    const crossing = [...next].some((id) => !group.rows.some((r) => r.audit_id === id))
    if (crossing) next.clear()
    if (next.has(row.audit_id)) next.delete(row.audit_id)
    else next.add(row.audit_id)
    return next
  })

  const activeGroup = groups.find((g) => g.rows.some((r) => picked.has(r.audit_id))) || null
  const destructive = activeGroup?.action === 'delete'
  const blocked = destructive && !reason.trim()

  const approve = () => {
    if (!activeGroup || picked.size === 0 || blocked) return
    setBusy(true); setError(''); setNotice('')
    approveDispositionBatch({
      auditIds: [...picked], policyId: activeGroup.policyId,
      policyVersion: activeGroup.policyVersion, action: activeGroup.action, reason,
    }).then((r) => {
      const done = new Set(r.approved || [])
      setRows((old) => old.filter((row) => !done.has(row.audit_id)))
      setPicked(new Set()); setReason('')
      // A partial batch is reported as a partial one (PRD §8) - never as "approved" alone.
      setNotice(`${(r.approved || []).length} approved`
        + ((r.refused || []).length ? `, ${r.refused.length} refused: `
          + r.refused.map((x) => `${x.audit_id} (${x.why})`).join('; ') : '')
        + ((r.already_decided || []).length ? `, ${r.already_decided.length} already decided` : '')
        + '. No source file was changed.')
    }).catch(() => setError('The batch was not approved. Nothing was changed.'))
      .finally(() => setBusy(false))
  }

  const total = groups.reduce((n, g) => n + g.rows.length, 0)
  const seen = groups.reduce((n, g) => n + g.rows.filter((r) => reviewed.has(r.file)).length, 0)

  return <section aria-labelledby="disposition-review-heading">
    <h2 id="disposition-review-heading">Disposition review queue</h2>
    <p role="status">
      {total.toLocaleString()} files in this view{status ? ` · ${status}` : ''}
      {policyId ? ` · policy ${policyId}` : ''} · {seen.toLocaleString()} reviewed,{' '}
      {(total - seen).toLocaleString()} remaining.
    </p>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}

    <label style={{ fontSize: 13 }}>Owner{' '}
      <select value={owner} onChange={(e) => setOwner(e.target.value)}>
        <option value="">All owners</option>
        {owners.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
      <div className="panel" style={{ maxHeight: 520, overflow: 'auto' }}>
        {groups.length === 0 && <p>No files match this view.</p>}
        {groups.map((group) => {
          const chosen = group.rows.filter((r) => picked.has(r.audit_id)).length
          return <section key={group.key} aria-label={`${group.rule} · ${group.action || 'no action'}`}>
            <h3 style={{ fontSize: 13 }}>
              {group.rule}{group.policyVersion != null && ` · version ${group.policyVersion}`}
              {' · '}{group.action || 'no proposed action'}{' · '}
              {group.rows.length.toLocaleString()} file{group.rows.length === 1 ? '' : 's'}
            </h3>
            {group.action && <p className="muted" style={{ fontSize: 12, margin: '0 0 6px' }}>
              {RISK[group.action] || 'Recommendation only'}
            </p>}
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {group.rows.map((row) => <li key={row.file} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <input type="checkbox" checked={picked.has(row.audit_id)}
                       disabled={!approvable(row)}
                       aria-label={`Select ${row.file} for batch approval`}
                       onChange={() => toggle(group, row)} />
                <button type="button" className="ghost" style={{ flex: 1, textAlign: 'left', marginBottom: 6 }}
                        aria-pressed={selected?.file === row.file} onClick={() => inspect(row)}>
                  <b>{row.file}</b><br />
                  <span className="muted">
                    {row.lifecycle_status || 'Active'} · {row.lifecycle_reason || 'No reason recorded'}
                    {reviewed.has(row.file) && ' · reviewed'}
                  </span>
                </button>
              </li>)}
            </ul>
            {chosen > 0 && <p className="muted" style={{ fontSize: 12 }}>{chosen} selected in this group</p>}
          </section>
        })}
      </div>
      <div>
        <LifecycleEvidencePanel file={selected} />
        {picked.size > 0 && activeGroup && <div className="panel">
          <h3 style={{ fontSize: 13 }}>Approve {picked.size.toLocaleString()} file{picked.size === 1 ? '' : 's'}</h3>
          <p className="muted" style={{ fontSize: 12 }}>
            {activeGroup.rule} · version {String(activeGroup.policyVersion)} · {activeGroup.action}.
            {' '}This records the decision. No source file is moved or deleted here.
          </p>
          <label style={{ display: 'block', fontSize: 13 }}>
            Reason{destructive ? ' (required for delete)' : ' (optional)'}
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
                      style={{ width: '100%' }} aria-describedby="batch-reason-note" />
          </label>
          <p id="batch-reason-note" className="muted" style={{ fontSize: 12 }}>
            Recorded against every row in this batch.
          </p>
          <button type="button" onClick={approve} disabled={busy || blocked}>
            {busy ? 'Approving' : `Approve ${picked.size.toLocaleString()}`}
          </button>
          {blocked && <p role="status" className="muted" style={{ fontSize: 12 }}>
            A delete approval must state a reason.
          </p>}
        </div>}
      </div>
    </div>
  </section>
}
