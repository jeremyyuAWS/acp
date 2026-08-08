import { useState, useRef, useEffect } from 'react'
import { resetDemoData, getAllowlist, setAllowlist, getSettings, updateSettings, getAiCosts, getAiProviders, putAiProvider, getAiStatus } from './api.js'
import { SIM } from './sim.js'

// What a write is allowed to claim when the API layer marked its own answer `simulated`.
// A simulated response never reached a server, so it is neither a success nor a failure — the
// request was never made — and it must not borrow the vocabulary of either.
const SIM_NOT_WRITTEN =
  'SIM — nothing was written. This demo build has no backend, so the change is local to this browser '
  + 'tab and the platform still holds its previous value. Use a build served by the real API to change it.'
// One place that decides what a settings write may report, so a new caller cannot forget the flag.
const wrote = (s, ok) => (s?.simulated ? SIM_NOT_WRITTEN : ok)
// Three tones, not two. `msg.startsWith('✓') ? green : red` had no room for "the request was never
// made": amber says it plainly without dressing a demo build up as a platform error.
const msgColor = (m) => (m.startsWith('✓') ? '#3B6D11' : m.startsWith('SIM') ? '#6B4A0B' : '#A32D2D')

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
        Wipes <strong>all customer data</strong> for a completely fresh app: scan results,
        findings, per-file decisions, inventory, disposition audit, and the learned review
        memory — plus every remediated file, cached original and preview in blob storage, and
        Langfuse traces. Nothing from a prior customer is left behind.
        <strong> Your configuration is preserved</strong> — worker count, AI mode, schedule,
        rubric, and remediation programs. This cannot be undone.
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
    // The checkbox moving is not evidence of a write — under SIM it moves either way, because the
    // store it reflects is this browser tab. `wrote(s, '')` keeps the real build silent as before
    // and makes the demo build say which one just happened.
    updateSettings({ drive_mirror_enabled: !settings.drive_mirror_enabled })
      .then((s) => { setSettings(s); setMsg(wrote(s, '')) })
      .catch((e) => setMsg(e.message || 'update failed'))
      .finally(() => setBusy(false))
  }
  const [aiUrl, setAiUrl] = useState('')
  const [aiVision, setAiVision] = useState('')
  useEffect(() => { if (settings) { setAiUrl(settings.ai_base_url || ''); setAiVision(settings.ai_vision_model || '') } }, [settings])
  // Whether this signed-in user may actually write platform settings. PUT /settings is
  // owner-only (ACP_OWNER_EMAIL); the SPA gates Settings behind Platform Admin, so start
  // optimistic and let the /ai/providers probe below correct it on a 403.
  const [canEdit, setCanEdit] = useState(true)
  // Why vision is off, straight from the server. A pinned model name the endpoint has never had
  // is otherwise invisible in this panel, and this is the field that fixes it. Re-read after every
  // apply, since clearing the override is exactly what changes the answer.
  const [aiStatus, setAiStatus] = useState(null)
  const loadAiStatus = () => getAiStatus().then(setAiStatus).catch(() => {})
  useEffect(() => { loadAiStatus() }, [])
  // The endpoint save must never leave the form asserting something the server did not store.
  // A failed PUT used to leave the typed value on screen with the old value still live in
  // production, and the only notice was a line at the very bottom of the panel — below the
  // whole providers section, off-screen from the Apply button that caused it.
  //
  // `{ clearBoth: true }` is the detach path below. Tested as an option object rather than
  // positional args because this is also the onClick handler, and a React MouseEvent arriving
  // as the first parameter must not read as "clear the fields".
  const saveEndpoint = (opts) => {
    const clearBoth = opts?.clearBoth === true
    const want = clearBoth
      ? { ai_base_url: '', ai_vision_model: '' }
      : { ai_base_url: aiUrl.trim(), ai_vision_model: aiVision.trim() }
    const ok = clearBoth
      ? '✓ back to the deploy default endpoint and vision model'
      : '✓ endpoint switched — takes effect on every replica within ~30s, no restart'
    setBusy(true); setMsg('')
    updateSettings(want)
      .then((s) => {
        setSettings(s)
        // Trust the response, not the request: report what the server actually kept. A 200
        // whose body disagrees with what we sent is a silent no-op otherwise.
        //
        // `simulated` is checked FIRST because the drift test structurally cannot catch it: SIM
        // builds its response out of the request, so the two always agree and `drift` is always
        // empty. Comparing a response to a request only detects a no-op when something other than
        // this client authored the response.
        const drift = Object.keys(want).filter((k) => (s?.[k] ?? '') !== want[k])
        setMsg(s?.simulated ? SIM_NOT_WRITTEN
          : drift.length
          ? `⚠ the server kept ${drift.map((k) => `${k}="${s?.[k] ?? ''}"`).join(', ')} — your value was not applied`
          : ok)
        return loadAiStatus()
      })
      .catch((e) => {
        setAiUrl(settings.ai_base_url || ''); setAiVision(settings.ai_vision_model || '')
        setMsg(`⚠ not saved: ${e.message || 'update failed'} — the fields have been restored to the values the server holds`)
      })
      .finally(() => setBusy(false))
  }
  // Detaching a burst GPU means clearing BOTH fields (deploy/gpu/README.md). Doing it by hand is
  // where this came from on 2026-07-29: the URL was cleared, the model name was not, and the
  // orphaned name shadowed the deploy default until someone read the precedence code.
  const useDeployDefault = () => saveEndpoint({ clearBoth: true })
  const [costs, setCosts] = useState(null)
  useEffect(() => { getAiCosts().then(setCosts).catch(() => {}) }, [])
  const toggleAutoApply = () => {
    setBusy(true); setMsg('')
    updateSettings({ auto_apply_validated: !settings.auto_apply_validated })
      .then((s) => { setSettings(s); setMsg(wrote(s, '')) })
      .catch((e) => setMsg(e.message || 'update failed'))
      .finally(() => setBusy(false))
  }
  const saveFolder = () => {
    setBusy(true); setMsg('')
    updateSettings({ drive_mirror_folder: folder })
      .then((s) => { setSettings(s); setMsg(wrote(s, '✓ saved')) })
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
        <input type="checkbox" checked={settings.drive_mirror_enabled} onChange={toggle} disabled={busy || !canEdit} />
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
                 disabled={busy || !canEdit || !settings.drive_mirror_enabled}
                 style={{ padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 6, flex: 1 }} />
          <button className="ghost small" onClick={saveFolder}
                  disabled={busy || !canEdit || !folder.trim() || !settings.drive_mirror_enabled || folder.trim() === settings.drive_mirror_folder}>
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
        <input type="checkbox" checked={!!settings.auto_apply_validated} onChange={toggleAutoApply} disabled={busy || !canEdit} />
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
      {!canEdit && <ReadOnlyNotice />}
      <label style={{ fontSize: 13, display: 'block' }}>Ollama base URL
        <input value={aiUrl} onChange={(e) => setAiUrl(e.target.value)} disabled={busy || !canEdit}
               placeholder="empty = deploy default"
               style={{ display: 'block', width: '100%', padding: '4px 8px', margin: '6px 0 10px', border: '1px solid var(--line)', borderRadius: 6 }} />
      </label>
      <label style={{ fontSize: 13, display: 'block' }}>Vision model
        <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          <input value={aiVision} onChange={(e) => setAiVision(e.target.value)} disabled={busy || !canEdit}
                 placeholder="empty = deploy default (e.g. moondream on CPU, llava:13b on a GPU)"
                 style={{ padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 6, flex: 1 }} />
          <button className="ghost small" onClick={saveEndpoint} disabled={busy || !canEdit}>Apply</button>
        </div>
      </label>
      {/* `=== false` on purpose, and the reason is NOT part of the gate. Both halves were wrong:
          a truthy test treats an endpoint that never reported the field as "vision is fine", and
          requiring the reason meant a server that said false without explaining itself rendered
          nothing at all. The warning follows the verdict; the reason only refines it. */}
      {aiStatus?.vision_available === false && (
        <p role="status" style={{ margin: '10px 0 0', fontSize: 13, color: '#A32D2D' }}>
          ⚠ <b>Genuine alt text is off</b>
          {aiStatus.vision_unavailable_reason ? ` — ${aiStatus.vision_unavailable_reason}` : ''}.
          Until this resolves, WCAG 1.1.1 findings get a fill-in template for a human to complete,
          not an image-derived description.
        </p>
      )}
      {canEdit && (aiUrl || aiVision) && (
        <button className="ghost small" style={{ marginTop: 10 }} onClick={useDeployDefault} disabled={busy}>
          Use deploy default (clears both)
        </button>
      )}
      {/* The outcome belongs next to the control that caused it. The copy at the foot of the
          panel is far below the providers section and was missed entirely. */}
      {msg && <p role="status" aria-live="polite"
                 style={{ margin: '10px 0 0', fontSize: 13, color: msgColor(msg) }}>{msg}</p>}
      <hr style={{ border: 0, borderTop: '1px solid var(--line)', margin: '20px 0' }} />
      <AIProvidersPanel onAccess={setCanEdit} />
      {msg && <p style={{ marginTop: 12, fontSize: 13, color: msgColor(msg) }}>{msg}</p>}
    </div>
  )
}
import Rubric from './Rubric.jsx'
import ScanScope from './ScanScope.jsx'
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
function AIProvidersPanel({ onAccess }) {
  const [providers, setProviders] = useState(null)
  const [draft, setDraft] = useState({})     // provider -> edited fields
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  // A 403 here is the one reliable read-only signal the SPA has: /ai/providers and
  // PUT /settings share the same owner-only gate. Swallowing it (the old
  // `.catch(() => setProviders([]))`) left every admin field editable and every save
  // guaranteed to fail, which is how a non-owner spent a session typing into a form
  // that could not persist anything.
  const [denied, setDenied] = useState(false)
  useEffect(() => {
    getAiProviders()
      .then((d) => { setProviders(d.providers || []); onAccess?.(true) })
      .catch((e) => {
        const forbidden = /\b403\b|forbidden|owner/i.test(e?.message || '')
        setDenied(forbidden); setProviders([]); onAccess?.(!forbidden)
      })
  }, [])
  if (!providers) return null
  // Nothing to show read-only either — the GET that would have supplied the rows is what 403'd.
  if (denied) return <ReadOnlyNotice />
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
                       setNote(wrote(res, `✓ ${PROVIDER_LABELS[row.provider] || row.provider} saved`)) })
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
      {note && <p style={{ fontSize: 13, color: msgColor(note) }}>{note}</p>}
    </div>
  )
}
// Shown instead of an editable admin form when the API has told us this user cannot write it.
// Saying so up front is the whole point: the alternative is a form that accepts input and
// then fails, which is indistinguishable from the platform being broken.
const ReadOnlyNotice = () => (
  <p role="status" style={{ fontSize: 13, background: '#FBF1DF', border: '1px solid #EAD9BF',
                            borderRadius: 8, padding: '10px 12px', color: '#6B4A0B' }}>
    🔒 <b>Read-only.</b> These settings are owner-only, and you are signed in as another user —
    the fields are disabled because a save would be rejected. Ask the platform owner to change them.
  </p>
)
// Badges the whole admin panel on a build whose writes cannot reach a platform. Gated on the
// BUILD flag, not on a response, so it is on screen before the first save rather than after: the
// fake "✓ endpoint switched" was believed on the Netlify site precisely because nothing on the
// panel said otherwise until the outcome line — and the outcome line was the thing that lied.
// Same shape as ReadOnlyNotice above; both answer "why won't my change stick?" before it is asked.
const SimNotice = () => (
  <p role="status" style={{ margin: '10px 16px 0', fontSize: 13, background: '#FBF1DF',
                            border: '1px solid #EAD9BF', borderRadius: 8, padding: '10px 12px', color: '#6B4A0B' }}>
    🎭 <b>Demo build — every setting here is simulated.</b> Nothing on this screen reaches a
    platform: changes live in this browser tab until you reload, and no production endpoint, vision
    model, storage setting or user list is affected. Use a build served by the real API to change
    them for real.
  </p>
)
const INP = { display: 'block', width: '100%', padding: '4px 8px', marginTop: 4, border: '1px solid var(--line)', borderRadius: 6, boxSizing: 'border-box' }
const L = ({ label, children }) => (<label style={{ fontSize: 12 }} className="muted">{label}{children}</label>)

