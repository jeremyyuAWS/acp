import { useState, useEffect } from 'react'
import { getSettings, updateSettings } from './api.js'
import { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'
import { TRACKED_17 } from './ruleDetails.js'

// ── Scan-scope WIZARD (Phase 1) ─────────────────────────────────────────────────────────────────
//
// A scan-launch wizard that OWNS its own scope state — one source of truth for the whole surface.
// It replaces the dense admin grid as the FIRST decision an operator makes, and keeps that grid
// available behind a "Customize" reveal for experts (docs/scan-scope-wizard-spec.md).
//
// The scope model, serialisation and guards are REPLICATED from ScanScope.jsx deliberately, not
// imported: ScanScope owns its own component state and tests, and coupling the two would churn
// both. The pieces here are small and behaviour-identical — `sel` is a {sc: Set(formats)} map,
// `toPayload`/`parseStoredScope` are the same two forms the backend accepts, an empty selection
// under "restrict" is refused rather than saved (backend reads `{}` as NO restriction, the exact
// opposite of "assess nothing"), and a save trusts the SERVER's echo, not its own request.

// The criteria this wizard OFFERS — SCOPE_UNIVERSE (every criterion×format pair the engine can
// reach a verdict on) narrowed to the 17 criteria Mova iO actually tracks. Derived, never typed,
// so it can neither offer a checkbox the engine has no verdict for nor hide a tracked capability.
const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))

const FMT_LABEL = { docx: 'DOCX', xlsx: 'XLSX', pptx: 'PPTX', pdf: 'PDF' }

// How many tracked criteria the engine can reach a verdict on for each format — the count each
// format card shows. Derived from OFFERED, NOT hardcoded, so it tracks the generated universe.
const FMT_COUNT = Object.fromEntries(
  SCOPE_FORMATS.map((f) => [f, OFFERED.filter((r) => r.formats.includes(f)).length]),
)

const SIM_NOT_WRITTEN =
  'SIM — nothing was written. This demo build has no backend, so the change is local to this browser '
  + 'tab and the platform still holds its previous value. Use a build served by the real API to change it.'
const EMPTY_GUARD =
  'Pick at least one criterion, or choose “Everything supported” — an empty selection would assess '
  + 'everything, which is the opposite of what it looks like.'
const msgColor = (m) => (m.startsWith('✓') ? '#3B6D11' : m.startsWith('SIM') ? '#6B4A0B' : '#A32D2D')

