import { useState, useEffect, useRef } from 'react'
import { getSettings, updateSettings, fetchCodeset, fetchEligibility } from './api.js'
import { SCOPE_FORMATS } from './scopePresets.js'
import { parseStoredScope } from './ScanScope.jsx'
import ScopeImpact from './ScopeImpact.jsx'

// The Assess-time scope picker (Discover/Assess PRD §4.4).
//
// WHY THIS LIVES IN ASSESS, AND WHY IT IS THE SINGLE AUTHORITY FOR THE FORMAT AXIS.
// `scan_scope` is one map of criterion → formats. Document-type (the format axis) used to be
// written by TWO pre-scan controls that did not know about each other — ScanSetup Step 1 and the
// Settings FileTypeConfig panel — plus a localStorage view-filter Discover read. Last touched won,
// silently. This screen resolves that: the doc-type picker here is now the ONE per-engagement
// control for the format axis, and ScanSetup no longer offers file types at all. Discover shows the
// whole discovered estate; what to ASSESS (which doc types, which criteria) is decided here, right
// before the run, where the eligible-file count can be shown against it.
//
// TWO AXES, ONE WRITE. The saved map is derived once as `codes × doc-types` — every selected WCAG
// code, on the selected document formats it actually has an assessment lane for. It cannot disagree
// with itself because there is one selection, and a pair the catalog has no lane for can never
// enter the scope however the boxes are ticked.

const FORMAT_LABEL = { docx: 'Word', pdf: 'PDF', pptx: 'PowerPoint', xlsx: 'Excel' }

// The eligible count is fetched live as the selection changes; a short debounce keeps a fast
// clicker from firing a request per checkbox while still feeling immediate.
const DEBOUNCE_MS = 300

