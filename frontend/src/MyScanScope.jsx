import { useState, useEffect } from 'react'
import { getMyScope, putMyScope, clearMyScope } from './api.js'
import { parseStoredScope } from './ScanScope.jsx'
import ScopeGrid, { scopeTotalPairs } from './ScopeGrid.jsx'

// The per-user scan-scope override editor (ADR 0035 stage 2, the user-facing surface).
//
// A signed-in reviewer sets their OWN scope on top of the owner default. The one rule that makes this
// safe for PHI — an override may only WIDEN, never narrow below what the owner mandated — is enforced
// server-side (the union in active_scope). This editor makes that rule VISIBLE rather than trusting the
// user to know it: the owner's mandated pairs render locked-on in the grid (a floor you can add to but
// never remove), and the user only ever ticks ADDITIONAL pairs. What is stored is those additions; the
// backend unions them with the owner default at scan time, so the owner mandate is always preserved even
// if it changes later.
const SIM_NOT_WRITTEN =
  'SIM — nothing was written. This demo build has no backend, so the change is local to this browser tab. '
  + 'Use a build served by the real API to save a personal scope.'
const msgColor = (m) => (m.startsWith('✓') ? 'var(--success-fg)' : m.startsWith('SIM') ? '#6B4A0B' : 'var(--error-fg-strong)')

const toPayload = (sel) => {
  const out = {}
  for (const [sc, fmts] of Object.entries(sel)) if (fmts.size) out[sc] = [...fmts].sort()
  return out
}
const asKey = (sel) => JSON.stringify(toPayload(sel))

export default function MyScanScope() {
  const [ownerScope, setOwnerScope] = useState(null)   // the owner default, {sc: Set} or null = no restriction
  const [sel, setSel] = useState({})                   // the user's ADDITIONS beyond the owner default
  const [savedKey, setSavedKey] = useState('{}')       // additions as loaded, for the dirty check
  const [mode, setMode] = useState('default')          // 'default' = no personal override | 'widen'
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    let alive = true
    getMyScope().then((s) => {
      if (!alive) return
      setOwnerScope(parseStoredScope(s?.owner_default || ''))
      const mine = parseStoredScope(s?.scan_scope || '')   // "" (none) and "" (empty) both read as none
      setSel(mine || {})
      setSavedKey(asKey(mine || {}))
      setMode(mine ? 'widen' : 'default')
      setLoaded(true)
    }).catch(() => { setLoaded(true) /* the panel still renders; a save reports the real failure */ })
    return () => { alive = false }
  }, [])

  const lockedHas = (sc, f) => Boolean(ownerScope?.[sc]?.has(f))   // owner-mandated pairs: locked-on
  const has = (sc, f) => Boolean(sel[sc]?.has(f))
  const toggle = (sc, f) => {
    if (lockedHas(sc, f)) return                                   // cannot remove an owner-required pair
    setSel((prev) => {
      const next = { ...prev }
      const fmts = new Set(next[sc] || [])
      if (fmts.has(f)) fmts.delete(f); else fmts.add(f)
      if (fmts.size) next[sc] = fmts; else delete next[sc]
      return next
    })
    setMsg('')
  }
  const toggleRow = (row) => {
    // Only the pairs not already locked by the owner are the user's to add/remove.
    const addable = row.formats.filter((f) => !lockedHas(row.sc, f))
    const all = addable.every((f) => has(row.sc, f))
    setSel((prev) => {
      const next = { ...prev }
      const fmts = new Set(next[row.sc] || [])
      addable.forEach((f) => (all ? fmts.delete(f) : fmts.add(f)))
      if (fmts.size) next[row.sc] = fmts; else delete next[row.sc]
      return next
    })
    setMsg('')
  }

  const added = Object.values(sel).reduce((n, s) => n + s.size, 0)
  const ownerCount = ownerScope
    ? Object.values(ownerScope).reduce((n, s) => n + s.size, 0) : 0
  const dirty = mode === 'widen' ? asKey(sel) !== savedKey : savedKey !== '{}'

  const save = async () => {
    setBusy(true); setMsg('')
    try {
      const additions = toPayload(sel)
      const clearing = mode === 'default' || Object.keys(additions).length === 0
      const res = clearing ? await clearMyScope() : await putMyScope(additions)
      if (res?.simulated) { setMsg(SIM_NOT_WRITTEN); return }
      const parsed = parseStoredScope(res?.scan_scope ?? '')
      setSel(parsed || {}); setSavedKey(asKey(parsed || {})); setMode(parsed ? 'widen' : 'default')
      setMsg(clearing
        ? '✓ Personal scope cleared — your scans use the organization default.'
        : `✓ Saved — your scans assess ${added} pair${added === 1 ? '' : 's'} beyond the organization default.`)
    } catch (e) {
      const m = String(e?.message || e)
      if (m.includes('401')) setMsg('Sign in to set a personal scan scope.')
      else setMsg(`Could not save: ${m}`)
    } finally { setBusy(false) }
  }

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>My scan scope
        <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}> · assess more than the org default, for your own scans</span>
      </h3>
      <p className="muted" style={{ fontSize: 13 }}>
        Your scans always assess everything your organization requires. Here you can add <b>more</b>
        criteria for your own runs — you can widen the scope, never narrow it, so a personal setting can
        never skip a check the organization asked for.
      </p>

      {loaded && ownerScope === null ? (
        <p role="status" style={{ fontSize: 13, background: '#EAF4EC', border: '1px solid #CDE6D2',
                                  borderRadius: 8, padding: '10px 12px', color: 'var(--success-fg)' }}>
          Your organization already assesses every supported criterion, so there is nothing a personal
          override can add.
        </p>
      ) : (
        <>
          <fieldset style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '10px 12px', margin: '12px 0' }}>
            <legend style={{ fontSize: 12, padding: '0 6px' }}>Personal scope</legend>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 6 }}>
              <input type="radio" name="myscopemode" checked={mode === 'default'} disabled={busy}
                     onChange={() => { setMode('default'); setMsg('') }} />
              {' '}Use the organization default ({ownerCount} pair{ownerCount === 1 ? '' : 's'})
            </label>
            <label style={{ display: 'block', fontSize: 13 }}>
              <input type="radio" name="myscopemode" checked={mode === 'widen'} disabled={busy}
                     onChange={() => { setMode('widen'); setMsg('') }} />
              {' '}Also assess additional criteria, selected below
            </label>
          </fieldset>

          {mode === 'widen' && (
            <>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '0 0 8px' }}>
                <button className="ghost small" disabled={busy || added === 0}
                        onClick={() => { setSel({}); setMsg('') }}>Clear additions</button>
                <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
                  {ownerCount} required by the org · <b>+{added}</b> added by you · {scopeTotalPairs} pairs total
                </span>
              </div>
              <ScopeGrid has={has} toggle={toggle} toggleRow={toggleRow} busy={busy} canEdit
                         lockedHas={lockedHas}
                         caption="Your scan scope: the organization's required pairs are locked on; tick any additional pairs to also assess." />
            </>
          )}
        </>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
        <button className="ghost small" onClick={save} disabled={busy || !dirty}>
          {busy ? 'Saving…' : 'Save my scope'}
        </button>
        {!dirty && <span className="muted" style={{ fontSize: 12 }}>No unsaved changes</span>}
      </div>
      {msg && <p role="status" aria-live="polite"
                 style={{ margin: '10px 0 0', fontSize: 13, color: msgColor(msg) }}>{msg}</p>}
    </div>
  )
}