// The stored value is a preset NAME or a JSON map — the two forms the backend accepts. Both resolve
// to {sc: Set(formats)} so nothing downstream has to care which was stored. (Same as ScanScope.)
export function parseStoredScope(raw) {
  const val = (raw || '').trim()
  if (!val) return null                                   // null = no restriction
  let obj = null
  if (val[0] === '{') {
    try { obj = JSON.parse(val) } catch { return null }    // unusable reads as no restriction,
  } else {                                                // matching the backend's fail-open
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
const payloadJson = (sel) => JSON.stringify(toPayload(sel))

// A preset materialised as {sc: Set} and as its canonical payload JSON, so a selection can be
// matched back to the profile that produced it (drives which profile pill reads as chosen).
const presetSel = (name) => {
  const p = SCOPE_PRESETS[name] || {}
  const out = {}
  for (const [sc, fmts] of Object.entries(p)) out[sc] = new Set(fmts)
  return out
}
const PRESET_JSON = {
  'acp-core-17': payloadJson(presetSel('acp-core-17')),
  'engagement-14': payloadJson(presetSel('engagement-14')),
}

// The full OFFERED grid as a selection — what "Everything supported" evaluates, and the base a
// format toggle edits when it starts from no-restriction.
const fullGridSel = () => {
  const out = {}
  for (const r of OFFERED) out[r.sc] = new Set(r.formats)
  return out
}

// Which profile a (restrict, sel) pair corresponds to — derived, so the pills never drift from the
// selection they describe.
const profileFor = (restrict, sel) => {
  if (!restrict) return 'everything'
  const j = payloadJson(sel)
  if (j === PRESET_JSON['acp-core-17']) return 'core-17'
  if (j === PRESET_JSON['engagement-14']) return 'engagement-14'
  return 'custom'
}

const PROFILES = [
  { id: 'core-17', label: 'Core 17', tag: 'Recommended', preset: 'acp-core-17',
    hint: 'The 17 criteria Mova iO tracks, every supported format.' },
  { id: 'engagement-14', label: 'Engagement 14', preset: 'engagement-14',
    hint: 'A narrower 14-criterion engagement scope.' },
  { id: 'custom', label: 'Custom scope',
    hint: 'Pick criteria and formats by hand below.' },
  { id: 'everything', label: 'Everything supported',
    hint: 'No restriction — assess every criterion the engine supports.' },
]

export default function ScanScopeWizard({ onStartScan, showStartButton = false }) {
  const [restrict, setRestrict] = useState(false)
  const [sel, setSel] = useState({})
  const [saved, setSaved] = useState('')       // the raw value as loaded, for the dirty check
  const [busy, setBusy] = useState(false)
  const [canEdit, setCanEdit] = useState(true)
  const [msg, setMsg] = useState('')
  const [remember, setRemember] = useState(true)

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

  const profile = profileFor(restrict, sel)

  // The selection the summary and format cards reason about: the real `sel` under restrict, or the
  // full grid when "Everything supported" is chosen (so all four cards read as on).
  const effective = restrict ? sel : fullGridSel()

  const has = (sc, f) => Boolean(sel[sc]?.has(f))
  const formatActive = (f) => Object.values(effective).some((s) => s.has(f))

  const chosen = Object.values(effective).reduce((n, s) => n + s.size, 0)
  const nCriteria = Object.values(effective).filter((s) => s.size).length
  const nFormats = SCOPE_FORMATS.filter(formatActive).length
  // Combinations inside the chosen criteria × chosen formats rectangle the engine cannot evaluate —
  // reported as "Not evaluated", never counted as passes.
  const unsupported = Math.max(0, nCriteria * nFormats - chosen)

  // Criteria in the SAVED scope this wizard no longer offers (written before the tracked-list
  // narrowing, or straight to the API). Preserved by toPayload, but surfaced so the count on screen
  // can always be reconciled with the rows.
  const hidden = Object.entries(sel)
    .filter(([sc, fmts]) => fmts.size && !OFFERED.some((r) => r.sc === sc))
    .map(([sc]) => sc)
    .sort()

  const applyPreset = (name) => { setSel(presetSel(name)); setRestrict(true); setMsg('') }

  const selectProfile = (id) => {
    if (id === 'everything') { setRestrict(false); setMsg('') ; return }
    const p = PROFILES.find((x) => x.id === id)
    if (p?.preset) { applyPreset(p.preset); return }
    // Custom — keep whatever is selected, just switch out of no-restriction so the grid drives it.
    setRestrict(true); setMsg('')
  }

  // Toggle a whole format COLUMN across the selection. Materialises the full grid first when
  // starting from no-restriction, so the four cards behave the same in every mode.
  const toggleFormat = (f) => {
    const base = restrict ? sel : fullGridSel()
    const on = Object.values(base).some((s) => s.has(f))
    const next = {}
    if (on) {
      for (const [sc, s] of Object.entries(base)) {
        const copy = new Set(s); copy.delete(f)
        if (copy.size) next[sc] = copy
      }
    } else {
      for (const [sc, s] of Object.entries(base)) next[sc] = new Set(s)
      for (const r of OFFERED) if (r.formats.includes(f)) (next[r.sc] || (next[r.sc] = new Set())).add(f)
    }
    setSel(next); setRestrict(true); setMsg('')
  }
  const selectAllFormats = () => { setSel(fullGridSel()); setRestrict(true); setMsg('') }
  const clearAllFormats = () => { setSel({}); setRestrict(true); setMsg('') }

  const toggle = (sc, f) => {
    setSel((prev) => {
      const next = { ...prev }
      const fmts = new Set(next[sc] || [])
      if (fmts.has(f)) fmts.delete(f); else fmts.add(f)
      if (fmts.size) next[sc] = fmts; else delete next[sc]
      return next
    })
    setRestrict(true); setMsg('')
  }
  const toggleRow = (row) => {
    const all = row.formats.every((f) => has(row.sc, f))
    setSel((prev) => {
      const next = { ...prev }
      if (all) delete next[row.sc]
      else next[row.sc] = new Set(row.formats)
      return next
    })
    setRestrict(true); setMsg('')
  }

  const total = OFFERED.reduce((n, r) => n + r.formats.length, 0)

  // Persist the scope. Returns true when the platform accepted (or was cleared), false when it was
  // refused or only simulated — the caller uses that to decide whether "Start scan" proceeds.
  const save = async () => {
    if (restrict && chosen === 0) { setMsg(EMPTY_GUARD); return false }
    setBusy(true); setMsg('')
    try {
      const payload = restrict ? toPayload(sel) : ''
      const res = await updateSettings({ scan_scope: payload })
      if (res?.simulated) { setMsg(SIM_NOT_WRITTEN); return false }
      // Trust the SERVER's echo, not the request.
      const back = res?.scan_scope ?? ''
      setSaved(back)
      const reparsed = parseStoredScope(back)
      setRestrict(Boolean(reparsed))
      setSel(reparsed || {})
      setMsg(restrict
        ? `✓ Scope saved — ${chosen} supported checks in scope.`
        : '✓ Scope cleared — every criterion the engine supports is assessed.')
      return true
    } catch (e) {
      const m = String(e?.message || e)
      if (m.includes('403')) { setCanEdit(false); setMsg('Owner-only — this account cannot change the scope.') }
      else setMsg(`Could not save: ${m}`)
      return false
    } finally { setBusy(false) }
  }

  const startScan = async () => {
    if (restrict && chosen === 0) { setMsg(EMPTY_GUARD); return }
    // "Remember" persists this scope as the platform default for next time; either way the scan
    // runs. A read-only account cannot persist, so it just starts with the scope already stored.
    if (remember && canEdit) { await save() }
    onStartScan?.()
  }

  const dirty = (() => {
    const now = restrict ? payloadJson(sel) : ''
    const p = parseStoredScope(saved)
    const was = p ? payloadJson(p) : ''
    return now !== was
  })()

  const profileLabel = (PROFILES.find((p) => p.id === profile) || {}).label || 'Custom scope'

  return (
    <div>
      <p style={{ fontSize: 13, margin: '0 0 4px' }}>
        Choose what this scan should evaluate. The same scope will be used for assessment,
        remediation, reporting, and export.
        {' '}
        <span aria-hidden="true" title="Unsupported combinations are reported as 'Not evaluated' and are never counted as passes."
              style={{ cursor: 'help', color: 'var(--muted)' }}>ⓘ</span>
        <span className="sronly">
          Unsupported combinations are reported as 'Not evaluated' and are never counted as passes.
        </span>
      </p>

      {!canEdit && (
        <p role="status" style={{ fontSize: 13, background: '#FBF1DF', border: '1px solid #EAD9BF',
                                  borderRadius: 8, padding: '10px 12px', color: '#6B4A0B' }}>
          🔒 <b>Read-only.</b> The scope is owner-only and you are signed in as another user.
        </p>
      )}

      {/* ── 1. Scan profile ─────────────────────────────────────────────────── */}
      <div style={{ margin: '12px 0 4px', fontSize: 12, fontWeight: 700, letterSpacing: '.04em', color: 'var(--muted)' }}>
        SCAN PROFILE
      </div>
      <div role="radiogroup" aria-label="Scan profile"
           style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {PROFILES.map((p) => {
          const on = profile === p.id
          return (
            <button key={p.id} type="button" role="radio" aria-checked={on}
                    disabled={busy || !canEdit} title={p.hint}
                    onClick={() => selectProfile(p.id)}
                    style={{ flex: '1 1 140px', textAlign: 'left', cursor: 'pointer',
                             border: `1px solid ${on ? '#6D28D9' : 'var(--line)'}`,
                             background: on ? '#F3EEFC' : 'var(--surface)', color: 'inherit',
                             borderRadius: 10, padding: '8px 10px', font: 'inherit' }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {p.label}{p.tag && <span className="muted" style={{ fontWeight: 400 }}> — {p.tag}</span>}
              </div>
              <div className="muted" style={{ fontSize: 11.5 }}>{p.hint}</div>
            </button>
          )
        })}
      </div>

      {/* ── 2. File formats ─────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '16px 0 4px' }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.04em', color: 'var(--muted)' }}>FILE FORMATS</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button className="ghost small" type="button" disabled={busy || !canEdit} onClick={selectAllFormats}>Select all</button>
          <button className="ghost small" type="button" disabled={busy || !canEdit} onClick={clearAllFormats}>Clear all</button>
        </span>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {SCOPE_FORMATS.map((f) => {
          const on = formatActive(f)
          return (
            <button key={f} type="button" role="checkbox" aria-checked={on}
                    aria-label={`${FMT_LABEL[f]} — ${FMT_COUNT[f]} supported criteria`}
                    disabled={busy || !canEdit} onClick={() => toggleFormat(f)}
                    style={{ flex: '1 1 90px', cursor: 'pointer', textAlign: 'center',
                             border: `2px solid ${on ? '#6D28D9' : 'var(--line)'}`,
                             background: on ? '#F3EEFC' : 'var(--surface)', color: 'inherit',
                             borderRadius: 10, padding: '12px 8px', font: 'inherit' }}>
              <div style={{ fontSize: 15, fontWeight: 700 }}>{FMT_LABEL[f]}</div>
              <div className="muted" style={{ fontSize: 11.5 }}>{FMT_COUNT[f]} supported criteria</div>
            </button>
          )
        })}
      </div>

      {/* ── 3. Summary line ─────────────────────────────────────────────────── */}
      <p role="status" aria-live="polite" style={{ fontSize: 13, margin: '12px 0 2px' }}>
        <b>{profileLabel}</b> · {nFormats} format{nFormats !== 1 ? 's' : ''} · {chosen} supported checks selected
        {hidden.length > 0 && (
          <span className="muted"> · <b title={`Not shown: ${hidden.join(', ')}`}>{hidden.length} outside the tracked list</b></span>
        )}
      </p>
      <p className="muted" style={{ fontSize: 12, margin: '0 0 4px' }}>
        {unsupported} unsupported combination{unsupported !== 1 ? 's' : ''} will not be evaluated
      </p>

      {/* ── 4. Customize criteria and combinations (collapsed) ──────────────── */}
      <details style={{ borderTop: '1px solid var(--line)', marginTop: 8 }}>
        <summary style={{ padding: '8px 0', cursor: 'pointer', fontSize: 13, userSelect: 'none' }}>
          Customize criteria and combinations
        </summary>
        <div style={{ paddingBottom: 8 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '0 0 8px' }}>
            <button className="ghost small" type="button" disabled={busy || !canEdit}
                    onClick={() => applyPreset('acp-core-17')}>Core 17</button>
            <button className="ghost small" type="button" disabled={busy || !canEdit}
                    onClick={() => applyPreset('engagement-14')}>Engagement 14</button>
            <button className="ghost small" type="button" disabled={busy || !canEdit || chosen === 0}
                    onClick={() => { setSel({}); setRestrict(true); setMsg('') }}>Clear selection</button>
            <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>
              {chosen} supported checks selected
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
              <caption className="sronly">
                Scan scope: tick each criterion and format this scan assesses.
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
                {OFFERED.map((row) => (
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
                          <>
                            <span aria-hidden="true" className="muted">—</span>
                            <span className="sronly">{`${FMT_LABEL[f]} not applicable to ${row.sc}`}</span>
                          </>
                        )}
                      </td>
                    ))}
                    <td style={{ textAlign: 'center', padding: '3px 8px' }}>
                      <button className="ghost small" type="button" disabled={busy || !canEdit}
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
        </div>
      </details>

      {/* ── 5/7. Footer ─────────────────────────────────────────────────────── */}
      {showStartButton ? (
        <>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, margin: '12px 0 0' }}>
            <input type="checkbox" checked={remember} disabled={busy}
                   onChange={(e) => setRemember(e.target.checked)} />
            Remember these selections for my next scan
          </label>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
            <button className="ghost small" type="button" disabled={busy} onClick={() => onStartScan?.({ cancel: true })}>Cancel</button>
            <button type="button" disabled={busy} onClick={startScan}>
              {busy ? 'Saving…' : 'Start scan →'}
            </button>
          </div>
        </>
      ) : (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
          <button className="ghost small" type="button" onClick={save} disabled={busy || !canEdit || !dirty}>
            {busy ? 'Saving…' : 'Save as reusable scope'}
          </button>
          {!dirty && <span className="muted" style={{ fontSize: 12 }}>No unsaved changes</span>}
        </div>
      )}

      {msg && <p role="status" aria-live="polite"
                 style={{ margin: '10px 0 0', fontSize: 13, color: msgColor(msg) }}>{msg}</p>}
    </div>
  )
}
