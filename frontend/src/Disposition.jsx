import { useState, useEffect, useCallback } from 'react'
import {
  listDispositionPolicies, createDispositionPolicy, setDispositionPolicyEnabled,
  previewDispositionPolicy, executeDispositionPolicy,
  listDispositionApprovals, approveDisposition, rejectDisposition, listDispositionAudit,
} from './api.js'

// ADR 0003 Phase 3 — disposition policies + the approval queue. A policy is a
// match predicate over the long-lived documents table plus an action. Safety
// posture mirrors the backend: created disabled, approval-gated by default,
// and "delete" is always Drive trash (recoverable), never permanent.
const FIELDS = ['department', 'business_criticality', 'regulatory_tags', 'triage_score', 'source', 'owner', 'age_days']
const OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains']
const ACTIONS = [
  ['leave', 'Leave in place', 'Record the decision only — never touches the file.'],
  ['archive', 'Move to “ACP Archive”', 'Moves the Drive file into an ACP Archive folder.'],
  ['rename', 'Rename with a marker', 'Renames the Drive file, default "{name} [ARCHIVED {date}]".'],
  ['move', 'Move to a folder', 'Moves the Drive file to the folder in the action config.'],
  ['delete', 'Move to Drive trash', 'Always the trash — recoverable for 30 days, never a permanent delete.'],
]
const OP_LABEL = { eq: '=', ne: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤', contains: 'contains' }

const inp = { padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 6, background: 'var(--surface)', color: 'inherit', fontSize: 13 }

function actionBadge(action) {
  const tone = action === 'delete' ? ['#FBE9E9', '#E5C4C4', '#A32D2D']
    : action === 'leave' ? ['#EAF3EC', '#CFE5D6', '#2F6B43'] : ['#EEF2FB', '#D3DDF1', '#2B4A7E']
  return (
    <span style={{ fontSize: 11.5, fontWeight: 600, padding: '2px 9px', borderRadius: 20,
                   background: tone[0], border: `1px solid ${tone[1]}`, color: tone[2] }}>
      {action}{action === 'delete' ? ' (trash)' : ''}
    </span>
  )
}

function CreatePolicy({ onCreated }) {
  const [name, setName] = useState('')
  const [field, setField] = useState('age_days')
  const [op, setOp] = useState('gt')
  const [value, setValue] = useState('')
  const [action, setAction] = useState('leave')
  const [approval, setApproval] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const numeric = field === 'triage_score' || field === 'age_days'
  const create = () => {
    setBusy(true); setErr('')
    const v = numeric ? Number(value) : value
    createDispositionPolicy(name.trim(), [{ field, op, value: v }], action, {}, approval)
      .then(() => { setName(''); setValue(''); onCreated() })
      .catch((e) => setErr(e.message || 'create failed'))
      .finally(() => setBusy(false))
  }
  const valid = name.trim() && value !== '' && (!numeric || !Number.isNaN(Number(value)))
  return (
    <div style={{ marginTop: 18, padding: '14px', border: '1px solid var(--line)', borderRadius: 10, background: 'var(--surface)' }}>
      <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 10 }}>New policy</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Policy name" aria-label="Policy name" style={{ ...inp, flex: '1 1 180px' }} />
        <span className="muted" style={{ fontSize: 12.5 }}>when</span>
        <select value={field} onChange={(e) => setField(e.target.value)} aria-label="Match field" style={inp}>
          {FIELDS.map((f) => <option key={f} value={f}>{f.replaceAll('_', ' ')}</option>)}
        </select>
        <select value={op} onChange={(e) => setOp(e.target.value)} aria-label="Match operator" style={inp}>
          {OPS.map((o) => <option key={o} value={o}>{OP_LABEL[o]}</option>)}
        </select>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={numeric ? 'e.g. 1095' : 'value'}
               aria-label="Match value" inputMode={numeric ? 'numeric' : 'text'} style={{ ...inp, width: 110 }} />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', marginTop: 10 }}>
        <label style={{ fontSize: 13 }}>then
          <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action" style={{ ...inp, marginLeft: 6 }}>
            {ACTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, cursor: 'pointer' }}>
          <input type="checkbox" checked={approval} onChange={() => setApproval(!approval)} />
          require approval per file
        </label>
        <button onClick={create} disabled={busy || !valid}>{busy ? 'Creating…' : '+ Create (disabled)'}</button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        {ACTIONS.find(([v]) => v === action)?.[2]} Policies start <b>disabled</b> — enable explicitly before executing.
      </div>
      {err && <p style={{ fontSize: 13, color: '#A32D2D', marginBottom: 0 }}>⚠ {err}</p>}
    </div>
  )
}

