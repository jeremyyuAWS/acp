import { useState, useEffect, useCallback } from 'react'
import {
  listDispositionPolicies, createDispositionPolicy, setDispositionPolicyEnabled, previewDispositionPolicy,
} from './api.js'

// Deva's Discover ask #3 — create archival/deletion rules during Discover.
//
// The backend rule engine (api/disposition.py + _evaluate_discover_lifecycle_rules) already runs
// these AT DISCOVERY TIME: a matched archive rule marks a file "Archive Candidate", a delete rule
// "Delete Candidate", and Assess then excludes those by default (the exclusion the scope funnel now
// shows). What was missing was any MOUNTED UI to CREATE such a rule — the one editor that existed was
// orphaned and could not even express folder-path or modified-before-date conditions. This is that UI,
// focused on the two lifecycle actions Deva asked for and wired to the conditions the backend supports.
//
// SAFETY mirrors the backend exactly: a rule is created DISABLED and approval-gated, and "delete" is
// always Drive TRASH (recoverable), never a permanent delete. Nothing here touches a file — enabling
// and executing a rule stays a separate, later, approval-gated step. Creating a rule needs admin; a
// non-admin's create is refused server-side and the message is surfaced inline.

// A condition template maps a plain-language choice to the real (field, op) the backend validates, so
// the operator never has to learn the field/op vocabulary. `kind` drives the value input + coercion.
const CONDITIONS = [
  { key: 'folder', label: 'Folder path starts with', field: 'parent_folder', op: 'prefix', kind: 'text', placeholder: 'e.g. Archive/ or Finance/2019/' },
  { key: 'pathhas', label: 'File path contains', field: 'path', op: 'contains', kind: 'text', placeholder: 'e.g. _OLD or /Superseded/' },
  { key: 'notmod', label: 'Not modified in the last N days', field: 'modified_age_days', op: 'gt', kind: 'number', placeholder: 'e.g. 1095' },
  { key: 'modbefore', label: 'Last modified before', field: 'modified_at', op: 'before', kind: 'date', placeholder: '' },
  { key: 'createdbefore', label: 'Created before', field: 'created_at', op: 'before', kind: 'date', placeholder: '' },
  { key: 'age', label: 'Older than N days (discovered age)', field: 'age_days', op: 'gt', kind: 'number', placeholder: 'e.g. 1825' },
]
const COND_BY_FIELD_OP = new Map(CONDITIONS.map((c) => [`${c.field}:${c.op}`, c]))
const ACTIONS = [
  ['archive', 'Archive', 'Moves the matched file into an ACP Archive folder.'],
  ['delete', 'Delete (Drive trash)', 'Moves the matched file to Drive trash — recoverable for 30 days, never a permanent delete.'],
]
const LIFECYCLE = new Set(['archive', 'delete'])

const inp = { padding: '5px 8px', border: '1px solid var(--line)', borderRadius: 6, background: 'var(--surface)', color: 'inherit', fontSize: 13 }

function actionBadge(action) {
  const tone = action === 'delete' ? ['#FBE9E9', '#E5C4C4', '#A32D2D'] : ['#EEF2FB', '#D3DDF1', '#2B4A7E']
  return (
    <span style={{ fontSize: 11.5, fontWeight: 600, padding: '2px 9px', borderRadius: 20,
                   background: tone[0], border: `1px solid ${tone[1]}`, color: tone[2] }}>
      {action === 'delete' ? 'delete (trash)' : 'archive'}
    </span>
  )
}

/** Human-readable one-liner for a stored match predicate, using the template label when the
 *  (field, op) matches one we offer, and a plain fallback otherwise. */
function ruleText(match) {
  return (match || []).map((c) => {
    const t = COND_BY_FIELD_OP.get(`${c.field}:${c.op}`)
    return t ? `${t.label} ${c.value}` : `${String(c.field).replaceAll('_', ' ')} ${c.op} ${c.value}`
  }).join(' AND ')
}

