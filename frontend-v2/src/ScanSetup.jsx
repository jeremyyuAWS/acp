import { useState, useEffect } from 'react'
import { getSettings, updateSettings } from './api.js'
import { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'
import { TRACKED_17 } from './ruleDetails.js'
import { parseStoredScope } from './ScanScope.jsx'
import { CAPABILITY_FALLBACK, modeFor } from './capability.js'
import { saveScopedFileTypes } from './FileTypeConfig.jsx'

// The pre-scan setup: what ACP should inspect, decided before anything is scanned.
//
// ONE EDITOR, TWO AXES, ONE WRITE — and that is the point of this component existing rather
// than putting the two existing panels side by side.
//
// `scan_scope` is a single map of criterion → formats. Two controls already write it and
// neither knows about the other: FileTypeConfig saves `scopeForFormats(allowed)`, which is
// EVERY criterion restricted to the ticked formats, so saving it silently discards a criterion
// narrowing; ScanScope saves its per-criterion selection and pays no attention to the file-type
// toggles. Whichever was touched last wins, and nothing says so.
//
// On separate screens that is a latent bug. On one screen — which is what "put the file types
// and the SCs on the first page" means — it becomes an immediate contradiction: tick a format,
// watch the criteria you just chose come back. So this screen owns both axes and derives the
// map once, at save, as `criteria × formats`. It cannot disagree with itself because there is
// only one selection.
//
// The two existing panels are untouched: Settings keeps them for the platform-admin path, and
// this does not change what either does. Reconciling all three is the "two filters" backlog
// item, and it wants a decision about which surface is authoritative, not a bigger component.
//
// STEP 2 IS PROFILE-FIRST. The 17 criteria are the expert surface; most operators want one of
// two intents — "the recommended set" or "only what runs without a person" — and should reach a
// correct scope in one click. So the checks step leads with three profiles (Recommended,
// Automated only, Custom) and only unfolds the per-criterion list when Custom is chosen. Every
// bulk affordance below Custom (select all, clear, per-principle tri-state, the lane filter) is
// a shortcut into the same one `criteria` Set the profiles write — there is still one selection.

// Derived from the criterion number, not typed out: the four WCAG principles are the first digit,
// and a hand-written map would be a fifth list to keep in step with the 17.
const PRINCIPLES = [
  ['1', 'Perceivable'],
  ['2', 'Operable'],
  ['3', 'Understandable'],
  ['4', 'Robust'],
]

// Only the criteria this product tracks, intersected with what the engine can reach a verdict
// on — the same expression ScanScope uses (#168), for the same reason: filtered so it can only
// narrow, never offer a checkbox with nothing behind it.
const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
const CORE = 'acp-core-17'

const FORMAT_LABEL = { docx: 'Word', pdf: 'PDF', pptx: 'PowerPoint', xlsx: 'Excel' }

// What ACP can do for a criterion on the formats currently ticked.
//
// Reported as the SET, not the best of them. A criterion is often automated on one format and
// human-only on another, and collapsing that to the strongest answer would tell an operator ACP
// can fix something it cannot — the overstatement this indicator exists to prevent.
function laneFor(sc, formats) {
  const modes = new Set()
  for (const f of formats) {
    if (OFFERED.find((r) => r.sc === sc)?.formats.includes(f)) {
      modes.add(modeFor(CAPABILITY_FALLBACK, f, sc))
    }
  }
  if (!modes.size) return null
  if (modes.size > 1) return { key: 'mixed', label: 'varies by format' }
  const only = [...modes][0]
  return { key: only, label: only === 'auto' ? 'Automated'
    : only === 'assisted' ? 'AI-assisted' : 'Human review' }
}

const LANE_TONE = {
  auto: ['#E7F0DC', '#3B6D11'],
  assisted: ['#EEF2FB', '#2B4A7E'],
  human: ['#FBF1DF', '#854F0B'],
  mixed: ['#EFEDEA', '#5F5E5A'],
}

// The lane filter chips, in a fixed order so the row does not reshuffle as counts change.
const LANE_ORDER = [
  ['auto', 'Automated'],
  ['assisted', 'AI-assisted'],
  ['human', 'Human review'],
  ['mixed', 'Varies'],
]

// A criterion is "available" when at least one ticked format offers a lane for it. Everything the
// bulk controls, the counts and the rendered rows operate on is this format-filtered set — so
// with Word alone selected the screen talks about 15 checks, not the 17 that exist across all
// four formats, and no row shows a criterion the current file types can't reach.
const availableRows = (formats) => OFFERED.filter((r) => r.formats.some((f) => formats.has(f)))

// The deterministic-first subset for the selected formats: every pair that would run is
// automated. Strict on purpose — a criterion automated on Word but human-reviewed on PDF is NOT
// in "Automated only" when both formats are ticked, because the scan it names would still route
// something to a person. Recomputed when the formats change (see toggleFormat), so the profile
// keeps meaning what its label says.
const autoOnlyCriteria = (formats) => new Set(
  availableRows(formats)
    .filter((r) => r.formats.filter((f) => formats.has(f))
      .every((f) => modeFor(CAPABILITY_FALLBACK, f, r.sc) === 'auto'))
    .map((r) => r.sc),
)

export default function ScanSetup({ onScan, busy, hasDriveToken, hasSPToken, onFileTypeChange }) {
  // .docx ONLY by default, not all four formats.
  //
  // A deliberate product choice, not a technical one: .docx is where the engine is strongest.
  // Of the Core 17, fifteen criteria have a docx lane and four can certify a PASS
  // (1.3.1, 1.4.3, 2.4.2, 3.1.1); remediation applies nine fixes across seven criteria on a
  // real document. The other formats are genuinely thinner — pdf cannot be assessed at all
  // without the external ACP_PDF_ENGINE, and 2.1.1 exists only on pptx.
  //
  // Defaulting to everything meant a first scan inventoried an estate the product could say
  // least about, and the weakest formats set the tone. Starting narrow makes the first result
  // the strongest one; widening is one click, and the chips show the other three ready to add.
  const [formats, setFormats] = useState(() => new Set(['docx']))
  const [criteria, setCriteria] = useState(() => new Set(Object.keys(SCOPE_PRESETS[CORE] || {})))
  // 'recommended' (all supported) · 'auto' (deterministic-first) · 'custom' (hand-picked). Any
  // per-criterion edit drops to 'custom', because the selection no longer matches a named intent.
  const [profile, setProfile] = useState('recommended')
  const [open, setOpen] = useState(null)         // which principle group is expanded
  const [laneFilter, setLaneFilter] = useState(null)   // view-only: which lane's rows are shown
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [loaded, setLoaded] = useState(false)
  const custom = profile === 'custom'

  // Read the saved scope back so this screen reflects the platform, not a fresh default. An
  // unrestricted platform reads as "everything", which is what Core 17 + all formats means here.
  useEffect(() => {
    let live = true
    getSettings()
      .then((st) => {
        if (!live) return
        const stored = parseStoredScope(st?.scan_scope || '')
        if (stored) {
          setCriteria(new Set(Object.keys(stored)))
          setFormats(new Set(Object.values(stored).flatMap((f) => [...f])))
          setProfile('custom')
        }
      })
      .catch(() => {})
      .finally(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [])

  // The map that gets written: every ticked criterion, on the ticked formats the engine can
  // actually judge it on. Derived at save from the generated universe, so a pair the engine
  // cannot reach can never enter the scope however the boxes are ticked.
  const scope = {}
  for (const row of OFFERED) {
    if (!criteria.has(row.sc)) continue
    const fmts = row.formats.filter((f) => formats.has(f))
    if (fmts.length) scope[row.sc] = fmts
  }
  const pairCount = Object.values(scope).reduce((n, f) => n + f.length, 0)
  const scCount = Object.keys(scope).length

  // Lane tallies. `runLanes` is the honest "what will this scan actually do" — over the SELECTED
  // criteria, since that is what runs. `availLanes` is over everything selectable on these
  // formats, and powers the filter chips ("6 automated checks you could pick"). They differ, and
  // the labels say which is which so the two numbers are not read as one.
  const tally = (scs) => {
    const t = { auto: 0, assisted: 0, human: 0, mixed: 0 }
    for (const sc of scs) { const l = laneFor(sc, formats); if (l) t[l.key] += 1 }
    return t
  }
  const runLanes = tally(Object.keys(scope))
  const availRows = availableRows(formats)
  const availLanes = tally(availRows.map((r) => r.sc))

  const laneSentence = (t) => LANE_ORDER
    .filter(([k]) => t[k])
    .map(([k, label]) => `${t[k]} ${k === 'mixed' ? 'vary by format' : label.toLowerCase()}`)
    .join(' · ')

  const toggleFormat = (f) => {
    const n = new Set(formats)
    n.has(f) ? n.delete(f) : n.add(f)
    setFormats(n)
    // Keep a derived profile honest when its inputs move. 'auto' names a set that depends on the
    // formats, so recompute it; 'recommended' is all-17 regardless of format and 'custom' is the
    // operator's own list, so neither is touched here.
    if (profile === 'auto') setCriteria(autoOnlyCriteria(n))
  }

  const toggleSc = (sc) => { setProfile('custom'); setCriteria((s) => {
    const n = new Set(s); n.has(sc) ? n.delete(sc) : n.add(sc); return n
  }) }

  // Bulk edits all write the one `criteria` Set and drop to 'custom'. They operate on the
  // format-available rows only: selecting a criterion with no lane on the ticked formats would
  // be a no-op at save (the scope derivation drops it), so offering it would be a lie.
  const setMany = (rows, on) => { setProfile('custom'); setCriteria((s) => {
    const n = new Set(s); for (const r of rows) on ? n.add(r.sc) : n.delete(r.sc); return n
  }) }
  const selectAll = () => setMany(availRows, true)
  const clearAll = () => setMany(availRows, false)
  const toggleCategory = (digit) => {
    const rows = availRows.filter((r) => r.sc.startsWith(digit + '.'))
    setMany(rows, !rows.every((r) => criteria.has(r.sc)))
  }

  // Recommended = the Core 17. Only the criteria move; the file types are Step 1's decision and
  // are left exactly as the operator set them.
  const useRecommended = () => {
    setCriteria(new Set(Object.keys(SCOPE_PRESETS[CORE] || {}))); setProfile('recommended'); setMsg('')
  }
  const useAutoOnly = () => {
    setCriteria(autoOnlyCriteria(formats)); setProfile('auto'); setMsg('')
  }
  const startCustom = () => { setProfile('custom'); setLaneFilter(null) }

  const save = async () => {
    // An empty selection stored literally would read as NO restriction on the backend —
    // "assess nothing" saved as "assess everything", silently. Refused with a reason, the same
    // way ScanScope refuses it.
    if (!scCount) { setMsg('Pick at least one check and one file type — an empty scope would assess everything.'); return false }
    setSaving(true); setMsg('')
    try {
      await updateSettings({ scan_scope: JSON.stringify(scope) })
      // BOTH stores, because one fact is kept in two places. `scan_scope` above decides what is
      // ASSESSED; the localStorage config decides what Discover LISTS (Discover.jsx filters on
      // `fileTypeConfig[f.type] !== false`). Writing only the first is what made unticking PDF
      // here scope the assessment while every PDF stayed in the inventory — the file types were
      // honoured everywhere except the screen the operator looks at next.
      //
      // saveScopedFileTypes MERGES the four engine-scoped formats into the stored config; html,
      // video, audio and custom extensions have no scan_scope axis and are left untouched.
      onFileTypeChange?.(saveScopedFileTypes(formats))
      setMsg(`✓ Saved · ${scCount} checks on ${formats.size} file type${formats.size === 1 ? '' : 's'}`)
      return true
    } catch (e) {
      setMsg(e?.message || 'Could not save the scan scope.')
      return false
    } finally { setSaving(false) }
  }

  // Scan only if the scope actually persisted. save() reports its failure into a status message
  // rather than throwing, so awaiting it and calling onScan regardless started a scan whose
  // scope had NOT been written — it would run against whatever was stored before, while this
  // screen displayed the selection the operator had just made. The scope is the entire purpose
  // of this screen, so a scan without it is worse than no scan: it produces a result that looks
  // scoped and is not. Caught by scanSetupDom.test.jsx, which renders the failure path; the
  // source-text tests could not see it.
  const scanAndSave = async (source) => { if (await save()) onScan(source) }

  const groups = PRINCIPLES.map(([digit, name]) => {
    const rows = availRows.filter((r) => r.sc.startsWith(digit + '.'))
    return { digit, name, rows, on: rows.filter((r) => criteria.has(r.sc)).length }
  }).filter((g) => g.rows.length)

  const laneMatch = (r) => !laneFilter || laneFor(r.sc, formats)?.key === laneFilter
  const fmtList = [...formats].map((f) => FORMAT_LABEL[f] || f.toUpperCase())
  const PROFILE_DESC = {
    // Keep the full "WCAG 2.1 AA — 17 ACP-supported checks" phrase: ACP tracks 17 criteria, and
    // "WCAG 2.1 AA" unqualified would imply the whole standard.
    recommended: 'WCAG 2.1 AA — 17 ACP-supported checks. The balanced default: deterministic, AI-assisted and human-review checks together.',
    auto: 'Only the checks ACP decides deterministically on the selected file types — a fast, fully automated scan with nothing routed to a person.',
    custom: 'Choose individual success criteria below.',
  }

  return (
    <div className="scansetup">
      <h3 className="setuptitle">Configure your accessibility scan</h3>
      <p className="muted setupsub">
        Choose what ACP should inspect. This applies to Discover, Assess and Remediate —
        configure once, and every stage reports against it.
      </p>

      {/* ① FILE TYPES — four, not five. `html` is deliberately absent: SCOPE_FORMATS is the
          generated document set, and the universe generator excludes html because this is a
          document engagement. A fifth checkbox would change nothing when ticked. */}
      <div className="setupstep">
        <div className="setupstep-h"><span className="setupstep-n">1</span> File types</div>
        <div className="setupchips">
          {SCOPE_FORMATS.map((f) => (
            <button key={f} className={formats.has(f) ? 'setupchip on' : 'setupchip'}
                    aria-pressed={formats.has(f)} onClick={() => toggleFormat(f)}>
              {formats.has(f) ? '✓ ' : ''}{FORMAT_LABEL[f] || f.toUpperCase()}
              <span className="muted"> · {f.toUpperCase()}</span>
            </button>
          ))}
        </div>
        <div className="muted setupcount">{formats.size} of {SCOPE_FORMATS.length} file types selected</div>
      </div>

      {/* ② CHECKS — profile-first. The 17 unfold only under Custom. */}
      <div className="setupstep">
        <div className="setupstep-h">
          <span className="setupstep-n">2</span> What should ACP check?
          <span className="muted setuphint"> · WCAG 2.1 AA success criteria</span>
        </div>

        <div className="setupchips" role="radiogroup" aria-label="Scan profile">
          <button className={profile === 'recommended' ? 'setupchip on' : 'setupchip'}
                  role="radio" aria-checked={profile === 'recommended'} onClick={useRecommended}>
            {profile === 'recommended' ? '✓ ' : ''}Recommended
          </button>
          <button className={profile === 'auto' ? 'setupchip on' : 'setupchip'}
                  role="radio" aria-checked={profile === 'auto'} onClick={useAutoOnly}>
            {profile === 'auto' ? '✓ ' : ''}Automated only
          </button>
          <button className={custom ? 'setupchip on' : 'setupchip'}
                  role="radio" aria-checked={custom} onClick={startCustom}>Custom</button>
        </div>
        <p className="muted setupdesc">{PROFILE_DESC[profile]}</p>

        {custom && (
          <div className="setupcustom">
            <div className="setupbulk">
              <div className="setupbulk-sel">
                {scCount < availRows.length && (
                  <button className="setuplink" onClick={selectAll}>Select all {availRows.length}</button>
                )}
                {scCount > 0 && <button className="setuplink" onClick={clearAll}>Clear all</button>}
              </div>
              {/* The capability pills double as a view filter — the fastest answer to
                  "which checks need a person?" is one click on Human review. */}
              <div className="setupfilter" role="group" aria-label="Filter by execution">
                <button className={!laneFilter ? 'setupfchip on' : 'setupfchip'}
                        aria-pressed={!laneFilter} onClick={() => setLaneFilter(null)}>
                  All {availRows.length}
                </button>
                {LANE_ORDER.filter(([k]) => availLanes[k]).map(([k, label]) => (
                  <button key={k} className={laneFilter === k ? 'setupfchip on' : 'setupfchip'}
                          aria-pressed={laneFilter === k} onClick={() => setLaneFilter(laneFilter === k ? null : k)}
                          style={laneFilter === k ? { background: LANE_TONE[k][0], color: LANE_TONE[k][1], borderColor: LANE_TONE[k][1] } : null}>
                    {label} {availLanes[k]}
                  </button>
                ))}
              </div>
            </div>

            {groups.map((g) => {
              const shown = g.rows.filter(laneMatch)
              if (!shown.length) return null
              const allOn = g.on === g.rows.length
              const someOn = g.on > 0 && !allOn
              return (
                <details key={g.digit} className="setupgroup" open={open === g.digit}>
                  <summary onClick={(e) => { e.preventDefault(); setOpen(open === g.digit ? null : g.digit) }}>
                    <input type="checkbox" className="setupcatbox"
                           ref={(el) => { if (el) el.indeterminate = someOn }}
                           checked={allOn} onChange={() => toggleCategory(g.digit)}
                           onClick={(e) => e.stopPropagation()}
                           aria-label={`Select all ${g.name}`} />
                    <b>{g.name}</b>
                    <span className="muted"> · {g.on} of {g.rows.length} selected</span>
                  </summary>
                  {shown.map((r) => {
                    const lane = laneFor(r.sc, formats)
                    const tone = lane ? LANE_TONE[lane.key] : null
                    // The formats this criterion is judged on, NARROWED to the ticked file types —
                    // so a Word-only scan shows "DOCX", not "DOCX · PDF · PPTX · XLSX" the operator
                    // then has to reconcile against Step 1. Rows with no ticked-format lane are not
                    // rendered at all (see availRows), so this list is never empty.
                    const shownFormats = r.formats.filter((f) => formats.has(f))
                    return (
                      <label key={r.sc} className="setuprow">
                        <input type="checkbox" checked={criteria.has(r.sc)} onChange={() => toggleSc(r.sc)}
                               aria-label={`${r.sc} ${r.name}`} />
                        <span className="setuprow-sc"><b>{r.sc}</b> {r.name}</span>
                        <span className="muted setuprow-f">{shownFormats.map((f) => f.toUpperCase()).join(' · ')}</span>
                        {lane && (
                          <span className="setuplane" style={{ background: tone[0], color: tone[1] }}
                                title="What ACP can do for this criterion on the file types you selected">
                            {lane.label}
                          </span>
                        )}
                      </label>
                    )
                  })}
                </details>
              )
            })}
          </div>
        )}

        <div className="setupcount setuprun">
          <b>{scCount} check{scCount === 1 ? '' : 's'} will run</b>
          {laneSentence(runLanes) && <span className="muted"> · {laneSentence(runLanes)}</span>}
        </div>
        <div className="muted setupcount setupcount-sub">
          {scCount} of {OFFERED.length} supported checks selected
          {/* Pairs, not just criteria. "17 checks" over four file types reads as 68; the real
              number is smaller because the engine has no lane for some combinations. */}
          {' · '}{pairCount} criterion × format pairs
        </div>
      </div>

      {/* ③ SOURCE + the action */}
      <div className="setupstep">
        <div className="setupstep-h"><span className="setupstep-n">3</span> Source</div>
        <div className="muted setupcount">
          {hasDriveToken ? 'Google Drive · connected' : 'No source connected — you can still try the sample corpus'}
          {hasSPToken ? ' · SharePoint / OneDrive · connected' : ''}
        </div>
      </div>

      {/* A last decision-oriented read before the action: what runs, on what, from where. */}
      <div className="setupsummary" role="status">
        <b>Scan configuration</b>
        <div className="setupsummary-grid">
          <span><span className="muted">Files</span> {fmtList.join(' · ') || 'none'}</span>
          <span><span className="muted">Checks</span> {scCount} of {availRows.length}{profile !== 'custom' ? ` (${profile === 'auto' ? 'Automated only' : 'Recommended'})` : ''}</span>
          <span><span className="muted">Execution</span> {laneSentence(runLanes) || '—'}</span>
          <span><span className="muted">Source</span> {hasDriveToken ? 'Google Drive' : 'Sample corpus'}</span>
        </div>
      </div>

      <div className="emptyactions">
        {hasDriveToken
          ? <button disabled={busy || saving || !scCount} onClick={() => scanAndSave('drive')}>
              {busy ? 'scanning…' : '→ Save & scan Google Drive'}</button>
          : <button disabled={busy || saving || !scCount} onClick={() => scanAndSave('local')}>
              {busy ? 'scanning…' : '→ Save & try the sample corpus'}</button>}
        {hasDriveToken && (
          <button className="ghost" disabled={busy || saving} onClick={() => scanAndSave('local')}>
            Try sample corpus
          </button>
        )}
        <button className="ghost" disabled={saving || !loaded} onClick={save}>
          {saving ? 'Saving…' : 'Save scope only'}
        </button>
      </div>
      {msg && <p className="muted setupmsg" role="status" aria-live="polite">{msg}</p>}
    </div>
  )
}