function PolicyRow({ p, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)     // {tone:'ok'|'err', text}
  const [preview, setPreview] = useState(null)
  let match = []
  try { match = JSON.parse(p.match || '[]') } catch { /* legacy row */ }
  const rule = match.map((c) => `${String(c.field).replaceAll('_', ' ')} ${OP_LABEL[c.op] || c.op} ${c.value}`).join(' AND ')
  const act = (fn, label) => {
    setBusy(true); setMsg(null)
    fn().then((r) => {
      if (label === 'preview') { setPreview(r); return }
      if (label === 'execute') {
        setMsg({ tone: 'ok', text: `matched ${r.matched} — ${r.pending_approval} queued for approval, ${r.applied} applied, ${r.skipped} already decided, ${r.failed} failed` })
      }
      onChanged()
    }).catch((e) => setMsg({ tone: 'err', text: e.message || `${label} failed` }))
      .finally(() => setBusy(false))
  }
  return (
    <div style={{ padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 9, background: 'var(--surface)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <b style={{ fontSize: 13.5 }}>{p.name}</b>
        {actionBadge(p.action)}
        {p.requires_approval ? <span className="muted" style={{ fontSize: 11.5 }}>🔎 approval-gated</span>
          : <span style={{ fontSize: 11.5, color: '#854F0B' }}>⚡ immediate</span>}
        <span style={{ flex: 1 }} />
        <label style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: 12.5, cursor: 'pointer' }}>
          <input type="checkbox" checked={!!p.enabled} disabled={busy}
                 onChange={() => act(() => setDispositionPolicyEnabled(p.policy_id, !p.enabled), 'toggle')} />
          enabled
        </label>
        <button className="ghost small" disabled={busy} onClick={() => act(() => previewDispositionPolicy(p.policy_id), 'preview')}>Preview</button>
        <button className="ghost small" disabled={busy || !p.enabled} title={p.enabled ? undefined : 'Enable the policy first'}
                onClick={() => act(() => executeDispositionPolicy(p.policy_id), 'execute')}>Execute</button>
      </div>
      <div className="muted" style={{ fontSize: 12.5, marginTop: 5 }}>when {rule || '—'}</div>
      {preview && (
        <div style={{ fontSize: 12.5, marginTop: 7, padding: '8px 10px', borderRadius: 8, background: '#EEF2FB', border: '1px solid #D3DDF1' }}>
          <b>Dry run:</b> would select {preview.would_match} document(s){preview.would_match > 0 && <> — {preview.documents.slice(0, 5).map((d) => d.path).join(' · ')}{preview.would_match > 5 ? ' · …' : ''}</>}
          <button className="ghost small" style={{ marginLeft: 8 }} onClick={() => setPreview(null)}>dismiss</button>
        </div>
      )}
      {msg && <div role="status" style={{ fontSize: 12.5, marginTop: 6, color: msg.tone === 'ok' ? '#3B6D11' : '#A32D2D' }}>{msg.tone === 'ok' ? '✓ ' : '⚠ '}{msg.text}</div>}
    </div>
  )
}

const RESULT_TONE = {
  applied: ['#EAF3EC', '#CFE5D6', '#2F6B43'],
  pending_approval: ['#FBF1DF', '#EAD9BF', '#854F0B'],
  rejected: ['#EEEDEA', '#DDD9D2', '#5F5E5A'],
  failed: ['#FBE9E9', '#E5C4C4', '#A32D2D'],
}