export default function Settings({ onClose, onRubricSaved, files = [], onOntologyChange, onDelegationChange, onFileTypeChange, onPrivilegeChange }) {
  const [tab, setTab] = useState('rules')
  const [dl, setDl] = useState(null) // 'xlsx' | 'pptx' while a deliverable is generating
  const [dlErr, setDlErr] = useState('')
  const panelRef = useRef(null)
  useDialog(panelRef, onClose)
  // console.error alone made a failed export indistinguishable from a slow one: the spinner
  // stopped, no file arrived, and nothing said why. Now the reason reaches the person who
  // clicked — these errors name a missing asset or a server returning the app instead of it,
  // which is a deployment fact an operator can act on.
  const grab = async (kind, fn) => {
    if (dl) return
    setDl(kind); setDlErr('')
    try { await fn() } catch (e) {
      console.error('deliverable export failed', e)
      setDlErr(e?.message || 'The download could not be prepared.')
    } finally { setDl(null) }
  }
  return (
    <div className="setoverlay" role="dialog" aria-modal="true" aria-label="Platform settings" onClick={onClose}>
      <div className="setpanel" ref={panelRef} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="sethead">
          <div><b>⚙ Platform settings</b><span className="muted"> · admin · rules &amp; validation</span></div>
          <button className="ghost small" aria-label="Close settings" onClick={onClose}>✕</button>
        </div>
        {/* Above the subtabs on purpose — it is true of every tab in this panel, not just the
            settings write paths. Rubric, Test users, Disposition and Reset data are SIM stubs too. */}
        {SIM && <SimNotice />}
        <div className="setexports">
          <span className="setexporthint">Updated deliverables — original format, with a live <b>Status</b> column reflecting what the platform ships today:</span>
          <div className="setexportbtns">
            <button className="dlbtn" disabled={!!dl} onClick={() => grab('xlsx', downloadUpdatedXlsx)}>{dl === 'xlsx' ? 'Preparing…' : '⤓ Coverage matrix · Excel'}</button>
            <button className="dlbtn" disabled={!!dl} onClick={() => grab('pptx', downloadUpdatedPptx)}>{dl === 'pptx' ? 'Preparing…' : '⤓ Method deck · PPT'}</button>
          </div>
          {dlErr && <p role="alert" style={{ fontSize: 12.5, color: '#A32D2D', margin: '6px 0 0' }}>⚠ {dlErr}</p>}
        </div>
        <div className="subtabs" role="tablist" aria-label="Settings sections">
          <button role="tab" aria-selected={tab === 'rules'} className={tab === 'rules' ? 'fchip on' : 'fchip'} onClick={() => setTab('rules')}>Scoring rules</button>
          <button role="tab" aria-selected={tab === 'validation'} className={tab === 'validation' ? 'fchip on' : 'fchip'} onClick={() => setTab('validation')}>Validation coverage</button>
          <button role="tab" aria-selected={tab === 'scope'} className={tab === 'scope' ? 'fchip on' : 'fchip'} onClick={() => setTab('scope')}>Scan scope</button>
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
          {tab === 'scope' && <ScanScope />}
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
