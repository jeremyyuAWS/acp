import { useEffect, useMemo, useState } from 'react'
import { approveDispositionBatch, getLifecycleFileDetail, getLifecycleFileHistory, getLifecycleFiles } from './api.js'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'
import { recoveryFor, recoveryLine, canUndo } from './recoveryPolicy.js'

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

// PRD §7.4 age filter. Buckets rather than a date picker: the question a reviewer actually has
// is "show me the genuinely old ones", and retention policy is written in these units.
const AGES = [['', 'Any age'], ['30', 'Older than 30 days'], ['90', 'Older than 90 days'],
              ['365', 'Older than 1 year'], ['1095', 'Older than 3 years']]

/** Days since the file was last modified at source, or null when nothing recorded it. */
export function ageInDays(row, now = Date.now()) {
  const raw = row.source_modified || row.created_at
  if (!raw) return null
  const then = Date.parse(raw)
  if (Number.isNaN(then)) return null
  return Math.floor((now - then) / 86400000)
}

export default function DispositionReviewWorkspace({
  scanId, status = '', policyId = '', candidateOnly = true, source = null,
}) {
  const [rows, setRows] = useState([])
  const [selected, setSelected] = useState(null)
  const [picked, setPicked] = useState(() => new Set())
  const [reviewed, setReviewed] = useState(() => new Set())
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [owner, setOwner] = useState('')
  const [fileType, setFileType] = useState('')
  const [minAge, setMinAge] = useState('')
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(50)

  useEffect(() => {
    let live = true
    setError(''); setNotice(''); setSelected(null); setPicked(new Set())
    getLifecycleFiles(scanId, { status, policyId, candidateOnly })
      .then((r) => { if (live) setRows(r.rows || []) })
      .catch(() => { if (live) setError('Lifecycle review files could not be loaded.') })
    return () => { live = false }
  }, [scanId, status, policyId, candidateOnly])

  const owners = useMemo(
    () => [...new Set(rows.map((r) => r.owner).filter(Boolean))].sort(), [rows])
  // Derived from the rows in hand rather than a hardcoded vocabulary: estate_inventory.classify
  // decides what a format IS, and a list copied here would drift from it silently.
  const fileTypes = useMemo(
    () => [...new Set(rows.map((r) => r.format || r.doc_class).filter(Boolean))].sort(), [rows])

  const filteredRows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (owner && r.owner !== owner) return false
      if (actionFilter && r.action !== actionFilter) return false
      if (fileType && (r.format || r.doc_class) !== fileType) return false
      if (minAge) {
        const age = ageInDays(r)
        // A file with no recorded date is NOT silently treated as new. An age filter that
        // quietly drops undated rows would shrink the queue without saying so, and the count
        // above it is the number a reviewer trusts.
        if (age === null || age < Number(minAge)) return false
      }
      if (needle && ![r.file, r.owner, r.lifecycle_status, r.lifecycle_reason, r.lifecycle_rule_id]
        .some((value) => String(value || '').toLowerCase().includes(needle))) return false
      return true
    }).sort((a, b) => rank(a) - rank(b) || String(a.file).localeCompare(String(b.file)))
  }, [rows, owner, actionFilter, fileType, minAge, search])

  useEffect(() => { setPage(0) }, [owner, actionFilter, fileType, minAge, search, pageSize, rows])

  const makeGroups = (sourceRows) => {
    const by = new Map()
    for (const row of sourceRows) {
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
  }
  const groups = useMemo(() => makeGroups(filteredRows), [filteredRows])
  const lastPage = Math.max(0, Math.ceil(filteredRows.length / pageSize) - 1)
  const currentPage = Math.min(page, lastPage)
  const visibleGroups = makeGroups(filteredRows.slice(currentPage * pageSize, (currentPage + 1) * pageSize))

  // Only rows the server could actually accept are selectable: a pending audit id, a policy
  // version, and an action. A row without them is still shown and still reviewable one at a
  // time — hiding it would make the queue disagree with the estate counts above it.
  const approvable = (row) => Boolean(row.audit_id && row.policy_version != null && row.action)

  const inspect = (row) => {
    setReviewed((seen) => new Set(seen).add(row.file))
    // Detail and history together: the panel is specified to show BOTH what a rule decided and
    // what happened before it, and a reviewer opening a file wants one answer, not two loads.
    // A history that fails to load must not blank the evidence beside it, so it degrades to an
    // empty timeline the panel can say it could not read.
    return Promise.all([
      getLifecycleFileDetail(scanId, row.file),
      getLifecycleFileHistory(scanId, row.file).then((h) => h.events || []).catch(() => null),
    ]).then(([detail, events]) => setSelected({ ...detail, history: events }))
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

    <div style={{ display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap', marginBottom: 12 }}>
      <label style={{ fontSize: 13 }}>Search<br />
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder="File, rule, reason, or owner" aria-label="Search disposition review queue" />
      </label>
      <label style={{ fontSize: 13 }}>Owner<br />
        <select value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">All owners</option>
          {owners.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
      <label style={{ fontSize: 13 }}>File type<br />
        <select value={fileType} onChange={(e) => setFileType(e.target.value)}>
          <option value="">All file types</option>
          {fileTypes.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>
      <label style={{ fontSize: 13 }}>Age<br />
        <select value={minAge} onChange={(e) => setMinAge(e.target.value)}>
          {AGES.map(([v, label]) => <option key={v || 'any'} value={v}>{label}</option>)}
        </select>
      </label>
      <label style={{ fontSize: 13 }}>Department<br />
        {/* PRD §6.2: a signal that needs connector work is labelled UNAVAILABLE, never rendered
            as an empty filter that appears to work and silently matches nothing. Department is
            not collected by the Drive/SharePoint scan today (api/documents.py, ADR 0003's own
            Costs/risks), so the control says so rather than pretending. */}
        <select disabled aria-describedby="dept-unavailable">
          <option>Unavailable until connected</option>
        </select>
      </label>
      <label style={{ fontSize: 13 }}>Action<br />
        <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}
                aria-label="Filter disposition queue by action">
          <option value="">All actions</option>
          <option value="archive">Archive</option>
          <option value="delete">Deletion</option>
        </select>
      </label>
      <label style={{ fontSize: 13 }}>Rows per page<br />
        <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}
                aria-label="Disposition files per page">
          {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
        </select>
      </label>
      {(search || owner || actionFilter || fileType || minAge) && <button type="button" className="ghost"
        onClick={() => {
          setSearch(''); setOwner(''); setActionFilter(''); setFileType(''); setMinAge('')
        }}>Clear filters</button>}
    </div>
    <p id="dept-unavailable" className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
      Department is not collected by the Drive or SharePoint scan yet, so it cannot be filtered
      on. Source is not offered here because every file in this queue came from one scan, and a
      scan has a single source.
    </p>

    <p className="muted" style={{ fontSize: 12.5 }}>
      {filteredRows.length.toLocaleString()} of {rows.length.toLocaleString()} files match.
      {' '}Showing {filteredRows.length ? currentPage * pageSize + 1 : 0}–{Math.min((currentPage + 1) * pageSize, filteredRows.length)}.
    </p>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
      <div className="panel" style={{ maxHeight: 520, overflow: 'auto' }}>
        {visibleGroups.length === 0 && <p>{
          // Three different zero states, and only the last is about the rules. #1175's message
          // ("the enabled rules ran and matched no files") became untrue the moment a client-side
          // filter could empty the list on its own: the rules DID match, and the filter hid the
          // result. Attributing a filter's effect to the rules is the §6.4 mistake one level up -
          // a zero that names the wrong cause sends someone to edit a policy that is working.
          rows.length > 0
            ? 'No files match these filters. ' + rows.length.toLocaleString()
              + ' file(s) are in this queue before filtering.'
            : candidateOnly
              ? 'No lifecycle candidates need review. The enabled rules ran and matched no files.'
              : 'No files match this view.'}</p>}
        {visibleGroups.map((group) => {
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
        {filteredRows.length > pageSize && <nav aria-label="Disposition review pages"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <button type="button" className="ghost" disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}>Previous page</button>
          <span style={{ fontSize: 12.5 }}>Page {currentPage + 1} of {lastPage + 1}</span>
          <button type="button" className="ghost" disabled={currentPage === lastPage}
                  onClick={() => setPage(currentPage + 1)}>Next page</button>
        </nav>}
      </div>
      <div>
        <LifecycleEvidencePanel file={selected} />
        {picked.size > 0 && activeGroup && <div className="panel">
          <h3 style={{ fontSize: 13 }}>Approve {picked.size.toLocaleString()} file{picked.size === 1 ? '' : 's'}</h3>
          <p className="muted" style={{ fontSize: 12 }}>
            {activeGroup.rule} · version {String(activeGroup.policyVersion)} · {activeGroup.action}.
            {' '}This records the decision. No source file is moved or deleted here.
          </p>
          {/* PRD §3/§8, "Recoverability is visible". Two different statements, and conflating
              them is what makes either one a lie: what the action MEANS at the source, and what
              actually happens when this button is pressed. recoveryPolicy holds the first; the
              second is record-only for every candidate in this queue (#1182). No Undo control is
              offered because canUndo() is false for every case ACP can produce today — the
              before-state of a move or rename is discarded rather than recorded. */}
          <p className="muted" style={{ fontSize: 12 }}>
            <b>Recovery:</b> {recoveryLine(recoveryFor({ action: activeGroup.action, source }))}
          </p>
          {canUndo(recoveryFor({ action: activeGroup.action, source })) && <p role="status">
            This action can be undone from ACP.
          </p>}
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