// The visible face of the append-only disposition_audit table — every outcome,
// newest first, so an admin can answer "what has this feature actually done?"
// without going to the database.
function History() {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState('')
  const load = () => listDispositionAudit(100).then(setRows).catch((e) => setErr(e.message || 'could not load history'))
  return (
    <details style={{ marginTop: 20 }} onToggle={(e) => { if (e.target.open) load() }}>
      <summary style={{ cursor: 'pointer', fontWeight: 700, fontSize: 14 }}>
        History <span className="muted" style={{ fontWeight: 400, fontSize: 12.5 }}>· every recorded outcome, newest first</span>
      </summary>
      {err && <p style={{ fontSize: 13, color: '#A32D2D' }}>⚠ {err}</p>}
      {rows === null && !err && <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Loading…</p>}
      {rows !== null && rows.length === 0 && <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>No dispositions recorded yet.</p>}
      {rows !== null && rows.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 10 }}>
          {rows.map((r) => {
            const tone = RESULT_TONE[r.result] || RESULT_TONE.rejected
            return (
              <div key={r.id} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'baseline', padding: '5px 8px', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                <span className="muted" style={{ flex: '0 0 118px', fontSize: 11.5 }}>{(r.ts || '').slice(0, 16).replace('T', ' ')}</span>
                <span style={{ fontSize: 11, fontWeight: 600, padding: '1px 8px', borderRadius: 20,
                               background: tone[0], border: `1px solid ${tone[1]}`, color: tone[2] }}>
                  {(r.result || '').replace('_', ' ')}
                </span>
                {actionBadge(r.action)}
                <b style={{ wordBreak: 'break-all' }}>{r.doc_id}</b>
                <span className="muted" style={{ flexBasis: '100%', fontSize: 11.5, paddingLeft: 126 }}>{r.detail}</span>
              </div>
            )
          })}
        </div>
      )}
    </details>
  )
}

function ApprovalQueue({ items, onDecided }) {
  const [busyId, setBusyId] = useState(null)
  const [err, setErr] = useState('')
  const decide = (id, fn) => {
    setBusyId(id); setErr('')
    fn(id).then(onDecided).catch((e) => setErr(e.message || 'action failed')).finally(() => setBusyId(null))
  }
  if (!items.length) {
    return <p className="muted" style={{ fontSize: 13 }}>Nothing awaiting approval — run an approval-gated policy to queue proposals here.</p>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      {err && <p style={{ fontSize: 13, color: '#A32D2D', margin: 0 }}>⚠ {err}</p>}
      {items.map((a) => (
        <div key={a.id} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', padding: '8px 11px', border: '1px solid var(--line)', borderRadius: 9, background: 'var(--surface)' }}>
          {actionBadge(a.action)}
          <span style={{ fontSize: 13, flex: 1, minWidth: 200 }}>
            <b style={{ wordBreak: 'break-all' }}>{a.doc_id}</b>
            <span className="muted" style={{ display: 'block', fontSize: 12 }}>{a.detail}</span>
          </span>
          <button className="ghost small" disabled={busyId === a.id} onClick={() => decide(a.id, approveDisposition)}>✓ Approve</button>
          <button className="ghost small" disabled={busyId === a.id} onClick={() => decide(a.id, rejectDisposition)}>✕ Reject</button>
        </div>
      ))}
    </div>
  )
}

export default function Disposition() {
  const [policies, setPolicies] = useState(null)
  const [approvals, setApprovals] = useState([])
  const [loadErr, setLoadErr] = useState('')
  const refresh = useCallback(() => {
    listDispositionPolicies().then(setPolicies).catch((e) => setLoadErr(e.message || 'could not load policies'))
    listDispositionApprovals().then(setApprovals).catch(() => {})
  }, [])
  useEffect(() => { refresh() }, [refresh])
  return (
    <div style={{ maxWidth: 720 }}>
      <h3 style={{ marginTop: 0 }}>Disposition policies</h3>
      <p className="muted" style={{ fontSize: 13 }}>
        Rules that decide what happens to documents at the end of their life — leave, archive,
        rename, move, or trash (ADR 0003). By default every match waits in the approval queue
        below before anything touches a file, and <b>delete only ever moves a Drive file to the
        trash</b> — it's recoverable, never permanent.
      </p>
      {loadErr && <p style={{ fontSize: 13, color: '#A32D2D' }}>⚠ {loadErr}</p>}
      {policies === null && !loadErr && <p className="muted">Loading…</p>}
      {policies !== null && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {policies.length === 0 && (
            <div className="muted" style={{ fontSize: 13, padding: 14, textAlign: 'center', border: '1px dashed var(--line)', borderRadius: 8 }}>
              No policies yet — create one below. It starts disabled.
            </div>
          )}
          {policies.map((p) => <PolicyRow key={p.policy_id} p={p} onChanged={refresh} />)}
        </div>
      )}
      <CreatePolicy onCreated={refresh} />
      <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--line)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Approval queue</h3>
          <span className="muted" style={{ fontSize: 13 }}>{approvals.length} pending</span>
          <button className="ghost small" onClick={refresh}>↻ Refresh</button>
        </div>
        <ApprovalQueue items={approvals} onDecided={refresh} />
        <History />
      </div>
    </div>
  )
}
