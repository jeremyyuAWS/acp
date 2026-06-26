import { useState, useRef, useEffect } from 'react'
import { resetDemoData, getAllowlist, setAllowlist } from './api.js'

// Danger zone — wipe scan results (Grafana + in-app charts) and/or Langfuse
// traces so the dashboards start fresh. Settings are preserved. Typed-confirm.
function ResetData() {
  const [scope, setScope] = useState('all')
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState('')
  const SCOPES = [
    ['all', 'Both', 'Clear scan results and delete Langfuse traces — full clean slate.'],
    ['grafana', 'Grafana / charts only', 'Clear the scan-results tables. Langfuse traces are kept.'],
    ['langfuse', 'Langfuse only', 'Delete the project’s traces. Scan history & charts are kept.'],
  ]
  const run = () => {
    setBusy(true); setErr(''); setResult(null)
    resetDemoData(scope)
      .then((d) => { setResult(d); setTyped('') })
      .catch((e) => setErr(e.message || 'reset failed'))
      .finally(() => setBusy(false))
  }
  return (
    <div style={{ maxWidth: 560 }}>
      <h3 style={{ marginTop: 0 }}>Reset demo data</h3>
      <p className="muted" style={{ fontSize: 13 }}>
        Wipes scan results so Grafana, Langfuse, and the in-app charts start fresh.
        <strong> Your settings are preserved</strong> — worker count, AI mode, schedule, rubric.
        This cannot be undone.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '14px 0' }}>
        {SCOPES.map(([v, label, desc]) => (
          <label key={v} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
            <input type="radio" name="rscope" checked={scope === v} onChange={() => setScope(v)} style={{ marginTop: 3 }} />
            <span><b>{label}</b><br /><span className="muted" style={{ fontSize: 12 }}>{desc}</span></span>
          </label>
        ))}
      </div>
      <label style={{ fontSize: 13 }}>Type <code>RESET</code> to confirm:
        <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="RESET"
               style={{ marginLeft: 8, padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 6 }} />
      </label>
      <div style={{ marginTop: 14 }}>
        <button onClick={run} disabled={busy || typed !== 'RESET'}
                style={{ background: typed === 'RESET' ? '#A32D2D' : '#ccc', color: '#fff', border: 'none',
                         borderRadius: 8, padding: '8px 16px', cursor: typed === 'RESET' ? 'pointer' : 'not-allowed', fontWeight: 600 }}>
          {busy ? 'Resetting…' : 'Reset data'}
        </button>
      </div>
      {result && (
        <p style={{ marginTop: 12, fontSize: 13, color: '#3B6D11' }}>
          ✓ Reset done — cleared {result.cleared_tables?.length || 0} table(s)
          {result.scope !== 'grafana' && `, deleted ${result.langfuse_traces_deleted} Langfuse trace(s)`}.
          {result.scope !== 'grafana' && result.langfuse_traces_deleted === 0 &&
            ' (No traces deleted — if Langfuse still shows data, clear it from its UI / retention settings.)'}
        </p>
      )}
      {err && <p style={{ marginTop: 12, fontSize: 13, color: '#A32D2D' }}>⚠ {err}</p>}
    </div>
  )
}
import Rubric from './Rubric.jsx'
import WcagCoverage from './WcagCoverage.jsx'
import Ontology from './Ontology.jsx'
import OwnerDelegate from './OwnerDelegate.jsx'
import FileTypeConfig from './FileTypeConfig.jsx'
import RolePrivilege from './RolePrivilege.jsx'
import UserManagement from './UserManagement.jsx'
import { useDialog } from './a11y.js'
import { downloadUpdatedXlsx, downloadUpdatedPptx } from './exportDeliverables.js'

