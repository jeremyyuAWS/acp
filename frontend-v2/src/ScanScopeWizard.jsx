import { useState, useEffect, Fragment } from 'react'
import { getSettings, updateSettings } from './api.js'
import { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'
import { TRACKED_17, RULE_DETAILS } from './ruleDetails.js'

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

// WCAG principle by the SC id's first digit — the grouping the matrix sections rows into.
const PRINCIPLES = [
  { digit: '1', name: 'Perceivable' },
  { digit: '2', name: 'Operable' },
  { digit: '3', name: 'Understandable' },
  { digit: '4', name: 'Robust' },
]

// Fix-mode filter labels, and the criterion → set-of-fix-modes map the fix-mode chips join on.
// Derived from RULE_DETAILS (each rule carries a `fixMode`), keyed by the rule's criterion. A
// criterion with several rules can offer several modes; one with no rule detail resolves to an
// empty set — "unknown", excluded from any fix-mode-filtered view rather than crashing.
const FIX_LABEL = { auto: 'Deterministic', 'ai-assisted': 'Assisted', 'human-only': 'Human review' }
const FIX_ORDER = ['auto', 'ai-assisted', 'human-only']
const FIXMODE_BY_SC = (() => {
  const out = {}
  for (const r of Object.values(RULE_DETAILS)) (out[r.sc] || (out[r.sc] = new Set())).add(r.fixMode)
  return out
})()

// ── Matrix cell / sticky styles ──────────────────────────────────────────────────────────────────
// Sticky needs an opaque background painted on the pinned cells (else scrolling content shows
// through) and a z-index order: the top-left corner sits above both the header row and the first
// column. borderCollapse must be `separate` for sticky offsets to hold, so borders live per-cell.
const CELL = { textAlign: 'center', padding: '3px 8px', borderBottom: '1px solid var(--line)' }
const STICKY_TOP = { position: 'sticky', top: 0, zIndex: 2, background: 'var(--surface)',
  padding: '5px 8px', borderBottom: '1px solid var(--line)' }
const STICKY_CORNER = { ...STICKY_TOP, left: 0, zIndex: 4, textAlign: 'left' }
const STICKY_LEFT = { position: 'sticky', left: 0, zIndex: 1, background: 'var(--surface)',
  textAlign: 'left', fontWeight: 400, padding: '3px 8px', whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--line)' }
const GROUP_ROW = { textAlign: 'left', padding: '6px 8px', background: 'var(--surface)',
  borderBottom: '1px solid var(--line)', borderTop: '1px solid var(--line)' }

// A compact select/deselect toggle used for the column, row and group controls — purple when it
// reads all-on, a muted outline otherwise. `st` is 'all' | 'some' | 'none'.
const selMini = (st) => ({
  cursor: 'pointer', font: 'inherit', fontSize: 11, lineHeight: 1.4, borderRadius: 6,
  padding: '1px 7px', color: 'inherit',
  border: `1px solid ${st === 'none' ? 'var(--line)' : '#6D28D9'}`,
  background: st === 'all' ? '#F3EEFC' : 'var(--surface)',
})

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

export default function ScanScopeWizard({ onStartScan, showStartButton = false,
                                          canEditScope = true, rememberDefault = true }) {
  const [restrict, setRestrict] = useState(false)
  const [sel, setSel] = useState({})
  const [saved, setSaved] = useState('')       // the raw value as loaded, for the dirty check
  const [busy, setBusy] = useState(false)
  // `scan_scope` is owner-only (PUT /settings is _require_admin). A non-owner used to discover this
  // only AFTER a save 403'd — by which point the review modal had closed and their edit was silently
  // dropped. `canEditScope` is the ownership signal threaded in from where the identity is known
  // (App passes me.allow.includes('settings'), the same gate the platform-admin UI uses), so a
  // non-owner gets read-only controls and a clear note UP FRONT. `forbidden` still handles the
  // belt-and-braces case of a 403 slipping through at save time.
  const [forbidden, setForbidden] = useState(false)
  const canEdit = canEditScope && !forbidden
  const [msg, setMsg] = useState('')
  const [remember, setRemember] = useState(rememberDefault)

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

  // ── matrix search + filters (view-only; they never mutate the scope) ──────────────────────────
  const [query, setQuery] = useState('')
  const [fSelected, setFSelected] = useState(false)
  const [fLevels, setFLevels] = useState(() => new Set())   // 'A' / 'AA'
  const [fSupportedAll, setFSupportedAll] = useState(false)
  const [fModes, setFModes] = useState(() => new Set())      // 'auto' / 'ai-assisted' / 'human-only'
  const toggleIn = (setter) => (val) => setter((prev) => {
    const n = new Set(prev); if (n.has(val)) n.delete(val); else n.add(val); return n
  })
  const toggleLevel = toggleIn(setFLevels)
  const toggleMode = toggleIn(setFModes)

  // The formats currently in scope — what "Supported by all selected formats" measures against.
  const activeFormats = SCOPE_FORMATS.filter(formatActive)

  const rowVisible = (row) => {
    const q = query.trim().toLowerCase()
    if (q && !`${row.sc} ${row.name}`.toLowerCase().includes(q)) return false
    if (fSelected && !row.formats.some((f) => has(row.sc, f))) return false
    if (fLevels.size && !fLevels.has(row.level)) return false
    if (fSupportedAll && !activeFormats.every((f) => row.formats.includes(f))) return false
    if (fModes.size) {
      const modes = FIXMODE_BY_SC[row.sc]                    // undefined = unknown → excluded
      if (!modes || ![...fModes].some((m) => modes.has(m))) return false
    }
    return true
  }
  const visibleRows = OFFERED.filter(rowVisible)
  const anyFilter = Boolean(query.trim()) || fSelected || fLevels.size > 0 || fSupportedAll || fModes.size > 0
  const clearFilters = () => {
    setQuery(''); setFSelected(false); setFLevels(new Set()); setFSupportedAll(false); setFModes(new Set())
  }

  // Visible rows sectioned by WCAG principle — empty groups drop out so a filtered view has no
  // orphan headers.
  const groups = PRINCIPLES
    .map((p) => ({ ...p, rows: visibleRows.filter((r) => r.sc[0] === p.digit) }))
    .filter((g) => g.rows.length)

  // all / some / none across a set of (criterion, format) pairs — drives aria-checked and whether
  // a click ticks or unticks.
  const tallState = (on, total) => (on === 0 ? 'none' : on >= total ? 'all' : 'some')
  const ariaChecked = (st) => (st === 'all' ? 'true' : st === 'some' ? 'mixed' : 'false')
  const rowState = (row) => tallState(row.formats.filter((f) => has(row.sc, f)).length, row.formats.length)
  const colRows = (f) => visibleRows.filter((r) => r.formats.includes(f))
  const colState = (f) => {
    const rows = colRows(f)
    return tallState(rows.filter((r) => has(r.sc, f)).length, rows.length)
  }
  const groupState = (rows) => {
    let on = 0, n = 0
    for (const r of rows) for (const f of r.formats) { n++; if (has(r.sc, f)) on++ }
    return tallState(on, n)
  }

  // Toggle a whole format COLUMN down the currently-visible rows only.
  const toggleColumn = (f) => {
    const rows = colRows(f)
    const on = rows.length > 0 && rows.every((r) => has(r.sc, f))
    setSel((prev) => {
      const next = { ...prev }
      for (const r of rows) {
        const s = new Set(next[r.sc] || [])
        if (on) s.delete(f); else s.add(f)
        if (s.size) next[r.sc] = s; else delete next[r.sc]
      }
      return next
    })
    setRestrict(true); setMsg('')
  }

  // Toggle every supported pair in a principle GROUP (its visible rows). `on` ticks, else unticks.
  const setGroup = (rows, on) => {
    setSel((prev) => {
      const next = { ...prev }
      for (const r of rows) { if (on) next[r.sc] = new Set(r.formats); else delete next[r.sc] }
      return next
    })
    setRestrict(true); setMsg('')
  }

  // A pill filter toggle. View-only, so it stays enabled even for a read-only account.
  const chip = (label, on, onClick, opts = {}) => (
    <button key={label} type="button" role="checkbox" aria-checked={on} onClick={onClick}
            disabled={busy} title={opts.title}
            style={{ cursor: 'pointer', font: 'inherit', fontSize: 12, borderRadius: 999,
                     padding: '3px 10px', color: 'inherit',
                     border: `1px solid ${on ? '#6D28D9' : 'var(--line)'}`,
                     background: on ? '#F3EEFC' : 'var(--surface)' }}>
      {label}
    </button>
  )

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
      if (m.includes('403')) { setForbidden(true); setMsg('Owner-only — this account cannot change the scope.') }
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
          🔒 <b>Read-only.</b> Scope is set by your workspace owner — this scan uses the shared scope.
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
          {/* Preset quick-picks + running count */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '0 0 8px', flexWrap: 'wrap' }}>
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

          {/* ── Search + filters ────────────────────────────────────────────── */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '0 0 6px' }}>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                   placeholder="Search criterion id or name" aria-label="Search criteria"
                   style={{ flex: '1 1 200px', minWidth: 160, font: 'inherit', fontSize: 13,
                            border: '1px solid var(--line)', borderRadius: 8, padding: '5px 10px',
                            background: 'var(--surface)', color: 'inherit' }} />
            {chip('Selected only', fSelected, () => setFSelected((v) => !v))}
            {chip('Level A', fLevels.has('A'), () => toggleLevel('A'))}
            {chip('Level AA', fLevels.has('AA'), () => toggleLevel('AA'))}
            {chip('Supported by all selected formats', fSupportedAll, () => setFSupportedAll((v) => !v),
              { title: activeFormats.length ? `Rows supporting every selected format (${activeFormats.map((f) => FMT_LABEL[f]).join(', ')})` : 'Rows supporting every selected format' })}
            {FIX_ORDER.map((m) => chip(FIX_LABEL[m], fModes.has(m), () => toggleMode(m),
              { title: `Fix mode: ${FIX_LABEL[m]}` }))}
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '0 0 8px' }}>
            <span className="muted" role="status" aria-live="polite" style={{ fontSize: 12 }}>
              Showing {visibleRows.length} of {OFFERED.length} criteria
            </span>
            {anyFilter && (
              <button className="ghost small" type="button" onClick={clearFilters}>Clear filters</button>
            )}
          </div>

          {/* ── The matrix (sticky header + criterion column) ───────────────── */}
          <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 360,
                        border: '1px solid var(--line)', borderRadius: 8 }}>
            <table style={{ borderCollapse: 'separate', borderSpacing: 0, fontSize: 13, width: '100%' }}>
              <caption className="sronly">
                Scan scope: tick each criterion and format this scan assesses. Rows are grouped by
                WCAG principle; unchecked but available pairs are excluded, and pairs the engine has
                no verdict for are marked Not supported.
              </caption>
              <thead>
                <tr>
                  <th scope="col" style={STICKY_CORNER}>Criterion</th>
                  {SCOPE_FORMATS.map((f) => {
                    const st = colState(f)
                    return (
                      <th key={f} scope="col" style={STICKY_TOP}>
                        <div style={{ fontWeight: 700 }}>{FMT_LABEL[f]}</div>
                        <button type="button" role="checkbox" aria-checked={ariaChecked(st)}
                                disabled={busy || !canEdit || colRows(f).length === 0}
                                onClick={() => toggleColumn(f)}
                                aria-label={`Select ${FMT_LABEL[f]} for all ${colRows(f).length} visible criteria`}
                                title={`Toggle ${FMT_LABEL[f]} down the visible rows`}
                                style={selMini(st)}>{st === 'all' ? 'Clear' : 'All'}</button>
                      </th>
                    )
                  })}
                  <th scope="col" style={STICKY_TOP}>Row</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => {
                  const gst = groupState(g.rows)
                  return (
                    <Fragment key={g.digit}>
                      <tr>
                        <td colSpan={SCOPE_FORMATS.length + 2} style={GROUP_ROW}>
                          <span style={{ position: 'sticky', left: 0, display: 'inline-flex',
                                         alignItems: 'center', gap: 8 }}>
                            <button type="button" role="checkbox" aria-checked={ariaChecked(gst)}
                                    disabled={busy || !canEdit}
                                    onClick={() => setGroup(g.rows, gst !== 'all')}
                                    aria-label={`Select all criteria in ${g.name}`}
                                    style={selMini(gst)}>{gst === 'all' ? 'None' : 'All'}</button>
                            <b>{g.name}</b>
                            <span className="muted" style={{ fontWeight: 400 }}>· {g.rows.length}</span>
                          </span>
                        </td>
                      </tr>
                      {g.rows.map((row) => {
                        const rst = rowState(row)
                        return (
                          <tr key={row.sc}>
                            <th scope="row" style={STICKY_LEFT}>
                              <b>{row.sc}</b> {row.name} <span className="muted">· {row.level}</span>
                            </th>
                            {SCOPE_FORMATS.map((f) => {
                              if (!row.formats.includes(f)) {
                                return (
                                  <td key={f} title="Not supported"
                                      style={{ ...CELL, background: 'var(--surface)' }}>
                                    <span aria-hidden="true" className="muted" style={{ opacity: 0.45 }}>·</span>
                                    <span className="sronly">{`${FMT_LABEL[f]}: Not supported for ${row.sc}`}</span>
                                  </td>
                                )
                              }
                              const on = has(row.sc, f)
                              return (
                                <td key={f} style={{ ...CELL, background: on ? '#F3EEFC' : 'transparent' }}>
                                  <input type="checkbox" checked={on} disabled={busy || !canEdit}
                                         onChange={() => toggle(row.sc, f)}
                                         aria-label={`${row.sc} ${row.name}, ${FMT_LABEL[f]}`} />
                                </td>
                              )
                            })}
                            <td style={CELL}>
                              <button type="button" role="checkbox" aria-checked={ariaChecked(rst)}
                                      disabled={busy || !canEdit} onClick={() => toggleRow(row)}
                                      aria-label={`Select every format for ${row.sc} ${row.name}`}
                                      style={selMini(rst)}>{rst === 'all' ? 'None' : 'All'}</button>
                            </td>
                          </tr>
                        )
                      })}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
          {visibleRows.length === 0 && (
            <p className="muted" role="status" style={{ fontSize: 13, margin: '8px 2px 0' }}>
              No criteria match these filters. <button className="ghost small" type="button" onClick={clearFilters}>Clear filters</button>
            </p>
          )}
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
