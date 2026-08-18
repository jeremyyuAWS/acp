import { useState, useEffect, useCallback } from 'react'
import {
  fetchScopeSelectors, fetchScopeRules, createScopeRule,
  setScopeRuleEnabled, deleteScopeRule, fetchScopedEligibility,
} from './api.js'

// The scope-rule editor (Discover/Assess PRD §4.4 / AC-09, Phase C4d).
//
// Admins define per-file WCAG scope rules — "Finance folders → this Core-17 subset, HR-owned
// content → that subset" — with precedence. The backend (api/routes/scope.py, merged C4c) owns
// resolution and validation; this is the owner-facing editor over it:
//   · a form to CREATE a rule (selector + value + Core-17 subset + priority + override + enabled),
//     surfacing the server's 400 validation message inline;
//   · the LIST of existing rules, priority-desc, each with an OVERRIDE badge, an enable/disable
//     toggle (PATCH) and a delete (DELETE); and
//   · the scope-aware eligible-file count (/assess/eligibility/scoped), refreshed after any change.
//
// PRECEDENCE, made legible: the effective code-set of a file is the UNION of every matching rule's
// codes, UNLESS a matching rule is an override — then the single highest-priority override REPLACES
// the union. Priority is shown on every row; the override hint says what an override does.

// What the value input means for each selector — labelled so an admin types the right thing.
const VALUE_LABEL = { folder: 'folder path', owner: 'owner email', department: 'department' }
const VALUE_PLACEHOLDER = { folder: 'e.g. Finance/', owner: 'e.g. jordan@acme.com', department: 'e.g. Legal' }
const SELECTOR_LABEL = { folder: 'Folder', owner: 'Owner', department: 'Department' }