// Platform settings, behind the header cog — gated to the Platform Admin. Holds
// the scoring rules (Rubric), the validation coverage (WCAG 2.1 + 2.2 matrix), and
// the business ontology/taxonomy — i.e. the configuration an admin owns, kept out
// of the day-to-day workflow tabs.
function AllowList() {
  const [emails, setEmails] = useState([])
  const [baseline, setBaseline] = useState([])
  const [domains, setDomains] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getAllowlist()
      .then((d) => { setEmails(d.emails || []); setBaseline(d.baseline_emails || []); setDomains(d.domains || []) })
      .catch(() => setMsg('Could not load the allow-list.'))
      .finally(() => setLoaded(true))
  }, [])

  const add = () => {
    const e = input.trim().toLowerCase()
    if (!e.includes('@')) { setMsg('Enter a valid email.'); return }
    if (emails.includes(e) || baseline.includes(e)) { setMsg('Already allowed.'); setInput(''); return }
    setEmails((s) => [...s, e].sort()); setInput(''); setMsg('')
  }
  const remove = (e) => setEmails((s) => s.filter((x) => x !== e))
  const save = () => {
    setBusy(true); setMsg('')
    setAllowlist(emails)
      .then((d) => { setEmails(d.emails || []); setMsg('✓ Saved — applies on each user’s next sign-in.') })
      .catch((err) => setMsg(`Could not save: ${err.message || err}`))
      .finally(() => setBusy(false))
  }

  return (
    <section style={{ maxWidth: 560 }}>
      <h3 style={{ marginTop: 0 }}>Who can use the app</h3>
      <p className="muted" style={{ fontSize: 13, marginTop: 4, lineHeight: 1.5 }}>
        Google emails allowed to sign in and scan. Changes take effect on the user’s next
        sign-in. (Each user must also be a Google OAuth <b>test user</b> until the app is verified.)
      </p>

      <div style={{ display: 'flex', gap: 8, margin: '12px 0' }}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && add()}
               placeholder="name@example.com" aria-label="Email to allow"
               style={{ flex: 1, padding: '7px 10px', borderRadius: 7, border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit' }} />
        <button className="ghost" onClick={add}>Add</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
        {loaded && emails.length === 0 && <span className="muted" style={{ fontSize: 13 }}>No additional emails yet.</span>}
        {emails.map((e) => (
          <div key={e} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                padding: '6px 10px', borderRadius: 7, background: '#F1EFF3', border: '1px solid var(--line)' }}>
            <span style={{ fontSize: 13 }}>{e}</span>
            <button className="ghost small" onClick={() => remove(e)} aria-label={`Remove ${e}`}>✕</button>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save allow-list'}</button>
        {msg && <span className="muted" role="status" aria-live="polite" style={{ fontSize: 13 }}>{msg}</span>}
      </div>

      {(baseline.length > 0 || domains.length > 0) && (
        <p className="muted" style={{ fontSize: 12, marginTop: 16, lineHeight: 1.5 }}>
          Always allowed (from deploy config, not editable here): {baseline.join(', ') || '—'}
          {domains.length > 0 && <> · anyone @{domains.join(', @')}</>}
        </p>
      )}
    </section>
  )
}

export default function Settings({ onClose, onRubricSaved, files = [], onOntologyChange, onDelegationChange, onFileTypeChange, onPrivilegeChange }) {
  const [tab, setTab] = useState('rules')
  const [dl, setDl] = useState(null) // 'xlsx' | 'pptx' while a deliverable is generating
  const panelRef = useRef(null)
  useDialog(panelRef, onClose)
  const grab = async (kind, fn) => { if (dl) return; setDl(kind); try { await fn() } catch (e) { console.error('deliverable export failed', e) } finally { setDl(null) } }
  return (
    <div className="setoverlay" role="dialog" aria-modal="true" aria-label="Platform settings" onClick={onClose}>
      <div className="setpanel" ref={panelRef} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="sethead">
          <div><b>⚙ Platform settings</b><span className="muted"> · admin · rules &amp; validation</span></div>
          <button className="ghost small" aria-label="Close settings" onClick={onClose}>✕</button>
        </div>
        <div className="setexports">
          <span className="setexporthint">Updated deliverables — original format, with a live <b>Status</b> column reflecting what the platform ships today:</span>
          <div className="setexportbtns">
            <button className="dlbtn" disabled={!!dl} onClick={() => grab('xlsx', downloadUpdatedXlsx)}>{dl === 'xlsx' ? 'Preparing…' : '⤓ Coverage matrix · Excel'}</button>
            <button className="dlbtn" disabled={!!dl} onClick={() => grab('pptx', downloadUpdatedPptx)}>{dl === 'pptx' ? 'Preparing…' : '⤓ Method deck · PPT'}</button>
          </div>
        </div>
        <div className="subtabs" role="tablist" aria-label="Settings sections">
          <button role="tab" aria-selected={tab === 'rules'} className={tab === 'rules' ? 'fchip on' : 'fchip'} onClick={() => setTab('rules')}>Scoring rules</button>
          <button role="tab" aria-selected={tab === 'validation'} className={tab === 'validation' ? 'fchip on' : 'fchip'} onClick={() => setTab('validation')}>Validation coverage</button>
          <button role="tab" aria-selected={tab === 'ontology'} className={tab === 'ontology' ? 'fchip on' : 'fchip'} onClick={() => setTab('ontology')}>Business ontology</button>
          <button role="tab" aria-selected={tab === 'filetypes'} className={tab === 'filetypes' ? 'fchip on' : 'fchip'} onClick={() => setTab('filetypes')}>File types</button>
          <button role="tab" aria-selected={tab === 'owners'} className={tab === 'owners' ? 'fchip on' : 'fchip'} onClick={() => setTab('owners')}>Owners</button>
          <button role="tab" aria-selected={tab === 'permissions'} className={tab === 'permissions' ? 'fchip on' : 'fchip'} onClick={() => setTab('permissions')}>Permissions</button>
          <button role="tab" aria-selected={tab === 'users'} className={tab === 'users' ? 'fchip on' : 'fchip'} onClick={() => setTab('users')}>Users</button>
          <button role="tab" aria-selected={tab === 'access'} className={tab === 'access' ? 'fchip on' : 'fchip'} onClick={() => setTab('access')}>Access</button>
          <button role="tab" aria-selected={tab === 'data'} className={tab === 'data' ? 'fchip on' : 'fchip'} onClick={() => setTab('data')}>Data</button>
        </div>
        <div className="setbody">
          {tab === 'rules' && <Rubric onSaved={onRubricSaved} />}
          {tab === 'validation' && <WcagCoverage />}
          {tab === 'ontology' && <Ontology files={files} onPublished={onOntologyChange} />}
          {tab === 'filetypes' && <FileTypeConfig onChanged={(cfg, custom) => onFileTypeChange?.(cfg, custom)} />}
          {tab === 'owners' && <OwnerDelegate files={files} onChanged={onDelegationChange} />}
          {tab === 'permissions' && <RolePrivilege onChanged={onPrivilegeChange} />}
          {tab === 'users' && <UserManagement />}
          {tab === 'access' && <AllowList />}
          {tab === 'data' && <ResetData />}
        </div>
      </div>
    </div>
  )
}