function CreateRule({ onCreated }) {
  const [name, setName] = useState('')
  const [condKey, setCondKey] = useState(CONDITIONS[0].key)
  const [value, setValue] = useState('')
  const [action, setAction] = useState('archive')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const cond = CONDITIONS.find((c) => c.key === condKey) || CONDITIONS[0]
  const numeric = cond.kind === 'number'
  const valid = name.trim() && value !== '' && (!numeric || !Number.isNaN(Number(value)))

  const create = () => {
    setBusy(true); setErr('')
    const v = numeric ? Number(value) : value
    createDispositionPolicy(name.trim(), [{ field: cond.field, op: cond.op, value: v }], action)
      .then(() => { setName(''); setValue(''); onCreated() })
      .catch((e) => setErr(e.message || 'create failed'))
      .finally(() => setBusy(false))
  }

  return (
    <div style={{ padding: 14, border: '1px solid var(--line)', borderRadius: 10, background: 'var(--surface)' }}>
      <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 10 }}>New archival / deletion rule</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Rule name" aria-label="Rule name" style={{ ...inp, flex: '1 1 180px' }} />
        <span className="muted" style={{ fontSize: 12.5 }}>when</span>
        <select value={condKey} onChange={(e) => { setCondKey(e.target.value); setValue('') }} aria-label="Condition" style={inp}>
          {CONDITIONS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={cond.placeholder}
               aria-label="Condition value" type={cond.kind === 'date' ? 'date' : 'text'}
               inputMode={numeric ? 'numeric' : undefined} style={{ ...inp, width: cond.kind === 'text' ? 220 : 150 }} />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', marginTop: 10 }}>
        <label style={{ fontSize: 13 }}>then
          <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action" style={{ ...inp, marginLeft: 6 }}>
            {ACTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <button onClick={create} disabled={busy || !valid}>{busy ? 'Creating…' : '+ Create (disabled)'}</button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        {ACTIONS.find(([v]) => v === action)?.[2]} Rules start <b>disabled</b> and approval-gated — matched files are
        marked as candidates during discovery and excluded from Assess; nothing is moved or deleted until you enable and approve it.
      </div>
      {err && <p style={{ fontSize: 13, color: '#A32D2D', margin: '8px 0 0' }} role="alert">⚠ {err}</p>}
    </div>
  )
}

function RuleRow({ p, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState(null)
  const [err, setErr] = useState('')
  let match = []
  try { match = JSON.parse(p.match || '[]') } catch { /* legacy row */ }
  const enabled = !!p.enabled

  const toggle = () => {
    setBusy(true); setErr('')
    Promise.resolve(setDispositionPolicyEnabled(p.policy_id, !enabled))
      .then(() => onChanged()).catch((e) => setErr(e.message || 'update failed')).finally(() => setBusy(false))
  }
  const runPreview = () => {
    setBusy(true); setErr('')
    Promise.resolve(previewDispositionPolicy(p.policy_id))
      .then((r) => setPreview(r?.would_match ?? 0)).catch((e) => setErr(e.message || 'preview failed')).finally(() => setBusy(false))
  }

  return (
    <div className="disprule-row" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '9px 0', borderTop: '1px solid var(--line)' }}>
      <div style={{ minWidth: 0, flex: '1 1 240px' }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{p.name} {actionBadge(p.action)}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{ruleText(match) || '—'}</div>
        {preview != null && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>Would match <b>{preview.toLocaleString()}</b> discovered file{preview === 1 ? '' : 's'}</div>}
        {err && <div style={{ fontSize: 12, color: '#A32D2D', marginTop: 2 }} role="alert">⚠ {err}</div>}
      </div>
      <button className="ghost small" onClick={runPreview} disabled={busy}>Preview matches</button>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12.5, cursor: 'pointer' }}>
        <input type="checkbox" checked={enabled} onChange={toggle} disabled={busy} aria-label={`Enable ${p.name}`} />
        {enabled ? 'Enabled' : 'Disabled'}
      </label>
    </div>
  )
}

export default function DispositionRules() {
  const [open, setOpen] = useState(false)
  const [rules, setRules] = useState(null)   // null = not loaded yet
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    Promise.resolve(listDispositionPolicies())
      .then((rows) => setRules((Array.isArray(rows) ? rows : []).filter((p) => LIFECYCLE.has(p.action))))
      .catch((e) => setErr(e.message || 'could not load rules'))
  }, [])
  useEffect(() => { if (open && rules == null) load() }, [open, rules, load])

  return (
    <section className="disprules" style={{ marginTop: 12, border: '1px solid var(--line)', borderRadius: 10, padding: '10px 14px' }}>
      <button className="linklike" onClick={() => setOpen((o) => !o)} aria-expanded={open}
              style={{ fontWeight: 700, fontSize: 13.5, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span> Archival &amp; deletion rules
      </button>
      <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
        Define what happens to documents at the end of their life — archive or trash — by folder, age or last-modified date.
        Rules run during discovery and mark matched files as candidates; Assess excludes them by default.
      </div>

      {open && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <CreateRule onCreated={load} />
          <div>
            <div className="muted" style={{ fontSize: 11.5, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 2 }}>Existing rules</div>
            {err && <p style={{ fontSize: 13, color: '#A32D2D' }} role="alert">⚠ {err}</p>}
            {rules == null ? (
              <p className="muted" style={{ fontSize: 12.5 }}>Loading…</p>
            ) : rules.length === 0 ? (
              <p className="muted" style={{ fontSize: 12.5 }}>No archival or deletion rules yet.</p>
            ) : (
              rules.map((p) => <RuleRow key={p.policy_id} p={p} onChanged={load} />)
            )}
          </div>
        </div>
      )}
    </section>
  )
}