export default function ScopeRules() {
  const [selectors, setSelectors] = useState([])       // ['folder','owner','department']
  const [catalog, setCatalog] = useState([])           // [{code, name, formats:[...]}] — the Core 17
  const [rules, setRules] = useState([])               // existing rules, priority-desc
  const [elig, setElig] = useState(null)               // {discovered, eligible, by_format, rules_applied}
  const [loaded, setLoaded] = useState(false)

  // Create-form state.
  const [name, setName] = useState('')
  const [selector, setSelector] = useState('folder')
  const [value, setValue] = useState('')
  const [codes, setCodes] = useState(() => new Set())
  const [priority, setPriority] = useState(0)
  const [isOverride, setIsOverride] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [formErr, setFormErr] = useState('')           // the inline 400 validation message
  const [busyId, setBusyId] = useState(null)           // rule being toggled/deleted

  // Refresh the rule list and the scope-aware eligible count together — the count depends on which
  // rules are enabled, so it moves whenever a rule is created, toggled or deleted.
  const refresh = useCallback(() => Promise.all([
    fetchScopeRules().catch(() => []),
    fetchScopedEligibility().catch(() => null),
  ]).then(([rs, e]) => { setRules(Array.isArray(rs) ? rs : []); setElig(e) }), [])

  useEffect(() => {
    let live = true
    fetchScopeSelectors().catch(() => ({ selectors: [], codes: [] })).then((sel) => {
      if (!live) return
      const sels = sel?.selectors || []
      setSelectors(sels)
      setCatalog(sel?.codes || [])
      if (sels.length && !sels.includes('folder')) setSelector(sels[0])
    }).then(() => refresh()).finally(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [refresh])

  const toggleCode = (code) => setCodes((s) => {
    const n = new Set(s); n.has(code) ? n.delete(code) : n.add(code); return n
  })

  const resetForm = () => {
    setName(''); setValue(''); setCodes(new Set()); setPriority(0)
    setIsOverride(false); setEnabled(true)
  }

  const submit = async (e) => {
    e?.preventDefault?.()
    setFormErr('')
    if (!value.trim()) { setFormErr('scope rule value must be non-empty'); return }
    if (codes.size === 0) { setFormErr('scope rule must select at least one WCAG code'); return }
    setSaving(true)
    try {
      await createScopeRule({
        name: name.trim(), selector, value: value.trim(), codes: [...codes],
        priority: Number(priority) || 0, is_override: isOverride, enabled,
      })
      resetForm()
      await refresh()
    } catch (err) {
      // The backend's 400 detail (the resolver's own message) — surfaced inline, not swallowed.
      setFormErr(err?.message || 'Could not create the scope rule.')
    } finally { setSaving(false) }
  }

  const onToggle = async (rule) => {
    setBusyId(rule.rule_id)
    try { await setScopeRuleEnabled(rule.rule_id, !rule.enabled); await refresh() }
    catch (_) { /* left as-is; the list re-reads on the next change */ }
    finally { setBusyId(null) }
  }

  const onDelete = async (rule) => {
    setBusyId(rule.rule_id)
    try { await deleteScopeRule(rule.rule_id); await refresh() }
    catch (_) { /* no-op */ }
    finally { setBusyId(null) }
  }

  const codeName = (code) => catalog.find((c) => c.code === code)?.name || code

  return (
    <section className="panel scoperules">
      <h2 style={{ margin: 0 }}>Scope rules</h2>
      <p className="muted" style={{ margin: '3px 0 14px', fontSize: 13, lineHeight: 1.5 }}>
        Assess different parts of the estate against different WCAG criteria — target files by
        folder, owner or department and assign a Core-17 subset. A file's checks are the
        <b> union</b> of every matching rule, unless an <b>override</b> replaces that union.
      </p>

      {/* ── CREATE FORM ─────────────────────────────────────────────────────────── */}
      <form className="scoperules-form" onSubmit={submit}>
        <div className="scoperules-frow">
          <label className="scoperules-field">
            <span className="scoperules-flabel">Rule name <span className="muted">(optional)</span></span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="e.g. Finance — full AA" aria-label="Rule name" />
          </label>
          <label className="scoperules-field">
            <span className="scoperules-flabel">Applies to</span>
            <select value={selector} aria-label="Selector"
                    onChange={(e) => setSelector(e.target.value)}>
              {selectors.map((s) => <option key={s} value={s}>{SELECTOR_LABEL[s] || s}</option>)}
            </select>
          </label>
          <label className="scoperules-field">
            <span className="scoperules-flabel">{VALUE_LABEL[selector] || 'value'}</span>
            <input type="text" value={value} onChange={(e) => setValue(e.target.value)}
                   placeholder={VALUE_PLACEHOLDER[selector] || ''}
                   aria-label={VALUE_LABEL[selector] || 'value'} />
          </label>
        </div>

        <fieldset className="scoperules-codes" aria-label="WCAG success criteria">
          <legend className="scoperules-flabel">WCAG criteria <span className="muted">· {codes.size} selected</span></legend>
          {!loaded ? (
            <p className="muted" style={{ fontSize: 13 }}>Loading the code-set…</p>
          ) : (
            <div className="scoperules-codegrid" role="group">
              {catalog.map((r) => {
                const on = codes.has(r.code)
                return (
                  <label key={r.code} className="scoperules-code">
                    <input type="checkbox" checked={on} onChange={() => toggleCode(r.code)}
                           aria-label={`${r.code} — ${r.name}`} />
                    <span><b>{r.code}</b> — {r.name}</span>
                  </label>
                )
              })}
            </div>
          )}
        </fieldset>

        <div className="scoperules-frow scoperules-frow-opts">
          <label className="scoperules-field scoperules-field-sm">
            <span className="scoperules-flabel">Priority</span>
            <input type="number" value={priority} aria-label="Priority"
                   onChange={(e) => setPriority(e.target.value)} />
          </label>
          <label className="scoperules-check">
            <input type="checkbox" checked={isOverride} aria-label="Override"
                   onChange={(e) => setIsOverride(e.target.checked)} />
            <span>Override <span className="muted">— replaces the union of matching rules instead of adding to it</span></span>
          </label>
          <label className="scoperules-check">
            <input type="checkbox" checked={enabled} aria-label="Enabled"
                   onChange={(e) => setEnabled(e.target.checked)} />
            <span>Enabled</span>
          </label>
        </div>

        {formErr && <p className="scoperules-err" role="alert">{formErr}</p>}

        <div className="emptyactions" style={{ marginTop: 4 }}>
          <button type="submit" disabled={saving || !loaded}>
            {saving ? 'Creating…' : 'Create scope rule'}
          </button>
        </div>
      </form>

      {/* ── EXISTING RULES ──────────────────────────────────────────────────────── */}
      <div className="scoperules-list">
        <div className="scoperules-listh">
          <b>{rules.length}</b> rule{rules.length === 1 ? '' : 's'}
          <span className="muted"> · highest priority first; overrides win over the union</span>
        </div>
        {rules.length === 0 ? (
          <p className="muted" style={{ fontSize: 13 }}>
            No scope rules yet — every file is assessed against the default Assess selection.
          </p>
        ) : rules.map((rule) => (
          <div key={rule.rule_id} className={rule.enabled ? 'scoperule' : 'scoperule off'}>
            <div className="scoperule-main">
              <div className="scoperule-head">
                {rule.name && <b className="scoperule-name">{rule.name}</b>}
                <span className="scoperule-target">
                  {SELECTOR_LABEL[rule.selector] || rule.selector}: <code>{rule.value}</code>
                </span>
                {rule.is_override && <span className="scoperule-override" title="Replaces the union of matching rules">OVERRIDE</span>}
                <span className="scoperule-prio muted">priority {rule.priority}</span>
              </div>
              <div className="scoperule-codes">
                {(rule.codes || []).map((code) => (
                  <span key={code} className="scoperule-codechip" title={codeName(code)}>
                    <b>{code}</b> {codeName(code)}
                  </span>
                ))}
              </div>
            </div>
            <div className="scoperule-actions">
              <button className="scoperule-toggle" disabled={busyId === rule.rule_id}
                      aria-pressed={rule.enabled} onClick={() => onToggle(rule)}>
                {rule.enabled ? 'Disable' : 'Enable'}
              </button>
              <button className="scoperule-del" disabled={busyId === rule.rule_id}
                      aria-label={`Delete rule ${rule.name || rule.value}`} onClick={() => onDelete(rule)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* ── SCOPE-AWARE ELIGIBILITY ─────────────────────────────────────────────── */}
      <div className="scoperules-elig" role="status" aria-live="polite">
        {elig ? (
          <div className="scoperules-elign">
            <b>{(elig.eligible || 0).toLocaleString()}</b> of {(elig.discovered || 0).toLocaleString()} files
            eligible once scope rules apply
            <span className="muted"> · {elig.rules_applied || 0} rule{(elig.rules_applied || 0) === 1 ? '' : 's'} reach a file</span>
          </div>
        ) : (
          <span className="muted" style={{ fontSize: 13 }}>—</span>
        )}
      </div>
    </section>
  )
}
