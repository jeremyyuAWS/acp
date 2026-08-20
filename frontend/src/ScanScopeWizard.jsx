import { useState, useEffect, useMemo, Fragment } from 'react'
import { getSettings, updateSettings, getScanLocations, setScanLocations,
         listFolders, listSpFolders } from './api.js'
import { scopeFooterPart, blockedReason } from './wizardScopeReady.js'
import FolderPicker from './FolderPicker.jsx'
import { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'
import { TRACKED_17, RULE_DETAILS } from './ruleDetails.js'
import { ASSESSMENT_FALLBACK, assessmentFor } from './capability.js'
import { reusableScopes, describeScope, whenLabel } from './recentScopes.js'
import { lastRunOfScope, coverageSentence } from './scopeHistory.js'

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

// ── READINESS (ADR 0023 assessment axis) ─────────────────────────────────────────────────────────
// SCOPE_UNIVERSE says which (criterion, format) pairs the engine CAN reach — a code fact. It is
// broader than what ACP can actually ASSESS: the assessment table (capability.js, CI-locked to the
// backend) is the "can ACP determine compliance?" answer, and a pair absent there, or marked
// 'human', yields no verdict a tester could act on. Those pairs are OFFERED but NOT READY: we grey
// them out and take them out of selection so nobody scopes a scan around a cell that returns nothing.
// A cell is READY when its assessment lane is 'auto' (🟢 automated) or 'review' (🟡
// detects, human confirms). Both produce a result; only 'human'/absent do not.
const STEPS = ['Drive locations', 'Formats & criteria', 'Review']

const laneOf = (sc, f) => assessmentFor(ASSESSMENT_FALLBACK, f, sc)   // 'auto' | 'review' | 'human' | null
const isReady = (sc, f) => laneOf(sc, f) === 'auto' || laneOf(sc, f) === 'review'

// The criteria this wizard OFFERS — SCOPE_UNIVERSE narrowed to the 17 criteria Mova iO tracks.
// Each row carries `.formats` (what the engine reaches — for the not-supported vs not-ready render
// distinction) AND `.ready` (the subset ACP can actually assess — the ONLY formats selection,
// counting and the presets operate on). Derived, never typed, so it tracks the generated universe
// and the assessment table together.
const OFFERED = SCOPE_UNIVERSE
  .filter((r) => TRACKED_17.has(r.sc))
  .map((r) => ({ ...r, ready: r.formats.filter((f) => isReady(r.sc, f)) }))

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

// How many tracked criteria ACP can actually ASSESS for each format — the count each format card
// shows. Counts READY cells only (not merely engine-reachable ones), so the card never promises a
// number the scan can't deliver. Derived from OFFERED, NOT hardcoded.
const FMT_COUNT = Object.fromEntries(
  SCOPE_FORMATS.map((f) => [f, OFFERED.filter((r) => r.ready.includes(f)).length]),
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

// Drop every NOT-READY (criterion, format) pair from a {sc: Set} selection, and drop any criterion
// left empty. Applied to presets and to the stored scope on load, so `sel` only ever holds pairs
// ACP can assess — counts, toggles and the saved payload can't promise a cell that returns nothing.
const readyOnly = (sel) => {
  const out = {}
  for (const [sc, fmts] of Object.entries(sel || {})) {
    const kept = new Set([...fmts].filter((f) => isReady(sc, f)))
    if (kept.size) out[sc] = kept
  }
  return out
}

// A preset materialised as {sc: Set} (READY pairs only) and as its canonical payload JSON, so a
// selection can be matched back to the profile that produced it (drives which profile pill reads as
// chosen). A preset that lists a not-ready pair contributes only its ready formats here.
const presetSel = (name) => readyOnly(
  Object.fromEntries(Object.entries(SCOPE_PRESETS[name] || {}).map(([sc, fmts]) => [sc, new Set(fmts)])),
)
const PRESET_JSON = {
  'acp-core-17': payloadJson(presetSel('acp-core-17')),
  'engagement-14': payloadJson(presetSel('engagement-14')),
}

// The full OFFERED grid as a selection — what "Everything supported" evaluates, and the base a
// format toggle edits when it starts from no-restriction. READY cells only: "everything supported"
// means every criterion ACP can assess, not every pair the engine merely reaches.
const fullGridSel = () => {
  const out = {}
  for (const r of OFFERED) if (r.ready.length) out[r.sc] = new Set(r.ready)
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

// Which stored location set a scan of `source` uses. The scan itself resolves 'all' to a single
// backend source from the tokens present (App.doScan), so this mirrors that rule rather than
// inventing a second one — two different answers to "which source is this?" is how the card and
// the run end up describing different estates.
export function locationsKeyFor(source, { hasDrive = false, hasSP = false } = {}) {
  if (source === 'sharepoint') return hasSP ? 'sharepoint' : null
  if (source === 'drive' || source === 'all') return hasDrive ? 'drive' : (hasSP ? 'sharepoint' : null)
  return null
}

export default function ScanScopeWizard({ onStartScan, showStartButton = false,
                                          canEditScope = true, rememberDefault = false,
                                          source = 'all', hasDrive = false, hasSP = false,
                                          scans = [] }) {
  // ── FOLDER SCOPE (PRD §6, step 1) ──────────────────────────────────────────────────────────
  //
  // WHOSE ANSWER IS THIS? The Sources card stores a folder set per CONNECTION; this wizard
  // chooses one per RUN. Two stores with no stated relationship is how the card ends up saying
  // "Scans: HR" while last night's run covered the whole Drive — the boundary defect in a new
  // costume, since anyone reading the card to interpret a count reads the wrong boundary.
  //
  // So the rule is: the card is the DEFAULT and seeds this control, a change here applies to THIS
  // RUN only, and writing back to the card is an explicit checkbox. The two therefore agree unless
  // somebody deliberately diverges them, and the run records its own scope regardless
  // (scan_runs.scope is frozen at scan start, ADR 0035).
  //
  // The criteria half now follows the SAME rule, which it did not before: "Remember these
  // selections" was opt-OUT and on by default, so a one-off narrow criteria choice was written to
  // the platform default for everyone unless somebody noticed a ticked box and unticked it. That
  // is the identical failure the folder half is careful about — a one-off quietly becoming
  // configuration — with the defaults the wrong way round. Both are now explicit, off by default,
  // and shown only once the run actually differs from what is stored.
  const locKey = locationsKeyFor(source, { hasDrive, hasSP })
  const [folders, setFolders] = useState([])
  const [excluded, setExcluded] = useState([])
  const [savedFolders, setSavedFolders] = useState(null)   // null = not loaded yet
  // THREE STEPS, because one panel asking for folders, formats, criteria and engine switches at
  // once makes every decision compete with every other. The order is deliberate: where, then what,
  // then confirm — folders decide which estate is judged, criteria only decide how each document
  // in it is judged, so asking criteria first invites tuning 53 checks over the wrong half of a
  // Drive. Progressive disclosure, not more surface.
  const [step, setStep] = useState(1)
  // "Entire source" vs "Specific folders" is asked EXPLICITLY rather than inferred from an empty
  // selection. Empty and everything look identical otherwise, and the reassuring reading of a
  // blank list is the wrong one — the same rule the picker and the source card already follow.
  const [scopeMode, setScopeMode] = useState('all')   // 'all' | 'some'
  const [saveFolders, setSaveFolders] = useState(false)    // write back to the card, off by default

  useEffect(() => {
    if (!locKey) { setSavedFolders([]); return undefined }
    let alive = true
    getScanLocations().then((r) => {
      if (!alive) return
      const inc = (r.locations || {})[locKey] || []
      const exc = ((r.locations || {})._exclude || {})[locKey] || []
      setFolders(inc); setExcluded(exc); setSavedFolders(inc)
      if (inc.length) setScopeMode('some')
    }).catch(() => { if (alive) setSavedFolders([]) })
    return () => { alive = false }
  }, [locKey])

  // Diverging from the card is legitimate — it is what "this run only" means — but it must be
  // SAID. An unremarked difference between the card and the run is the whole failure mode.
  // The inline picker seeds its own selection from `initial` at MOUNT, so anything that replaces
  // the selection from outside it (choosing "Entire source", applying a recent scope) has to
  // remount it. Without this the browser keeps showing the previous chips while the wizard state
  // says something else — two answers to "what am I about to scan?" on one screen, which is the
  // failure the two-column layout exists to remove.
  const [pickerSeed, setPickerSeed] = useState(0)
  const chooseAll = () => { setScopeMode('all'); setFolders([]); setExcluded([]); setPickerSeed((n) => n + 1) }

  // The same component serves two surfaces: the scan-launch modal (stepped) and the Settings
  // scope editor (one panel, no start button). Stepping the editor would hide half its controls
  // behind a flow that has nowhere to go.
  const atStep = (n) => !showStartButton || step === n


  const foldersDiffer = savedFolders !== null
    && JSON.stringify(folders.map((f) => f.id).sort())
       !== JSON.stringify((savedFolders || []).map((f) => f.id).sort())

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

  // ── REUSE A SCOPE YOU HAVE ACTUALLY RUN ────────────────────────────────────────────────────
  // Derived from `scan_runs.scope`, not from a saved-scopes store. A saved scope is a claim about
  // what WILL be covered; a run's frozen scope is a record of what WAS, and only the second can be
  // checked. Reusing one also keeps the two runs comparable — a diff cannot tell a document that
  // got worse from a document measured against fewer criteria unless both boundaries agree.
  const reusable = useMemo(() => reusableScopes(scans, locKey), [scans, locKey])
  const [reusedKey, setReusedKey] = useState(null)

  const applyScope = (e) => {
    setFolders(e.folders)
    // Carve-outs are carried over even though the run recorded only their IDS. Dropping them
    // would WIDEN this scan while the control the user clicked was labelled as a narrowing; the
    // name is what is missing, so the chip says that rather than printing a raw Drive id.
    setExcluded(e.excluded.map((f) => ({ id: f.id, name: f.name || 'folder not named on that run' })))
    setScopeMode(e.folders.length ? 'some' : 'all')
    setPickerSeed((n) => n + 1)
    // Round-tripped through the SAME parser the stored scope uses, so a reused scope and a saved
    // one cannot normalise differently — and readyOnly drops pairs this release cannot assess, so
    // an old scope does not resurrect a cell that would return nothing.
    const parsed = e.scanScope ? parseStoredScope(JSON.stringify(e.scanScope)) : null
    setRestrict(Boolean(parsed))
    setSel(parsed ? readyOnly(parsed) : {})
    setReusedKey(e.key)
    setMsg('')
  }

  useEffect(() => {
    let alive = true
    getSettings().then((s) => {
      if (!alive) return
      const raw = s?.scan_scope || ''
      const parsed = parseStoredScope(raw)
      setSaved(raw)
      setRestrict(Boolean(parsed))
      // A scope stored before the readiness narrowing may name not-ready pairs; drop them so the
      // grid, counts and dirty check only ever reason about cells ACP can assess.
      setSel(parsed ? readyOnly(parsed) : {})
    }).catch(() => { /* the panel still renders; a save reports the real failure */ })
    return () => { alive = false }
  }, [])

  // What this EXACT scope covered last time, matched on the whole frozen boundary — locations,
  // carve-outs and criteria together, in the shape scanner records them. Recomputed on every
  // render rather than memoised: `scans` is one user's run list and the match is a few string
  // comparisons, and a stale memo here would caption one boundary's count with another's, which
  // is the precise failure this is meant to prevent.
  const lastRun = lastRunOfScope(scans,
    { folders, excluded, scan_scope: restrict ? toPayload(sel) : null }, locKey)

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
      for (const r of OFFERED) if (r.ready.includes(f)) (next[r.sc] || (next[r.sc] = new Set())).add(f)
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
    const all = row.ready.length > 0 && row.ready.every((f) => has(row.sc, f))
    setSel((prev) => {
      const next = { ...prev }
      if (all) delete next[row.sc]
      else next[row.sc] = new Set(row.ready)
      return next
    })
    setRestrict(true); setMsg('')
  }

  const total = OFFERED.reduce((n, r) => n + r.ready.length, 0)

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
    if (fSelected && !row.ready.some((f) => has(row.sc, f))) return false
    if (fLevels.size && !fLevels.has(row.level)) return false
    if (fSupportedAll && !activeFormats.every((f) => row.ready.includes(f))) return false
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
  const rowState = (row) => tallState(row.ready.filter((f) => has(row.sc, f)).length, row.ready.length)
  const colRows = (f) => visibleRows.filter((r) => r.ready.includes(f))
  const colState = (f) => {
    const rows = colRows(f)
    return tallState(rows.filter((r) => has(r.sc, f)).length, rows.length)
  }
  const groupState = (rows) => {
    let on = 0, n = 0
    for (const r of rows) for (const f of r.ready) { n++; if (has(r.sc, f)) on++ }
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
      for (const r of rows) { if (on) next[r.sc] = new Set(r.ready); else delete next[r.sc] }
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
    // Explicit write-back only. A one-off narrow scan must not quietly reconfigure the connection:
    // every later scheduled scan would then cover less, and it would look like configuration
    // somebody chose on purpose.
    if (saveFolders && locKey) {
      try { await setScanLocations(locKey, folders, excluded) } catch { /* the run still goes */ }
    }
    onStartScan?.({ folders, exclude: excluded })
  }

  const dirty = (() => {
    const now = restrict ? payloadJson(sel) : ''
    const p = parseStoredScope(saved)
    // Project the stored scope through readyOnly too: `sel` is always ready-only, so a scope saved
    // before the narrowing (which may list not-ready pairs) must be compared on the same footing or
    // it reads as dirty the instant it loads.
    const was = p ? payloadJson(readyOnly(p)) : ''
    return now !== was
  })()

  const profileLabel = (PROFILES.find((p) => p.id === profile) || {}).label || 'Custom scope'

  // One line answering "what am I about to run?", visible at every step. Locations first because
  // that is the decision the count will later be a count OF.
  // The locations half used to read "Entire source" for ANY empty list, so with "Specific
  // folders" selected and nothing picked the footer contradicted the mode selector directly above
  // it — and agreed with the run that would actually have happened. Three states, told apart.
  // Why the primary action is unavailable, or null. A reason rather than a boolean: a dead button
  // with no explanation is its own defect, and the reason is the thing the user has to act on.
  const blocked = locKey ? blockedReason(scopeMode, folders) : null

  const footerSummary = [
    locKey ? scopeFooterPart(scopeMode, folders, excluded) : null,
    `${nFormats} format${nFormats === 1 ? '' : 's'}`,
    profileLabel,
  ].filter(Boolean).join(' · ')

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

      {/* ── Stepper ─────────────────────────────────────────────────────────── */}
      {/* Numbered, not just visually distinct: a step count is the cheapest way to say "there is
          an end to this" to somebody looking at a dense configuration screen for the first time. */}
      {showStartButton && (
        <ol style={{ display: 'flex', gap: 0, listStyle: 'none', margin: '0 0 14px', padding: 0,
                     fontSize: 12.5, alignItems: 'center' }}>
          {STEPS.map((label, i) => {
            const n = i + 1
            const on = step === n
            const done = step > n
            return (
              <li key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {i > 0 && <span aria-hidden="true" className="muted"
                                style={{ margin: '0 10px' }}>──</span>}
                <button type="button"
                        // Going BACK by clicking a completed step is free; jumping forward is not
                        // offered, because a later step summarises choices the earlier ones make.
                        disabled={!done}
                        onClick={() => done && setStep(n)}
                        aria-current={on ? 'step' : undefined}
                        style={{ display: 'flex', alignItems: 'center', gap: 6, font: 'inherit',
                                 background: 'none', border: 'none', padding: 0,
                                 cursor: done ? 'pointer' : 'default',
                                 color: on ? 'var(--ink)' : 'var(--muted)',
                                 fontWeight: on ? 650 : 400 }}>
                  <span aria-hidden="true" style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 20, height: 20, borderRadius: 999, fontSize: 11.5, fontWeight: 600,
                    border: `1px solid ${on || done ? '#6D28D9' : 'var(--line)'}`,
                    background: on ? '#6D28D9' : 'transparent',
                    color: on ? '#fff' : (done ? '#6D28D9' : 'var(--muted)') }}>
                    {done ? '✓' : n}
                  </span>
                  {label}
                </button>
              </li>
            )
          })}
        </ol>
      )}

      {/* ── 0. Drive locations (PRD §6 step 1) ──────────────────────────────── */}
      {/* FIRST, because it is the question with the largest effect on what a scan means: criteria
          decide how each document is judged, folders decide which estate is being judged at all.
          Asking it after the criteria invites someone to tune 53 checks and then discover they
          were tuning them over the wrong half of the Drive. */}
      {atStep(1) && locKey && (
        <>
          <div style={{ margin: '4px 0', fontSize: 12, fontWeight: 700, letterSpacing: '.04em',
                        color: 'var(--muted)' }}>
            DRIVE LOCATIONS
          </div>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
            Choose which locations ACP should assess. Subfolders are included unless you exclude them.
          </div>


          {/* The two answers, as an explicit choice. Inferring "entire source" from an empty
              selection means the most consequential scope decision is made by NOT clicking. */}
          <div role="radiogroup" aria-label="What to assess"
               style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            {[['all', 'Entire connected source', 'Every accessible folder'],
              ['some', 'Specific folders', 'Assess only selected projects or departments']]
              .map(([id, title, hint]) => {
                const on = scopeMode === id
                return (
                  <button key={id} type="button" role="radio" aria-checked={on} disabled={busy}
                          onClick={() => (id === 'all' ? chooseAll() : setScopeMode('some'))}
                          style={{ flex: '1 1 200px', textAlign: 'left', cursor: 'pointer',
                                   border: `1px solid ${on ? '#6D28D9' : 'var(--line)'}`,
                                   background: on ? '#F3EEFC' : 'var(--surface)', color: 'inherit',
                                   borderRadius: 10, padding: '10px 12px', font: 'inherit' }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
                    <div className="muted" style={{ fontSize: 11.5 }}>{hint}</div>
                  </button>
                )
              })}
          </div>

          {/* THE BROWSER IS ON THE PAGE, not behind a "Choose folders…" link into a modal.
              The link version made the two halves of one decision sequential: you picked inside a
              dialog, saved, closed it, and only then read a row of chips on the screen underneath.
              The scope you were assembling was never visible while you were assembling it, and it
              became visible at exactly the point it had stopped being cheap to change. Inline and
              two-column, every tick moves a chip that is already on screen — an over-wide
              selection is something you SEE rather than something the count tells you afterwards,
              which is the whole shape of the defect this screen exists to prevent. */}
          {savedFolders === null ? (
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>Loading…</div>
          ) : scopeMode === 'all' ? (
            // Said out loud rather than left blank. "Nothing selected" and "everything" look the
            // same on screen otherwise, and the reassuring reading of a blank row is the wrong one.
            <div style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>Entire source</b> — every accessible folder
            </div>
          ) : (
            <div style={{ marginBottom: 8 }}>
              <FolderPicker
                layout="inline"
                key={`${locKey}:${pickerSeed}`}
                rootName={locKey === 'drive' ? 'My Drive' : 'OneDrive'}
                lister={locKey === 'drive' ? listFolders : (parent) => listSpFolders(parent)}
                initial={folders}
                initialExclude={excluded}
                // "Specific folders" IS the claim to narrow, so an empty list here is unfinished,
                // not "everything". Without this the picker reports the source-card meaning.
                requireSelection
                // It has no Save of its own: the wizard footer is the only footer on this screen,
                // and a second commit button next to it would make "saved" ambiguous. So the
                // picker reports as you tick.
                onChange={(inc, exc) => { setFolders(inc); setExcluded(exc || []) }} />
            </div>
          )}

          {/* Past scopes are an ACCELERATOR, not the decision. They used to sit at the top of this
              step, above the mode selector, which put a scan-history browser in front of the thing
              the user came here to choose — and offered a second, competing set of scope answers
              two inches above "Entire connected source / Specific folders".

              Collapsed and placed after the selection, so it is reachable when wanted and silent
              when not. Not a nested modal: this dialog is already a modal, and a modal inside a
              modal loses the reader's place.

              These come from `scan_runs.scope`, the boundary each run FROZE at scan start, so every
              entry is a record of what was covered rather than a claim about what would be. A run
              with no recorded scope is deliberately absent: NULL means unknown, and applying
              unknown would apply as "everything". */}
          {reusable.length > 0 && (
            <details style={{ marginBottom: 10 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12.5, color: 'var(--muted)' }}>
                Use a recent scope
                <span style={{ marginLeft: 6 }}>{reusable.length} available</span>
              </summary>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                {reusable.map((e) => {
                  const on = reusedKey === e.key
                  return (
                    <button key={e.key} type="button" disabled={busy} aria-pressed={on}
                            onClick={() => applyScope(e)}
                            style={{ textAlign: 'left', cursor: 'pointer', font: 'inherit',
                                     border: `1px solid ${on ? '#6D28D9' : 'var(--line)'}`,
                                     background: on ? '#F3EEFC' : 'var(--surface)', color: 'inherit',
                                     borderRadius: 10, padding: '7px 10px', flex: '1 1 240px' }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600 }}>{describeScope(e)}</div>
                      <div className="muted" style={{ fontSize: 11.5 }}>
                        Last run {whenLabel(e.at)}
                      </div>
                    </button>
                  )
                })}
              </div>
              {reusedKey && (
                // Applying one is not the end of the decision, it is the start: the browser above
                // now shows what was applied, and saying so is what stops "reused" being taken for
                // "verified". Anything reused is still editable, and still frozen fresh at start.
                <div role="status" aria-live="polite" className="muted"
                     style={{ fontSize: 11.5, marginTop: 6 }}>
                  Applied to this run — check the locations and criteria above before starting.
                </div>
              )}
            </details>
          )}

          {/* Divergence from the connection default is allowed — that is what "this run" means —
              but never silent: an unremarked difference between the card and the run is the exact
              failure this whole arrangement exists to prevent. */}
          {foldersDiffer && (
            <div style={{ fontSize: 12.5, background: '#F1EFF3', border: '1px solid var(--line)',
                          borderRadius: 8, padding: '9px 12px', marginBottom: 10, lineHeight: 1.45 }}>
              This differs from the folders saved on the source. It applies to <b>this scan only</b>.
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                <input type="checkbox" checked={saveFolders} disabled={busy}
                       onChange={(e) => setSaveFolders(e.target.checked)} />
                Also save as the default for this source
              </label>
            </div>
          )}

        </>
      )}

      {/* A source with no folder hierarchy to narrow — a local corpus, or a connector that is not
          signed in. Step 1 still SAYS something: a blank first page with a Continue button under
          it is a dead end that reads as a broken screen, and it also hides the fact that this run
          will cover everything. */}
      {atStep(1) && !locKey && (
        <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: '12px 14px',
                      fontSize: 12.5, lineHeight: 1.5 }}>
          <b>Entire connected source</b>
          <div className="muted" style={{ marginTop: 4 }}>
            This source has no folder hierarchy to narrow, so every accessible file is in scope.
            Connect Google Drive or OneDrive to choose specific folders.
          </div>
        </div>
      )}

      {/* ── 1. Scan profile ─────────────────────────────────────────────────── */}
      {atStep(2) && (<>
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
                             position: 'relative',
                             // Selected = white with a purple BORDER and a tick, not a purple
                             // fill. Filling every selected card made four equally-important
                             // choices compete with each other and with the profile cards above;
                             // the state is just as legible from the border, and the panel stops
                             // shouting.
                             border: `2px solid ${on ? '#6D28D9' : 'var(--line)'}`,
                             background: 'var(--surface)', color: 'inherit',
                             opacity: FMT_COUNT[f] ? 1 : 0.55,
                             borderRadius: 10, padding: '12px 8px', font: 'inherit' }}>
              {on && (
                <span aria-hidden="true" style={{ position: 'absolute', top: 5, right: 7,
                                                  color: '#6D28D9', fontSize: 12 }}>✓</span>
              )}
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
      {/* OPEN ONLY ON PURPOSE. A recommended profile already answers this question, so the full
          criterion x format matrix is expert surface that every first-time user was made to scroll
          past before they could start a basic scan. `open` follows the Custom profile, so choosing
          Custom reveals it without a second click and choosing a preset never does. */}
      <details open={profile === 'custom'}
               style={{ borderTop: '1px solid var(--line)', marginTop: 8 }}>
        <summary style={{ padding: '8px 0', cursor: 'pointer', fontSize: 13, userSelect: 'none' }}>
          View or customize criteria
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

          {/* ── Readiness legend ────────────────────────────────────────────────
              What each cell state means, so a tester knows what is theirs to try. Keyed on the
              CI-locked assessment axis (capability.js): 🟢 automated, 🟡 review required, and
              a criterion×format ACP can't assess yet is greyed and can't be selected. */}
          <div role="note" aria-label="Readiness legend"
               style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', alignItems: 'center',
                        fontSize: 11.5, color: 'var(--muted)', margin: '0 2px 8px' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 3, border: '2px solid #3B6D11', display: 'inline-block' }} />
              Automated — ACP evaluates this combination
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 3, border: '2px solid #B45309', display: 'inline-block' }} />
              Review required — ACP detects evidence, a person decides
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span aria-hidden="true" style={{ color: 'var(--muted)', opacity: 0.6 }}>◌</span>
              Not currently supported — greyed, can't be selected
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span aria-hidden="true" className="muted" style={{ opacity: 0.45 }}>·</span>
              Not supported for that format
            </span>
          </div>

          {/* ── The matrix (sticky header + criterion column) ───────────────── */}
          <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 360,
                        border: '1px solid var(--line)', borderRadius: 8 }}>
            <table style={{ borderCollapse: 'separate', borderSpacing: 0, fontSize: 13, width: '100%' }}>
              <caption className="sronly">
                Scan scope: tick each criterion and format this scan assesses. Rows are grouped by
                WCAG principle. Pairs ACP cannot assess yet are marked Not ready and cannot be
                selected; pairs the engine has no verdict for are marked Not supported.
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
                        const rowNotReady = row.ready.length === 0   // no format ACP can assess yet
                        return (
                          <tr key={row.sc}>
                            <th scope="row" style={{ ...STICKY_LEFT, opacity: rowNotReady ? 0.55 : 1 }}>
                              <b>{row.sc}</b> {row.name} <span className="muted">· {row.level}</span>
                              {rowNotReady && (
                                <span title="No format ACP can assess for this criterion yet"
                                      style={{ marginLeft: 6, fontSize: 10.5, fontWeight: 600, letterSpacing: '.02em',
                                               color: 'var(--muted)', border: '1px solid var(--line)',
                                               borderRadius: 999, padding: '0 6px' }}>NOT READY</span>
                              )}
                            </th>
                            {SCOPE_FORMATS.map((f) => {
                              // Three states: not supported (engine has no verdict) · not ready
                              // (engine reaches it but ACP can't yet ASSESS it — greyed, disabled) ·
                              // ready (selectable checkbox, tinted by assessment lane).
                              if (!row.formats.includes(f)) {
                                return (
                                  <td key={f} title="Not supported for this format"
                                      style={{ ...CELL, background: 'var(--surface)' }}>
                                    <span aria-hidden="true" className="muted" style={{ opacity: 0.45 }}>·</span>
                                    <span className="sronly">{`${FMT_LABEL[f]}: Not supported for ${row.sc}`}</span>
                                  </td>
                                )
                              }
                              if (!isReady(row.sc, f)) {
                                return (
                                  <td key={f} title={`Not currently supported — ${row.sc} on ${FMT_LABEL[f]} is not evaluated in this release`}
                                      style={{ ...CELL, background: 'var(--surface)', opacity: 0.9 }}>
                                    <span aria-hidden="true" style={{ color: 'var(--muted)', opacity: 0.6, fontSize: 12 }}>◌</span>
                                    <span className="sronly">{`${FMT_LABEL[f]}: not currently supported for ${row.sc} — cannot be selected`}</span>
                                  </td>
                                )
                              }
                              const on = has(row.sc, f)
                              const lane = laneOf(row.sc, f)        // 'auto' | 'review'
                              const accent = lane === 'auto' ? '#3B6D11' : '#B45309'
                              return (
                                <td key={f} title={lane === 'auto'
                                      ? `Automated — ACP evaluates ${row.sc} for ${FMT_LABEL[f]}`
                                      : `Ready — ACP detects ${row.sc} for ${FMT_LABEL[f]}, you confirm`}
                                    style={{ ...CELL, background: on ? '#F3EEFC' : 'transparent' }}>
                                  <input type="checkbox" checked={on} disabled={busy || !canEdit}
                                         onChange={() => toggle(row.sc, f)}
                                         style={{ accentColor: accent }}
                                         aria-label={`${row.sc} ${row.name}, ${FMT_LABEL[f]} — ${lane === 'auto' ? 'ready, certifies' : 'ready, detect and confirm'}`} />
                                </td>
                              )
                            })}
                            <td style={CELL}>
                              <button type="button" role="checkbox" aria-checked={ariaChecked(rst)}
                                      disabled={busy || !canEdit || rowNotReady} onClick={() => toggleRow(row)}
                                      aria-label={`Select every format for ${row.sc} ${row.name}`}
                                      style={{ ...selMini(rst), ...(rowNotReady ? { opacity: 0.4, cursor: 'not-allowed' } : {}) }}>{rst === 'all' ? 'None' : 'All'}</button>
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

      </>)}

      {/* ── 3. Review ───────────────────────────────────────────────────────── */}
      {/* A scope CONTRACT: what is about to be covered, stated once, in the order it was decided.
          Still no ESTIMATED file count. A number invented here would be the one thing on this
          screen a reader would most reasonably trust, and under ADR 0020 a Discover run IS the
          listing — so an estimate is not a cheap preview of an expensive operation, it is very
          nearly the operation run twice, producing a SECOND number for the same estate at a
          different moment under a different cap. Two numbers that can disagree, both correct, is
          the 2026-07-30 defect (scanScope.js).
          What IS shown is a number that was actually measured: what THIS EXACT SCOPE covered the
          last time it ran, matched on the whole frozen boundary and captioned with its date. When
          no such run exists the line says so and stops — inventing a figure for precisely the case
          with no evidence behind it would be the least checkable number on the screen. */}
      {showStartButton && step === 3 && (
        <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: '12px 14px' }}>
          <div style={{ fontSize: 13, fontWeight: 650, marginBottom: 8 }}>Ready to scan</div>
          <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 14px',
                       margin: 0, fontSize: 12.5 }}>
            {locKey && (
              <>
                <dt className="muted">Drive locations</dt>
                <dd style={{ margin: 0 }}>
                  {folders.length === 0
                    ? 'Entire connected source'
                    : `${folders.length} folder${folders.length === 1 ? '' : 's'}, including subfolders`}
                </dd>
              </>
            )}
            {excluded.length > 0 && (
              <>
                <dt className="muted">Excluded</dt>
                <dd style={{ margin: 0 }}>
                  {excluded.map((f) => f.name).join(', ')}
                </dd>
              </>
            )}
            <dt className="muted">Formats</dt>
            <dd style={{ margin: 0 }}>
              {activeFormats.length ? activeFormats.map((f) => FMT_LABEL[f]).join(', ') : 'None selected'}
            </dd>
            <dt className="muted">Criteria</dt>
            <dd style={{ margin: 0 }}>{profileLabel}</dd>
            <dt className="muted">Executable checks</dt>
            <dd style={{ margin: 0 }}>
              {chosen} supported combination{chosen === 1 ? '' : 's'}
              {unsupported > 0 && (
                <span className="muted"> · {unsupported} unsupported will not be evaluated</span>
              )}
            </dd>
          </dl>
          {/* Below the contract, not inside it: this is evidence ABOUT the scope, not part of it.
              `aria-live` because it changes as the scope does, and a count whose boundary silently
              moved underneath it is the failure mode this whole screen is built against. */}
          <div role="status" aria-live="polite" className="muted"
               style={{ fontSize: 12, marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line)' }}>
            {coverageSentence(lastRun, lastRun ? whenLabel(lastRun.at) : '')}
          </div>
        </div>
      )}

      {/* ── 5/7. Footer ─────────────────────────────────────────────────────── */}
      {showStartButton ? (
        <>
          {/* THE CRITERIA WRITE-BACK, now symmetric with the folder one directly above it.
              It used to read "Remember these selections for my next scan", be ticked by DEFAULT,
              and appear on every run. Three things were wrong with that. It is not "my next scan"
              — `scan_scope` is the platform default and applies to everyone. Being on by default
              made a one-off narrowing into permanent configuration unless somebody noticed a
              ticked box, which is the exact failure the folder half is careful about, with the
              default the wrong way round. And a checkbox that is always there is a checkbox people
              tick without reading; appearing only once the run actually DIFFERS from what is
              stored makes its absence a signal too.
              Hidden for a non-owner rather than shown and ignored: PUT /settings is admin-only, so
              offering it to a read-only account promises a write that 403s. */}
          {step === 3 && dirty && canEdit && (
            <div style={{ margin: '12px 0 0' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <input type="checkbox" checked={remember} disabled={busy}
                       onChange={(e) => setRemember(e.target.checked)} />
                Also save these criteria as the platform default
              </label>
              <div className="muted" style={{ fontSize: 11.5, marginLeft: 24 }}>
                Applies to every later scan, for everyone. This run uses them either way.
              </div>
            </div>
          )}

          {/* Sticky footer: the running scope stays visible while the folder tree or the criterion
              matrix scrolls, so the primary action never leaves the screen and the summary never
              stops answering "what am I about to run?". */}
          <div style={{ position: 'sticky', bottom: 0, background: 'var(--surface)',
                        borderTop: '1px solid var(--line)', marginTop: 12, paddingTop: 10,
                        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="muted" style={{ fontSize: 12.5 }}>{footerSummary}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              <button className="ghost small" type="button" disabled={busy}
                      onClick={() => (step === 1 ? onStartScan?.({ cancel: true }) : setStep(step - 1))}>
                {step === 1 ? 'Cancel' : '← Back'}
              </button>
              {step < 3 ? (
                // Blocked rather than silently reinterpreted. An enabled Continue over an empty
                // "Specific folders" selection authorises the whole estate — the run the footer
                // and the scope panel both used to describe as "Entire source" while the user was
                // looking at a screen that said they were narrowing.
                <button type="button" disabled={busy || !!blocked} title={blocked || undefined}
                        onClick={() => setStep(step + 1)}>Continue →</button>
              ) : (
                <button type="button" disabled={busy || !!blocked} title={blocked || undefined}
                        onClick={startScan}>
                  {busy ? 'Saving…' : 'Start scan →'}
                </button>
              )}
            </span>
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