export default function AssessScope({ onSaved }) {
  const [codeset, setCodeset] = useState([])          // [{code, name, formats:[...]}] — the Core 17
  const [codes, setCodes] = useState(() => new Set()) // selected WCAG codes (criterion axis)
  const [formats, setFormats] = useState(() => new Set(SCOPE_FORMATS)) // selected doc-types (format axis)
  const [elig, setElig] = useState(null)              // {discovered, eligible, by_format, formats, codes}
  const [eligLoading, setEligLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const debounce = useRef(null)

  // Load the catalog and the stored scope together, so the picker opens reflecting the platform's
  // current selection rather than a fresh default. A stored scope narrows both axes; no stored
  // scope reads as "everything" — all 17 codes, all four formats.
  useEffect(() => {
    let live = true
    Promise.all([
      fetchCodeset().catch(() => []),
      getSettings().then((s) => parseStoredScope(s?.scan_scope || '')).catch(() => null),
    ]).then(([cat, stored]) => {
      if (!live) return
      const rows = Array.isArray(cat) ? cat : []
      setCodeset(rows)
      if (stored && Object.keys(stored).length) {
        setCodes(new Set(Object.keys(stored)))
        setFormats(new Set(Object.values(stored).flatMap((f) => [...f])))
      } else {
        setCodes(new Set(rows.map((r) => r.code)))
        setFormats(new Set(SCOPE_FORMATS))
      }
    }).finally(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [])

  // Live eligible-file count, debounced, keyed on the selected codes. Read-only — it never starts a
  // scan, so calling it on every selection change is safe.
  const codesKey = [...codes].sort().join(',')
  useEffect(() => {
    if (!loaded) return
    clearTimeout(debounce.current)
    setEligLoading(true)
    debounce.current = setTimeout(() => {
      fetchEligibility([...codes])
        .then((r) => setElig(r))
        .catch(() => setElig(null))
        .finally(() => setEligLoading(false))
    }, DEBOUNCE_MS)
    return () => clearTimeout(debounce.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codesKey, loaded])

  const toggleFormat = (f) => setFormats((s) => {
    const n = new Set(s); n.has(f) ? n.delete(f) : n.add(f); return n
  })
  const toggleCode = (code) => setCodes((s) => {
    const n = new Set(s); n.has(code) ? n.delete(code) : n.add(code); return n
  })
  const selectAll = () => setCodes(new Set(codeset.map((r) => r.code)))
  const clearAll = () => setCodes(new Set())

  // The scope written to the server: every selected code, on the selected doc-types it has a lane
  // for. Derived at save from the catalog, so a code/format pair the engine cannot judge can never
  // enter the scope. This is the authoritative write for BOTH axes.
  const scope = {}
  for (const row of codeset) {
    if (!codes.has(row.code)) continue
    const fmts = row.formats.filter((f) => formats.has(f))
    if (fmts.length) scope[row.code] = fmts
  }
  const scCount = Object.keys(scope).length
  const pairCount = Object.values(scope).reduce((n, f) => n + f.length, 0)

  // Eligible files, narrowed to the doc-types this scope will actually assess. The endpoint counts
  // every format the selected codes reach; the format axis restricts that to the ticked types, so
  // the headline reflects what the run will really open.
  const byFormat = elig?.by_format || {}
  const eligibleInScope = Object.entries(byFormat)
    .filter(([f]) => formats.has(f))
    .reduce((n, [, v]) => n + v, 0)

  const save = async () => {
    if (!scCount) {
      setMsg('Pick at least one WCAG check and one document type — an empty scope would assess everything.')
      return false
    }
    setSaving(true); setMsg('')
    try {
      const res = await updateSettings({ scan_scope: JSON.stringify(scope) })
      if (res?.simulated) {
        setMsg('SIM — nothing was written. This demo build has no backend.')
        return false
      }
      setMsg(`✓ Saved · ${scCount} check${scCount === 1 ? '' : 's'} on ${formats.size} document type${formats.size === 1 ? '' : 's'}`)
      onSaved?.(scope)
      return true
    } catch (e) {
      setMsg(e?.message || 'Could not save the assessment scope.')
      return false
    } finally { setSaving(false) }
  }

  return (
    <section className="panel assessscope">
      <h2 style={{ margin: 0 }}>Choose what to assess</h2>
      <p className="muted" style={{ margin: '3px 0 12px', fontSize: 13, lineHeight: 1.5 }}>
        Pick the document types and the WCAG success criteria this run assesses. This is the single
        source of truth for the assessment scope — Discover always shows the whole estate; what gets
        scored against WCAG is decided here.
      </p>

      {/* ① DOCUMENT TYPES — the format axis, authoritative. */}
      <div className="setupstep">
        <div className="setupstep-h"><span className="setupstep-n">1</span> Document types</div>
        <div className="setupchips">
          {SCOPE_FORMATS.map((f) => (
            <button key={f} className={formats.has(f) ? 'setupchip on' : 'setupchip'}
                    aria-pressed={formats.has(f)} onClick={() => toggleFormat(f)}>
              {formats.has(f) ? '✓ ' : ''}{FORMAT_LABEL[f] || f.toUpperCase()}
              <span className="muted"> · {f.toUpperCase()}</span>
            </button>
          ))}
        </div>
        <div className="muted setupcount">{formats.size} of {SCOPE_FORMATS.length} document types selected</div>
      </div>

      {/* ② WCAG CHECKS — the Core-17 criterion axis, "code — name". */}
      <div className="setupstep">
        <div className="setupstep-h">
          <span className="setupstep-n">2</span> WCAG success criteria
          <span className="muted setuphint"> · the Core 17</span>
        </div>
        <div className="setupbulk">
          <div className="setupbulk-sel">
            {codes.size < codeset.length && (
              <button className="setuplink" onClick={selectAll}>Select all {codeset.length}</button>
            )}
            {codes.size > 0 && <button className="setuplink" onClick={clearAll}>Clear all</button>}
          </div>
          <span className="muted" style={{ fontSize: 12 }}>{codes.size} of {codeset.length} selected</span>
        </div>
        {!loaded ? (
          <p className="muted" style={{ fontSize: 13 }}>Loading the code-set…</p>
        ) : (
          <div className="assessscope-codes" role="group" aria-label="WCAG success criteria">
            {codeset.map((r) => {
              const on = codes.has(r.code)
              return (
                <label key={r.code} className="setuprow assessscope-code">
                  <input type="checkbox" checked={on} onChange={() => toggleCode(r.code)}
                         aria-label={`${r.code} — ${r.name}`} />
                  <span className="setuprow-sc"><b>{r.code}</b> — {r.name}</span>
                  <span className="muted setuprow-f">{r.formats.map((f) => f.toUpperCase()).join(' · ')}</span>
                </label>
              )
            })}
          </div>
        )}
        <div className="muted setupcount setupcount-sub" style={{ marginTop: 6 }}>
          {scCount} check{scCount === 1 ? '' : 's'} in scope · {pairCount} criterion × format pairs
        </div>
      </div>

      {/* ③ ELIGIBLE FILES — the read-only count for the current selection, before any run. */}
      <div className="setupstep">
        <div className="setupstep-h"><span className="setupstep-n">3</span> Eligible files</div>
        <div className="assessscope-elig" role="status" aria-live="polite">
          {elig ? (
            <>
              <div className="assessscope-elign">
                <b>{eligibleInScope.toLocaleString()}</b> file{eligibleInScope === 1 ? '' : 's'} eligible
                <span className="muted"> · of {(elig.discovered || 0).toLocaleString()} discovered{eligLoading ? ' · updating…' : ''}</span>
              </div>
              {Object.keys(byFormat).length > 0 && (
                <div className="assessscope-eligfmts">
                  {Object.entries(byFormat).sort(([a], [b]) => a.localeCompare(b)).map(([f, n]) => (
                    <span key={f} className={formats.has(f) ? 'assessscope-eligfmt on' : 'assessscope-eligfmt'}
                          title={formats.has(f) ? `${FORMAT_LABEL[f] || f.toUpperCase()} · in your selected types` : `${FORMAT_LABEL[f] || f.toUpperCase()} · not in your selected types`}>
                      {(FORMAT_LABEL[f] || f.toUpperCase())} <b>{n.toLocaleString()}</b>
                    </span>
                  ))}
                </div>
              )}
              {(elig.discovered || 0) === 0 && (
                <p className="muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
                  No discovery run yet — the count fills in once you have scanned a source.
                </p>
              )}
            </>
          ) : (
            <span className="muted" style={{ fontSize: 13 }}>{eligLoading ? 'Counting eligible files…' : '—'}</span>
          )}
        </div>
        {/* Live population funnel — the narrowing behind the single count above, with each drop named. */}
        <ScopeImpact elig={elig} formats={formats} loading={eligLoading} />
      </div>

      <div className="emptyactions" style={{ marginTop: 8 }}>
        <button disabled={saving || !loaded || !scCount} onClick={save}>
          {saving ? 'Saving…' : 'Save assessment scope'}
        </button>
      </div>
      {msg && <p className="muted setupmsg" role="status" aria-live="polite">{msg}</p>}
    </section>
  )
}
