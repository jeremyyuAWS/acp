import { useState, useEffect } from 'react'
import { getSettings, updateSettings } from './api.js'
import { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } from './scopePresets.js'
import { TRACKED_17 } from './ruleDetails.js'
import { parseStoredScope } from './ScanScope.jsx'
import { CAPABILITY_FALLBACK, modeFor } from './capability.js'

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

export default function ScanSetup({ onScan, busy, hasDriveToken, hasSPToken }) {
  const [formats, setFormats] = useState(() => new Set(SCOPE_FORMATS))
  const [criteria, setCriteria] = useState(() => new Set(Object.keys(SCOPE_PRESETS[CORE] || {})))
  const [custom, setCustom] = useState(false)
  const [open, setOpen] = useState(null)         // which principle group is expanded
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [loaded, setLoaded] = useState(false)

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
          setCustom(true)
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

  const toggleFormat = (f) => setFormats((s) => {
    const n = new Set(s); n.has(f) ? n.delete(f) : n.add(f); return n
  })
  const toggleSc = (sc) => { setCustom(true); setCriteria((s) => {
    const n = new Set(s); n.has(sc) ? n.delete(sc) : n.add(sc); return n
  }) }
  const usePreset = () => {
    setCriteria(new Set(Object.keys(SCOPE_PRESETS[CORE] || {})))
    setFormats(new Set(SCOPE_FORMATS)); setCustom(false); setMsg('')
  }

  const save = async () => {
    // An empty selection stored literally would read as NO restriction on the backend —
    // "assess nothing" saved as "assess everything", silently. Refused with a reason, the same
    // way ScanScope refuses it.
    if (!scCount) { setMsg('Pick at least one check and one file type — an empty scope would assess everything.'); return }
    setSaving(true); setMsg('')
    try {
      await updateSettings({ scan_scope: JSON.stringify(scope) })
      setMsg(`✓ Saved · ${scCount} checks on ${formats.size} file type${formats.size === 1 ? '' : 's'}`)
    } catch (e) {
      setMsg(e?.message || 'Could not save the scan scope.')
    } finally { setSaving(false) }
  }

  const scanAndSave = async (source) => { await save(); onScan(source) }

  const groups = PRINCIPLES.map(([digit, name]) => {
    const rows = OFFERED.filter((r) => r.sc.startsWith(digit + '.'))
    return { digit, name, rows, on: rows.filter((r) => criteria.has(r.sc)).length }
  }).filter((g) => g.rows.length)

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

      {/* ② CHECKS — preset by default; the 17 are one click away, not a wall. */}
      <div className="setupstep">
        <div className="setupstep-h"><span className="setupstep-n">2</span> Accessibility checks</div>
        <div className="setupchips">
          <button className={!custom ? 'setupchip on' : 'setupchip'} aria-pressed={!custom}
                  onClick={usePreset}>
            {!custom ? '✓ ' : ''}WCAG 2.1 AA — 17 ACP-supported checks
          </button>
          <button className={custom ? 'setupchip on' : 'setupchip'} aria-pressed={custom}
                  onClick={() => setCustom(true)}>Custom</button>
        </div>

        {custom && groups.map((g) => (
          <details key={g.digit} className="setupgroup" open={open === g.digit}
                   onToggle={(e) => setOpen(e.currentTarget.open ? g.digit : null)}>
            <summary>
              <b>{g.name}</b>
              <span className="muted"> · {g.on} of {g.rows.length} selected</span>
            </summary>
            {g.rows.map((r) => {
              const lane = laneFor(r.sc, formats)
              const tone = lane ? LANE_TONE[lane.key] : null
              return (
                <label key={r.sc} className="setuprow">
                  <input type="checkbox" checked={criteria.has(r.sc)} onChange={() => toggleSc(r.sc)}
                         aria-label={`${r.sc} ${r.name}`} />
                  <span className="setuprow-sc"><b>{r.sc}</b> {r.name}</span>
                  {/* The formats this criterion is actually judged on — 2.1.1 is pptx-only,
                      2.4.3 is pdf+pptx. A row that showed no formats would imply all four. */}
                  <span className="muted setuprow-f">{r.formats.map((f) => f.toUpperCase()).join(' · ')}</span>
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
        ))}

        <div className="muted setupcount">
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

      <div className="setupsummary" role="status">
        <b>Scan scope</b> · {[...formats].map((f) => f.toUpperCase()).join(' + ') || 'no file types'}
        {' · '}{scCount} accessibility check{scCount === 1 ? '' : 's'} ({pairCount} pairs)
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
