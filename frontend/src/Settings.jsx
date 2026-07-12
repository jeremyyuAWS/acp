import { useState, useRef, useEffect } from 'react'
import { resetDemoData, getAllowlist, setAllowlist, getSettings, updateSettings, getAiCosts, getAiProviders, putAiProvider } from './api.js'

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

// ADR 0010: Blob is always the primary, must-succeed write for a remediated file.
// This controls whether it's ALSO auto-mirrored to Drive right after, and which
// Drive folder that mirror lands in.
function DriveMirror() {
  const [settings, setSettings] = useState(null)
  const [folder, setFolder] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    getSettings().then((s) => { setSettings(s); setFolder(s.drive_mirror_folder || 'Remediated') }).catch(() => {})
  }, [])
  const toggle = () => {
    if (!settings || busy) return
    setBusy(true); setMsg('')
    updateSettings({ drive_mirror_enabled: !settings.drive_mirror_enabled })
      .then(setSettings)
      .catch((e) => setMsg(e.message || 'update failed'))
      .finally(() => setBusy(false))
  }
  const [aiUrl, setAiUrl] = useState('')
  const [aiVision, setAiVision] = useState('')
  useEffect(() => { if (settings) { setAiUrl(settings.ai_base_url || ''); setAiVision(settings.ai_vision_model || '') } }, [settings])
  const saveEndpoint = () => {
    setBusy(true); setMsg('')
    updateSettings({ ai_base_url: aiUrl.trim(), ai_vision_model: aiVision.trim() })
      .then((s) => { setSettings(s); setMsg('✓ endpoint switched — takes effect on every replica within ~30s, no restart') })
      .catch((e) => setMsg(e.message || 'update failed'))
      .finally(() => setBusy(false))
  }
  const [costs, setCosts] = useState(null)
  useEffect(() => { getAiCosts().then(setCosts).catch(() => {}) }, [])
  const toggleAutoApply = () => {
    setBusy(true); setMsg('')
    updateSettings({ auto_apply_validated: !settings.auto_apply_validated })
      .then(setSettings)
      .catch((e) => setMsg(e.message || 'update failed'))
      .finally(() => setBusy(false))
  }
  const saveFolder = () => {
    setBusy(true); setMsg('')
    updateSettings({ drive_mirror_folder: folder })
      .then((s) => { setSettings(s); setMsg('✓ saved') })
      .catch((e) => setMsg(e.message || 'update failed'))
      .finally(() => setBusy(false))
  }
  if (!settings) return <p className="muted">Loading…</p>
  const Roll = ({ label, r }) => (
    <div style={{ flex: 1, minWidth: 150, border: '1px solid var(--line)', borderRadius: 8, padding: '10px 12px' }}>
      <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: .3 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>${(r?.cost_usd ?? 0).toFixed(2)}</div>
      <div className="muted" style={{ fontSize: 12 }}>{(r?.calls ?? 0).toLocaleString()} AI call{(r?.calls === 1) ? '' : 's'}{r?.avg_latency_ms ? ` · ${r.avg_latency_ms}ms avg` : ''}</div>
    </div>
  )
  return (
    <div style={{ maxWidth: 560 }}>
      <h3 style={{ marginTop: 0 }}>AI usage &amp; cost <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· governance</span></h3>
      <p className="muted" style={{ fontSize: 13 }}>
        Real per-call provenance, summed — never an estimate (ADR 0016). For this keyless
        local-AI build every external AI cost is a genuine <b>$0.00</b>: no per-token billing,
        and no document bytes leave your network. A governed cloud provider records its real
        cost and it appears here.
      </p>
      {costs && (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '10px 0' }}>
            <Roll label="Today" r={costs.today} />
            <Roll label="Last 30 days" r={costs.month} />
            <Roll label="All time" r={costs.all_time} />
          </div>
          {costs.all_time?.by_zone?.length > 0 && (
            <div className="muted" style={{ fontSize: 12 }}>
              Processing zone: {costs.all_time.by_zone.map((z) => `${z.key} (${z.calls})`).join(' · ')}
              {costs.all_time.by_zone.every((z) => z.key === 'local') && ' — nothing left your network 🟢'}
            </div>
          )}
        </>
      )}
      <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '20px 0' }} />
      <h3 style={{ marginTop: 0 }}>Remediated-file storage</h3>
      <p className="muted" style={{ fontSize: 13 }}>
        A remediated file's fixed copy is always written to Azure Blob first — the durable,
        must-succeed copy (ADR 0010). This controls whether it's <b>also</b> mirrored to Google
        Drive automatically right after, and which folder that mirror lands in.
      </p>
      <label style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: busy ? 'default' : 'pointer', margin: '16px 0' }}>
        <input type="checkbox" checked={settings.drive_mirror_enabled} onChange={toggle} disabled={busy} />
        <span>
          <b>Auto-mirror to Drive</b><br />
          <span className="muted" style={{ fontSize: 12 }}>
            {settings.drive_mirror_enabled
              ? 'On — every successful Blob remediation also tries to write a copy to Drive.'
              : 'Off — remediated files stay Blob-only. No automatic Drive write.'}
          </span>
        </span>
      </label>
      <label style={{ fontSize: 13, display: 'block' }}>Drive folder name
        <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Remediated"
                 disabled={busy || !settings.drive_mirror_enabled}
                 style={{ padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 6, flex: 1 }} />
          <button className="ghost small" onClick={saveFolder}
                  disabled={busy || !folder.trim() || !settings.drive_mirror_enabled || folder.trim() === settings.drive_mirror_folder}>
            Save
          </button>
        </div>
        <span className="muted" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
          Files already mirrored under a previous folder name aren't moved — only new remediations use the updated folder.
        </span>
      </label>
      <h3>AI draft auto-apply</h3>
      <p className="muted" style={{ fontSize: 13 }}>
        A vision draft grounded in the image's own text always auto-applies. This controls the
        NEXT tier: an ungrounded draft that an <b>independent second AI reading</b> confirms
        (consistency cross-check — a measurement, never the model grading itself). Drafts the
        cross-check does not confirm always queue for one-click human approval, and every
        applied fix is still verified by re-scan before anything is certified.
      </p>
      <label style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: busy ? 'default' : 'pointer', margin: '16px 0' }}>
        <input type="checkbox" checked={!!settings.auto_apply_validated} onChange={toggleAutoApply} disabled={busy} />
        <span>
          <b>Auto-apply cross-checked drafts</b><br />
          <span className="muted" style={{ fontSize: 12 }}>
            {settings.auto_apply_validated
              ? 'On — a draft confirmed by an independent second reading is applied without waiting for review (provenance says so on the fix).'
              : 'Off — every ungrounded draft waits for one-click human approval (the default).'}
          </span>
        </span>
      </label>
      <h3>AI endpoint <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· GPU burst without a restart</span></h3>
      <p className="muted" style={{ fontSize: 13 }}>
        Point the platform at a different Ollama endpoint (e.g. a burst GPU pod) at runtime —
        it takes effect on every replica within ~30 seconds, with <b>no container restart</b>,
        so running scans are never disturbed. Empty = the deploy's default. Every switch is
        audited, and the 🟢 local / 🟡 cloud provenance badge follows the endpoint truthfully.
      </p>
      <label style={{ fontSize: 13, display: 'block' }}>Ollama base URL
        <input value={aiUrl} onChange={(e) => setAiUrl(e.target.value)} disabled={busy}
               placeholder="empty = deploy default"
               style={{ display: 'block', width: '100%', padding: '4px 8px', margin: '6px 0 10px', border: '1px solid var(--line)', borderRadius: 6 }} />
      </label>
      <label style={{ fontSize: 13, display: 'block' }}>Vision model
        <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          <input value={aiVision} onChange={(e) => setAiVision(e.target.value)} disabled={busy}
                 placeholder="empty = deploy default (e.g. llava:13b on a GPU)"
                 style={{ padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 6, flex: 1 }} />
          <button className="ghost small" onClick={saveEndpoint} disabled={busy}>Apply</button>
        </div>
      </label>
      <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '20px 0' }} />
      <AIProvidersPanel />
      {msg && <p style={{ marginTop: 12, fontSize: 13, color: msg.startsWith('✓') ? '#3B6D11' : '#A32D2D' }}>{msg}</p>}
    </div>
  )
}
import Rubric from './Rubric.jsx'
import Disposition from './Disposition.jsx'
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
  const [owner, setOwner] = useState('')
  const [domains, setDomains] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getAllowlist()
      .then((d) => { setEmails(d.emails || []); setOwner(d.owner || ''); setDomains(d.domains || []) })
      .catch(() => setMsg('Could not load the test-user list.'))
      .finally(() => setLoaded(true))
  }, [])

  const add = () => {
    const e = input.trim().toLowerCase()
    if (!e.includes('@')) { setMsg('Enter a valid email.'); return }
    if (emails.includes(e)) { setMsg('Already added.'); setInput(''); return }
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

  const avatar = (e) => (e.trim()[0] || '?').toUpperCase()
  const dirty = loaded   // Save is always available once loaded; cheap idempotent write

  return (
    <section style={{ maxWidth: 640 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <h3 style={{ margin: 0 }}>Test users</h3>
        <span className="muted" style={{ fontSize: 13 }}>{emails.length} added · who can sign in &#38; scan</span>
      </div>

      {/* How access works — the two gates, stated plainly */}
      <div style={{ marginTop: 12, padding: '12px 14px', borderRadius: 10, background: '#EEF2FB', border: '1px solid #D3DDF1' }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: '#2B4A7E', marginBottom: 6 }}>Two things let someone in:</div>
        <div style={{ fontSize: 12.5, color: '#33405C', lineHeight: 1.55 }}>
          <div><b>1.</b> They’re on this list <span className="muted">— manage it right here; applies on their next sign-in.</span></div>
          <div><b>2.</b> They’re a Google <b>test user</b> <span className="muted">— required until the app is Google-verified. Add them once in&nbsp;</span>
            <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" rel="noopener noreferrer" style={{ color: '#2B6CB0', fontWeight: 600 }}>Google Cloud → OAuth consent screen ↗</a>.
          </div>
        </div>
      </div>

      {/* Add */}
      <div style={{ display: 'flex', gap: 8, margin: '14px 0 10px' }}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && add()}
               placeholder="name@gmail.com" aria-label="Add a test user email" type="email"
               style={{ flex: 1, padding: '8px 11px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit', fontSize: 14 }} />
        <button onClick={add}>+ Add user</button>
      </div>

      {/* Editable list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 14 }}>
        {loaded && emails.length === 0 && (
          <div className="muted" style={{ fontSize: 13, padding: '14px', textAlign: 'center', border: '1px dashed var(--line)', borderRadius: 8 }}>
            No test users added yet — add a Gmail above to grant access.
          </div>
        )}
        {emails.map((e) => {
          const isOwner = e === owner
          return (
            <div key={e} style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '8px 11px', borderRadius: 9, background: 'var(--surface)', border: '1px solid var(--line)' }}>
              <span aria-hidden="true" style={{ width: 30, height: 30, borderRadius: '50%', background: isOwner ? '#854F0B' : '#6D28D9', color: '#fff', fontSize: 14, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{avatar(e)}</span>
              <span style={{ fontSize: 14, flex: 1, wordBreak: 'break-all' }}>{e}</span>
              {isOwner
                ? <span title="The owner can’t be removed — anti-lockout safety" style={{ fontSize: 11.5, fontWeight: 600, color: '#854F0B', background: '#FBF1DF', border: '1px solid #EAD9BF', borderRadius: 20, padding: '3px 9px', whiteSpace: 'nowrap' }}>🔒 owner</span>
                : <button className="ghost small" onClick={() => remove(e)} aria-label={`Remove ${e}`}>Remove</button>}
            </div>
          )
        })}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button onClick={save} disabled={busy || !dirty}>{busy ? 'Saving…' : 'Save changes'}</button>
        {msg && <span className="muted" role="status" aria-live="polite" style={{ fontSize: 13 }}>{msg}</span>}
      </div>

      {/* Always-allowed domains (read-only) */}
      {domains.length > 0 && (
        <div style={{ marginTop: 20, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#6B7280', marginBottom: 8 }}>🔒 ALWAYS ALLOWED <span style={{ fontWeight: 400 }}>· by domain, set at deploy</span></div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
            {domains.map((d) => (
              <span key={d} style={{ fontSize: 12.5, padding: '4px 10px', borderRadius: 20, background: '#EAF3EC', border: '1px solid #CFE5D6', color: '#2F6B43' }}>anyone @{d}</span>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

// Friendly labels for the provider catalogue. Azure OpenAI is the only wired adapter in Phase 1;
// the others store config for a later adapter (the backend keeps their config, no cloud call yet).
const PROVIDER_LABELS = {
  azure_openai: 'Azure OpenAI', openai: 'OpenAI', anthropic: 'Anthropic',
  gemini: 'Google Gemini', bedrock: 'AWS Bedrock',
}
const ADAPTER_READY = new Set(['azure_openai'])

// ADR 0019 §6 — the admin's AI provider governance page. The KEY is never entered here: an admin's
// ops team provisions it as a container/Key-Vault secret, and this stores only the secret's NAME
// (key_secret_ref). The page shows whether the referenced secret is present, never its value.
function AIProvidersPanel() {
  const [providers, setProviders] = useState(null)
  const [draft, setDraft] = useState({})     // provider -> edited fields
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  useEffect(() => { getAiProviders().then((d) => setProviders(d.providers || [])).catch(() => setProviders([])) }, [])
  if (!providers) return null
  const edit = (p, field, val) => setDraft((d) => ({ ...d, [p]: { ...(d[p] || {}), [field]: val } }))
  const field = (row, f) => (draft[row.provider]?.[f] ?? row[f] ?? '')
  const save = (row) => {
    const d = draft[row.provider] || {}
    setBusy(row.provider); setNote('')
    putAiProvider({
      provider: row.provider,
      enabled: d.enabled ?? row.enabled,
      endpoint: field(row, 'endpoint'),
      deployment: field(row, 'deployment'),
      model: field(row, 'model'),
      key_secret_ref: field(row, 'key_secret_ref'),
    })
      .then((res) => { setProviders(res.providers); setDraft((x) => ({ ...x, [row.provider]: {} }))
                       setNote(`✓ ${PROVIDER_LABELS[row.provider] || row.provider} saved`) })
      .catch((e) => setNote(e.message || 'save failed'))
      .finally(() => setBusy(''))
  }
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>AI providers <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· governance &amp; bring-your-own-key</span></h3>
      <p className="muted" style={{ fontSize: 13 }}>
        The platform runs <b>local-first</b>: your on-box Ollama handles everything by default, at
        $0, with no document leaving your network. You may enable a governed cloud provider as a
        fallback for cases the local model can’t ground (e.g. dense charts) — escalation is
        transparent and only fires when local falls short.
      </p>
      <p className="muted" style={{ fontSize: 13, background: 'var(--card, #f7f4fb)', border: '1px solid var(--line)', borderRadius: 8, padding: '8px 12px' }}>
        🔐 <b>The key is never entered here.</b> Your ops team provisions it as a container / Key
        Vault secret; you enter only the secret’s <b>reference name</b> (e.g.
        <code> AZURE_OPENAI_API_KEY</code>). The key value never touches the database, this page, or
        a log — only whether it’s present is shown.
      </p>
      {providers.map((row) => {
        const ready = ADAPTER_READY.has(row.provider)
        const dirty = !!draft[row.provider] && Object.keys(draft[row.provider]).length > 0
        return (
          <div key={row.provider} style={{ border: '1px solid var(--line)', borderRadius: 10, padding: '12px 14px', margin: '10px 0', opacity: ready ? 1 : 0.7 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <b style={{ fontSize: 14 }}>{PROVIDER_LABELS[row.provider] || row.provider}</b>
              {!ready && <span className="muted" style={{ fontSize: 11 }}>· adapter coming (config saved)</span>}
              <span style={{ marginLeft: 'auto', fontSize: 12 }}
                    title="Whether the ops-provisioned secret named below is present in this environment">
                {row.key_present
                  ? <span style={{ color: '#2C5209' }}>🔵 key present · {row.credential_source}</span>
                  : <span className="muted">key not set</span>}
              </span>
            </div>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '10px 0', fontSize: 13 }}>
              <input type="checkbox" checked={draft[row.provider]?.enabled ?? row.enabled}
                     onChange={(e) => edit(row.provider, 'enabled', e.target.checked)} disabled={!ready} />
              <span>Enable as an escalation fallback {row.enabled ? '' : '(off — local-only)'}</span>
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <L label="Endpoint"><input value={field(row, 'endpoint')} placeholder="https://your.openai.azure.com"
                     onChange={(e) => edit(row.provider, 'endpoint', e.target.value)} style={INP} /></L>
              <L label="Deployment / model"><input value={field(row, 'deployment')} placeholder="gpt-4o"
                     onChange={(e) => edit(row.provider, 'deployment', e.target.value)} style={INP} /></L>
              <L label="Model (for cost)"><input value={field(row, 'model')} placeholder="gpt-4o"
                     onChange={(e) => edit(row.provider, 'model', e.target.value)} style={INP} /></L>
              <L label="Secret reference NAME (not the key)"><input value={field(row, 'key_secret_ref')} placeholder="AZURE_OPENAI_API_KEY"
                     onChange={(e) => edit(row.provider, 'key_secret_ref', e.target.value)} style={INP} /></L>
            </div>
            <button className="ghost small" style={{ marginTop: 10 }} onClick={() => save(row)}
                    disabled={busy === row.provider || !dirty}>
              {busy === row.provider ? 'Saving…' : 'Save'}
            </button>
          </div>
        )
      })}
      {note && <p style={{ fontSize: 13, color: note.startsWith('✓') ? '#3B6D11' : '#A32D2D' }}>{note}</p>}
    </div>
  )
}
const INP = { display: 'block', width: '100%', padding: '4px 8px', marginTop: 4, border: '1px solid var(--line)', borderRadius: 6, boxSizing: 'border-box' }
const L = ({ label, children }) => (<label style={{ fontSize: 12 }} className="muted">{label}{children}</label>)

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
          <button role="tab" aria-selected={tab === 'access'} className={tab === 'access' ? 'fchip on' : 'fchip'} onClick={() => setTab('access')}>Test users</button>
          <button role="tab" aria-selected={tab === 'drivemirror'} className={tab === 'drivemirror' ? 'fchip on' : 'fchip'} onClick={() => setTab('drivemirror')}>Remediated storage</button>
          <button role="tab" aria-selected={tab === 'disposition'} className={tab === 'disposition' ? 'fchip on' : 'fchip'} onClick={() => setTab('disposition')}>Disposition</button>
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
          {tab === 'drivemirror' && <DriveMirror />}
          {tab === 'disposition' && <Disposition />}
          {tab === 'data' && <ResetData />}
        </div>
      </div>
    </div>
  )
}
