import { useState, useEffect } from 'react'
import { getSettings, updateSettings } from './api.js'
import { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'

// The operator scan scope, as a criterion × format grid.
//
// Until this panel the scope was a SETTING with no editor: choosing what a customer had agreed
// to assess meant editing SCOPE_PRESETS in Python, reviewing it and deploying — for a fact that
// is a customer's checklist, not a property of the code. The backend now accepts the scope as
// data (`scan_scope` may hold a JSON map, not only a preset name), and this is the surface that
// writes it.
//
// THE GRID IS DERIVED, NOT TYPED. SCOPE_UNIVERSE comes from scopePresets.js, generated from the
// backend's RULE_FORMATS ∪ REVIEW_FORMATS by scripts/gen_scope_presets.py with a CI drift guard.
// A pair appears only where the engine can actually reach a verdict, so this panel cannot offer
// a checkbox that would change nothing — and cannot drift into implying capability that does not
// exist, which on an accessibility product is the expensive kind of wrong.
//
// WHY "NO RESTRICTION" IS A SEPARATE CHOICE AND NOT AN EMPTY GRID. `{}` means no restriction on
// the backend — `in_scope()` has always treated a falsy scope as "everything" — so an empty
// selection saved literally would do the OPPOSITE of what an empty grid looks like it means.
// Rather than quietly translate, the panel asks the question directly: restrict, or don't. An
// operator who ticks nothing while "restrict" is chosen gets told to pick something, instead of
// silently enabling the whole estate.

const FMT_LABEL = { docx: 'DOCX', xlsx: 'XLSX', pptx: 'PPTX', pdf: 'PDF' }
const SIM_NOT_WRITTEN =
  'SIM — nothing was written. This demo build has no backend, so the change is local to this browser '
  + 'tab and the platform still holds its previous value. Use a build served by the real API to change it.'
const msgColor = (m) => (m.startsWith('✓') ? '#3B6D11' : m.startsWith('SIM') ? '#6B4A0B' : '#A32D2D')

// The stored value is a preset NAME or a JSON map — the same two forms the backend accepts. Both
// resolve to {sc: Set(formats)} here so the grid never has to care which was stored.
export function parseStoredScope(raw) {
  const val = (raw || '').trim()
  if (!val) return null                                  // null = no restriction
  let obj = null
  if (val[0] === '{') {
    try { obj = JSON.parse(val) } catch { return null }   // unusable reads as no restriction,
  } else {                                               // matching the backend's fail-open
    obj = SCOPE_PRESETS[val] || null
  }
  if (!obj) return null
  const out = {}
  for (const [sc, fmts] of Object.entries(obj)) {
    if (Array.isArray(fmts) && fmts.length) out[sc] = new Set(fmts)
  }
  return Object.keys(out).length ? out : null
}

const toPayload = (sel) => {
  const out = {}
  for (const [sc, fmts] of Object.entries(sel)) if (fmts.size) out[sc] = [...fmts].sort()
  return out
}

export default function ScanScope() {
  const [restrict, setRestrict] = useState(false)
  const [sel, setSel] = useState({})
  const [saved, setSaved] = useState('')       // the raw value as loaded, for the dirty check
  const [busy, setBusy] = useState(false)
  const [canEdit, setCanEdit] = useState(true)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    let alive = true
    getSettings().then((s) => {
      if (!alive) return
      const raw = s?.scan_scope || ''
      const parsed = parseStoredScope(raw)
      setSaved(raw)
      setRestrict(Boolean(parsed))
      setSel(parsed || {})
    }).catch(() => { /* the panel still renders; a save reports the real failure */ })
    return () => { alive = false }
  }, [])

  const has = (sc, f) => Boolean(sel[sc]?.has(f))
  const toggle = (sc, f) => {
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
    const all = row.formats.every((f) => has(row.sc, f))
    setSel((prev) => {
      const next = { ...prev }
      if (all) delete next[row.sc]
      else next[row.sc] = new Set(row.formats)
      return next
    })
    setMsg('')
  }
  const applyPreset = (name) => {
    const p = SCOPE_PRESETS[name] || {}
    const next = {}
    for (const [sc, fmts] of Object.entries(p)) next[sc] = new Set(fmts)
    setSel(next); setRestrict(true); setMsg('')
  }

  const chosen = Object.values(sel).reduce((n, s) => n + s.size, 0)
  const total = SCOPE_UNIVERSE.reduce((n, r) => n + r.formats.length, 0)

  const save = async () => {
    // An empty selection under "restrict" would store {} — which the backend reads as NO
    // restriction. Saving it would turn "assess nothing" into "assess everything", silently.
    if (restrict && chosen === 0) {
      setMsg('Pick at least one criterion, or choose “No restriction” — an empty selection would '
             + 'assess everything, which is the opposite of what it looks like.')
      return
    }
    setBusy(true); setMsg('')
    try {
      const payload = restrict ? toPayload(sel) : ''
      const res = await updateSettings({ scan_scope: payload })
      if (res?.simulated) { setMsg(SIM_NOT_WRITTEN); return }
      // Trust the SERVER's echo, not the request: a save that was accepted but stored something
      // else is exactly what this panel must not report as success.
      const back = res?.scan_scope ?? ''
      setSaved(back)
      const reparsed = parseStoredScope(back)
      setRestrict(Boolean(reparsed))
      setSel(reparsed || {})
      setMsg(restrict
        ? `✓ Scope saved — ${chosen} of ${total} criterion/format pairs in scope.`
        : '✓ Scope cleared — every criterion the engine supports is assessed.')
    } catch (e) {
      const m = String(e?.message || e)
      if (m.includes('403')) { setCanEdit(false); setMsg('Owner-only — this account cannot change the scope.') }
      else setMsg(`Could not save: ${m}`)
    } finally { setBusy(false) }
  }

  const dirty = (() => {
    const now = restrict ? JSON.stringify(toPayload(sel)) : ''
    const was = (() => {
      const p = parseStoredScope(saved)
      return p ? JSON.stringify(toPayload(p)) : ''
    })()
    return now !== was
  })()

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Scan scope
        <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}> · what this engagement assesses</span>
      </h3>
      <p className="muted" style={{ fontSize: 13 }}>
        Which <b>criterion × format</b> pairs the platform evaluates. Out-of-scope pairs read
        <i> not evaluated</i> — every file is still scanned and every in-scope result still counts,
        so narrowing the scope never flatters the score the way skipping a file type would.
        The grid offers only pairs the engine can actually reach a verdict on.
      </p>
      {!canEdit && (
        <p role="status" style={{ fontSize: 13, background: '#FBF1DF', border: '1px solid #EAD9BF',
                                  borderRadius: 8, padding: '10px 12px', color: '#6B4A0B' }}>
          🔒 <b>Read-only.</b> The scope is owner-only and you are signed in as another user.
        </p>
      )}

      <fieldset style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '10px 12px', margin: '12px 0' }}>
        <legend style={{ fontSize: 12, padding: '0 6px' }}>Scope mode</legend>
        <label style={{ display: 'block', fontSize: 13, marginBottom: 6 }}>
          <input type="radio" name="scopemode" checked={!restrict} disabled={busy || !canEdit}
                 onChange={() => { setRestrict(false); setMsg('') }} />
          {' '}No restriction — assess everything the engine supports
        </label>
        <label style={{ display: 'block', fontSize: 13 }}>
          <input type="radio" name="scopemode" checked={restrict} disabled={busy || !canEdit}
                 onChange={() => { setRestrict(true); setMsg('') }} />
          {' '}Restrict to the pairs selected below
        </label>
      </fieldset>

      {restrict && (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '0 0 8px' }}>
            {Object.keys(SCOPE_PRESETS).map((name) => (
              <button key={name} className="ghost small" disabled={busy || !canEdit}
                      onClick={() => applyPreset(name)}>Load “{name}”</button>
            ))}
            <button className="ghost small" disabled={busy || !canEdit || chosen === 0}
                    onClick={() => { setSel({}); setMsg('') }}>Clear selection</button>
            <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
              {chosen} of {total} pairs selected
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
              <caption className="sronly">
                Scan scope: tick each criterion and format this engagement assesses.
              </caption>
              <thead>
                <tr>
                  <th scope="col" style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>Criterion</th>
                  {SCOPE_FORMATS.map((f) => (
                    <th key={f} scope="col" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>{FMT_LABEL[f]}</th>
                  ))}
                  <th scope="col" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>All</th>
                </tr>
              </thead>
              <tbody>
                {SCOPE_UNIVERSE.map((row) => (
                  <tr key={row.sc}>
                    <th scope="row" style={{ textAlign: 'left', fontWeight: 400, padding: '3px 8px', whiteSpace: 'nowrap' }}>
                      <b>{row.sc}</b> {row.name} <span className="muted">· {row.level}</span>
                    </th>
                    {SCOPE_FORMATS.map((f) => (
                      <td key={f} style={{ textAlign: 'center', padding: '3px 8px' }}>
                        {row.formats.includes(f) ? (
                          <input type="checkbox" checked={has(row.sc, f)} disabled={busy || !canEdit}
                                 onChange={() => toggle(row.sc, f)}
                                 aria-label={`${row.sc} ${row.name}, ${FMT_LABEL[f]}`} />
                        ) : (
                          // Not a disabled checkbox: the engine has no verdict for this pair, so
                          // there is nothing to tick. A disabled box reads as "off", which would
                          // imply a choice was made.
                          <>
                            <span aria-hidden="true" className="muted">—</span>
                            <span className="sronly">{`${FMT_LABEL[f]} not applicable to ${row.sc}`}</span>
                          </>
                        )}
                      </td>
                    ))}
                    <td style={{ textAlign: 'center', padding: '3px 8px' }}>
                      <button className="ghost small" disabled={busy || !canEdit}
                              onClick={() => toggleRow(row)}
                              aria-label={`Toggle every format for ${row.sc} ${row.name}`}>
                        {row.formats.every((f) => has(row.sc, f)) ? 'none' : 'all'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
        <button className="ghost small" onClick={save} disabled={busy || !canEdit || !dirty}>
          {busy ? 'Saving…' : 'Save scope'}
        </button>
        {!dirty && <span className="muted" style={{ fontSize: 12 }}>No unsaved changes</span>}
      </div>
      {msg && <p role="status" aria-live="polite"
                 style={{ margin: '10px 0 0', fontSize: 13, color: msgColor(msg) }}>{msg}</p>}
    </div>
  )
}
