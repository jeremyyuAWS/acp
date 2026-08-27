import { useState, useEffect, useRef } from 'react'
import { getSettings, updateSettings, fetchCodeset, fetchEligibility } from './api.js'
import { SCOPE_FORMATS } from './scopePresets.js'
import { parseStoredScope } from './ScanScope.jsx'
import { scopeImpact, coverageGaps } from './scopeImpact.js'
import { WCAG } from './wcagCatalog.js'

// The Assess PRE-RUN screen — board 2 of the redesign. One card that holds every decision the run
// depends on, and nothing that reports on a run.
//
// WHY THIS SCREEN OWNS THE EXCLUSIONS. The review note on the results board was "we should NOT have
// any exclusions at this stage" — at the RESULTS. This is the stage that owns them. Everything
// knowable WITHOUT opening a file is settled here: document type, lifecycle tag, and whether ACP
// has an assessment lane for the criteria you picked. Discovery is metadata-only (api/handlers.py
// — list, classify from metadata, STOP; no file is ever opened), so those are the only exclusions
// that can honestly exist before a run.
//
// What CANNOT be decided here is whether a document will actually open. Password protection,
// corruption and unsupported internal variants are discoverable only by trying to read the file,
// which happens during Assess — so a failed read is an OUTCOME on the results screen, never an
// exclusion on this one. The card says so in as many words, because the division is the whole
// point and a reader cannot infer it from the numbers.
//
// THE ARITHMETIC IS ON SCREEN. Every excluded population is named with its count, and the parts are
// printed adding back up to the discovered total. A run that quietly assesses 22 of 12,408 without
// the operator seeing that ratio is the failure this screen exists to prevent — which is why the
// acknowledgement states the fraction in words and the run is gated on it.
//
// NO SECOND OPINION ABOUT THE TARGET. There is no Level A / AA / AAA selector. The conformance
// target is DERIVED from the criteria selection (see deriveLevel below) and stated as derived. Two
// controls that can disagree about one thing is the defect this redesign is about.
//
// NO ESTIMATES. No "about 3 minutes", no score, no bare percentage. Every number on this screen is
// a count rendered with the noun it counts and the population it counts over.
//
// This does not replace AssessScope.jsx by deleting it: App.jsx still imports that component, and
// removing it here would break the build before the parent has rewired. Once App.jsx renders
// AssessSetup instead, AssessScope.jsx + ScopeImpact.jsx + assessScope.test.jsx are removable.

const FORMAT_LABEL = { docx: 'Word', pdf: 'PDF', pptx: 'PowerPoint', xlsx: 'Excel' }
const fmtLabel = (f) => FORMAT_LABEL[f] || String(f).toUpperCase()

// The eligible count is fetched live as the selection changes; a short debounce keeps a fast
// clicker from firing a request per checkbox while still feeling immediate. Same value AssessScope
// used, for the same reason.
const DEBOUNCE_MS = 300

const RANK = { A: 1, AA: 2, AAA: 3 }
// The hand-kept WCAG catalogue carries the conformance level for every 2.1/2.2 criterion — the
// authoritative source AssessRunner's own derivation consults first.
const CATALOG_LEVEL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))

/**
 * The conformance target, DERIVED from the selected success criteria.
 *
 * The highest WCAG level present in the selection sets the target: any AAA criterion makes it AAA,
 * otherwise AA (the ADA/EAA/508 floor and what every shipped document scope resolves to), and A
 * only when the selection is entirely Level A. This mirrors `deriveLevel(SCOPE_SCS)` in
 * AssessRunner.jsx — the engine has always taken the target this way, so the removed selector was
 * not merely redundant, it was a second opinion the code was already ignoring.
 *
 * Exported so the rule can be asserted directly rather than inferred from rendered text.
 * An empty selection has no target to derive and returns null; the caller renders nothing.
 */
export function deriveLevel(scs) {
  let maxR = 0
  for (const sc of scs || []) {
    const r = RANK[CATALOG_LEVEL[sc]] || 1
    if (r > maxR) maxR = r
  }
  if (!maxR) return null
  return maxR >= 3 ? 'AAA' : maxR === 1 ? 'A' : 'AA'
}

const n = (x) => Number(x || 0).toLocaleString()
const plural = (count, one, many) => (count === 1 ? one : many)

const row = { display: 'flex', gap: 12, alignItems: 'flex-start', padding: '14px 0',
              borderTop: '1px solid var(--line)' }
const rowLabel = { width: 190, flex: '0 0 190px', fontSize: 12.5, color: 'var(--muted)', paddingTop: 1 }
const rowValue = { flex: 1, minWidth: 0, fontSize: 13.5, lineHeight: 1.55 }
const linkBtn = { border: 'none', background: 'none', padding: 0, font: 'inherit', fontSize: 12.5,
                  color: 'var(--plum)', cursor: 'pointer', textDecoration: 'underline' }

/**
 * The Assess pre-run screen.
 *
 * @param onRun         REQUIRED. Called when the operator starts the run, with a descriptor of
 *                      exactly what was decided here:
 *                        { scope, codes, formats, documents, criteria, checks, level,
 *                          includeLifecycleFlagged, discovered, excluded }
 *                      `scope` is the criterion → formats map that was just written to
 *                      `scan_scope`; `includeLifecycleFlagged` is the authorized override the
 *                      POST /scans/{id}/assess route takes as `include_lifecycle_flagged`.
 *                      Not called unless there is at least one document to assess.
 * @param onSaved       optional. The saved scope map, for a parent that mirrors it in its own
 *                      state — same signature AssessScope used.
 * @param busy          optional. True while a run is already in flight; disables the action.
 * @param discoveredAt  optional. The discovery run's timestamp, for the header line. Omitted
 *                      renders no line at all rather than an invented one.
 */
export default function AssessSetup({ onRun, onSaved, busy = false, discoveredAt = null }) {
  const [codeset, setCodeset] = useState([])            // [{code, name, formats:[...]}] — the Core 17
  const [codes, setCodes] = useState(() => new Set())   // selected criteria (criterion axis)
  const [formats, setFormats] = useState(() => new Set(SCOPE_FORMATS))  // selected doc-types
  const [elig, setElig] = useState(null)                // {discovered, eligible, by_format, ...}
  const [eligLoading, setEligLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [editTypes, setEditTypes] = useState(false)
  const [editCriteria, setEditCriteria] = useState(false)
  const [includeFlagged, setIncludeFlagged] = useState(false)
  const [acked, setAcked] = useState(false)
  const [starting, setStarting] = useState(false)
  const [msg, setMsg] = useState('')
  const debounce = useRef(null)

  // Load the catalogue and the stored scope together, so the screen opens reflecting the platform's
  // current selection rather than a fresh default. No stored scope reads as "everything".
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

  // Live eligible-file count, debounced, keyed on the selected criteria. Read-only — it never
  // starts a scan, so calling it on every selection change is safe.
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

  // Changing the selection invalidates the acknowledgement: it names a specific fraction, and a
  // tick carried across an edit would be an acknowledgement of numbers the operator never saw.
  const formatsKey = [...formats].sort().join(',')
  useEffect(() => { setAcked(false) }, [codesKey, formatsKey, includeFlagged])

  const toggleFormat = (f) => setFormats((s) => {
    const x = new Set(s); x.has(f) ? x.delete(f) : x.add(f); return x
  })
  const toggleCode = (code) => setCodes((s) => {
    const x = new Set(s); x.has(code) ? x.delete(code) : x.add(code); return x
  })

  // The scope written to the server: every selected criterion, on the selected document types it
  // actually has a lane for. Derived from the catalogue, so a (criterion × format) pair the engine
  // cannot judge can never enter the scope however the boxes are ticked. Identical derivation to
  // AssessScope's, because it is the same authoritative write for both axes.
  const scope = {}
  for (const r of codeset) {
    if (!codes.has(r.code)) continue
    const fmts = (r.formats || []).filter((f) => formats.has(f))
    if (fmts.length) scope[r.code] = fmts
  }
  const criteriaCount = Object.keys(scope).length
  const level = deriveLevel(Object.keys(scope))
  const gaps = coverageGaps(codeset, codes, formats)

  // ── The population arithmetic ────────────────────────────────────────────────────────────────
  // All of it from `scopeImpact`, the same unit-tested derivation the funnel already used, so this
  // screen cannot invent a fourth answer to "how many files". Every stage is a real backend count:
  // a stage the backend does not report (an older response with no lifecycle field) is ABSENT
  // rather than guessed, which is also why a missing count renders nothing here and never 0.
  const impact = scopeImpact(elig, formats)
  const discovered = impact ? impact.discovered : null
  // The lifecycle drop is the authorized override's subject: included, those files come back into
  // the run and stop being an exclusion at all.
  const lifecycleDrop = impact ? (includeFlagged ? 0 : impact.lifecycleExcluded) : 0
  const lifecycleTagged = impact ? impact.lifecycleExcluded : 0
  const documents = impact ? Math.max(0, impact.inScope - lifecycleDrop) : null
  const noMethod = impact ? impact.noMethod : 0
  const deselected = impact ? impact.deselected : 0
  const excluded = noMethod + deselected + lifecycleDrop
  // One number defines the run. Rendered with both factors beside it so it can never read as a
  // measurement of anything.
  const checks = documents == null ? null : documents * criteriaCount

  // Named populations, in the order they narrow. Only a population that exists is rendered — a
  // zero row is not an exclusion, it is noise that makes the real ones harder to read.
  const exclusionRows = [
    noMethod > 0 && {
      key: 'nomethod', count: noMethod,
      what: 'not a document type ACP can assess — media, archives, and unsupported or legacy file '
          + 'types, recognised from the filename and the source metadata',
    },
    deselected > 0 && {
      key: 'deselected', count: deselected,
      what: 'outside the document types selected above',
    },
    lifecycleDrop > 0 && {
      key: 'lifecycle', count: lifecycleDrop,
      // A lifecycle rule writes a RECOMMENDATION on a discovered file. It does not move or delete
      // anything, so this must never read as "N archived files" or "N deleted files" — the file is
      // still there, and a screen that says otherwise is describing an action nobody took.
      what: 'tagged for archive or deletion review by a lifecycle rule',
    },
  ].filter(Boolean)

  // The identity, printed. Either it holds on screen or the bug is visible to the reader rather
  // than only to whoever reads the query.
  const reconcile = impact && [
    ...exclusionRows.map((r) => `${n(r.count)} excluded`),
    `${n(documents)} assessed`,
  ].join(' + ') + ` = ${n(discovered)} discovered`

  const needsAck = excluded > 0
  const ready = !!documents && criteriaCount > 0 && (!needsAck || acked)

  const start = async () => {
    if (!ready) return
    setStarting(true); setMsg('')
    try {
      const res = await updateSettings({ scan_scope: JSON.stringify(scope) })
      // `simulated` is the demo build answering "there is no backend to write to". Nothing was
      // persisted, which is worth saying — but it is not a failure, and refusing to run would
      // leave the offline build with no Assess at all.
      if (res?.simulated) setMsg('SIM — the scope was not persisted; this demo build has no backend.')
      onSaved?.(scope)
      onRun?.({
        scope, codes: [...codes].sort(), formats: [...formats].sort(),
        documents, criteria: criteriaCount, checks, level,
        includeLifecycleFlagged: includeFlagged, discovered, excluded,
      })
    } catch (e) {
      setMsg(e?.message || 'Could not save the assessment scope, so the run was not started.')
    } finally { setStarting(false) }
  }

  const selectedFormats = SCOPE_FORMATS.filter((f) => formats.has(f))

  return (
    <section className="panel assesssetup">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                    gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 650 }}>Assess</h2>
        {/* A count we do not have renders nothing — never "0 files listed", which is a discovery
            result nobody obtained. Same for the timestamp: absent unless the parent supplies it. */}
        {(discoveredAt || discovered > 0) && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            {discoveredAt ? `From discovery run ${discoveredAt}` : 'From the latest discovery run'}
            {discovered > 0 && ` · ${n(discovered)} ${plural(discovered, 'file', 'files')} listed`}
          </span>
        )}
      </div>
      <p className="muted" style={{ margin: '6px 0 0', fontSize: 13, lineHeight: 1.55 }}>
        Discovery listed the estate from metadata — no file was opened. This is the step that opens
        documents and scores them against WCAG.
      </p>

      <div style={{ border: '1px solid var(--line)', borderRadius: 14, padding: '4px 18px 16px',
                    marginTop: 16, background: 'var(--surface)' }}>

        {/* ① DOCUMENTS ─────────────────────────────────────────────────────────────────────── */}
        <div style={{ ...row, borderTop: 'none' }}>
          <div style={rowLabel}>Documents</div>
          <div style={rowValue} className="assesssetup-documents">
            {documents == null ? (
              <span className="muted" style={{ fontSize: 13 }}>
                {eligLoading ? 'Counting eligible documents…' : 'No eligible-file count yet.'}
              </span>
            ) : (
              <><b>{n(documents)} {plural(documents, 'document', 'documents')}</b> will be opened and scored</>
            )}
            <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              {selectedFormats.length
                ? selectedFormats.map((f) => `.${f}`).join(' · ')
                : 'no document types selected'}
              {' — '}
              <button type="button" style={linkBtn} onClick={() => setEditTypes((v) => !v)}>
                {editTypes ? 'done' : 'change document types'}
              </button>
            </div>
            {editTypes && (
              <div className="setupchips" style={{ marginTop: 10 }}>
                {SCOPE_FORMATS.map((f) => (
                  <button key={f} type="button" className={formats.has(f) ? 'setupchip on' : 'setupchip'}
                          aria-pressed={formats.has(f)} onClick={() => toggleFormat(f)}>
                    {formats.has(f) ? '✓ ' : ''}{fmtLabel(f)}
                    <span className="muted"> · {f.toUpperCase()}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ② CRITERIA, and the target DERIVED from them ────────────────────────────────────── */}
        <div style={row}>
          <div style={rowLabel}>Criteria</div>
          <div style={rowValue} className="assesssetup-criteria">
            {!loaded ? (
              <span className="muted" style={{ fontSize: 13 }}>Loading the code-set…</span>
            ) : (
              <>
                <b>{n(criteriaCount)} success {plural(criteriaCount, 'criterion', 'criteria')}</b>
                {' '}— selected from the Core {codeset.length || ''}, on the document types above
              </>
            )}
            <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              <button type="button" style={linkBtn} onClick={() => setEditCriteria((v) => !v)}>
                {editCriteria ? 'Done' : 'Change criteria'}
              </button>
            </div>
            {editCriteria && (
              <div className="assessscope-codes" role="group" aria-label="WCAG success criteria"
                   style={{ marginTop: 8 }}>
                {codeset.map((r) => (
                  <label key={r.code} className="setuprow assessscope-code">
                    <input type="checkbox" checked={codes.has(r.code)} onChange={() => toggleCode(r.code)}
                           aria-label={`${r.code} — ${r.name}`} />
                    <span className="setuprow-sc"><b>{r.code}</b> — {r.name}</span>
                    <span className="muted setuprow-f">{(r.formats || []).map((f) => f.toUpperCase()).join(' · ')}</span>
                  </label>
                ))}
              </div>
            )}

            {/* THE TARGET IS DERIVED, and stated as derived. There is no picker here, and adding
                one would recreate the two-controls-one-fact defect this board removes. */}
            {level && (
              <div className="muted assesssetup-target"
                   style={{ fontSize: 12.5, marginTop: 8, paddingTop: 8,
                            borderTop: '1px solid var(--line)', lineHeight: 1.55 }}>
                <b style={{ color: 'var(--ink)' }}>Conformance target: WCAG 2.1 Level {level}</b>
                {' '}— derived from the criteria above, not chosen separately. The highest level
                present in your selection sets the target, so the two can never disagree.
              </div>
            )}

            {/* Blind spots in the selection — a criterion ticked for a document type ACP has no
                lane for. Knowable now, from the catalogue, without opening anything; saying it
                here is what stops it arriving as a surprise in "unable to assess" afterwards. */}
            {gaps.length > 0 && (
              <div className="muted assesssetup-gaps" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.6 }}>
                {gaps.map((g) => (
                  <div key={g.format}>
                    <b style={{ color: 'var(--ink)' }}>{g.count}</b>{' '}
                    selected {plural(g.count, 'criterion has', 'criteria have')} no assessment method
                    for {fmtLabel(g.format)} — {g.codes.map((c) => c.code).join(', ')}. Nothing in
                    that document type will be scored against {plural(g.count, 'it', 'them')}.
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ③ NOT BEING ASSESSED — the exclusions, with their arithmetic ───────────────────── */}
        {/* Gated on a real estate. With nothing discovered there is no population to exclude
            FROM, and "nothing is excluded from 0 files" is a true sentence that reads as a
            reassurance about a run that cannot happen. The empty state below says it properly. */}
        {impact && discovered > 0 && (
          <div style={row}>
            <div style={rowLabel}>
              Not being assessed
              {excluded > 0 && (
                <div style={{ fontSize: 11.5, marginTop: 2 }}>{n(excluded)} of {n(discovered)}</div>
              )}
            </div>
            <div style={rowValue}>
              {excluded === 0 ? (
                <p className="muted" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6 }}>
                  Nothing is excluded — every one of the {n(discovered)} discovered
                  {' '}{plural(discovered, 'file', 'files')} is queued for this run.
                </p>
              ) : (
                <div className="assesssetup-exclusions"
                     style={{ border: '1px solid var(--line)', borderRadius: 11, padding: '12px 14px',
                              background: 'var(--bg)' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px',
                                fontSize: 12.5, lineHeight: 1.5 }}>
                    {exclusionRows.map((r) => (
                      <div key={r.key} style={{ display: 'contents' }}>
                        <div style={{ fontWeight: 700, textAlign: 'right',
                                      fontVariantNumeric: 'tabular-nums' }}>{n(r.count)}</div>
                        <div>{r.what}</div>
                      </div>
                    ))}
                  </div>

                  {/* THE FRACTION, IN WORDS, and the run waits for it. The operator has to have
                      seen the ratio — that is the entire job of this control. When unchecked the
                      row extends to the box edges and the fraction renders in ink (not muted) so
                      the numbers that need reading are the most visible thing on the screen. */}
                  <label className="assesssetup-ack"
                         style={{ display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 12.5,
                                  lineHeight: 1.5, cursor: 'pointer',
                                  ...(!acked
                                    ? { margin: '8px -14px -12px', padding: '11px 14px 12px',
                                        background: 'var(--ack-warn-bg, #fffbf4)',
                                        borderTop: '1px solid var(--ack-warn-border, #fcd34d)',
                                        borderRadius: '0 0 10px 10px' }
                                    : { marginTop: 11, paddingTop: 11,
                                        borderTop: '1px solid var(--line)' }) }}>
                    <input type="checkbox" checked={acked} style={{ marginTop: 2 }}
                           onChange={(e) => setAcked(e.target.checked)}
                           aria-label={`I have reviewed what is excluded. Assessing ${documents} of ${discovered} discovered files.`} />
                    <span>I have reviewed what is excluded.{' '}
                      <span {...(acked ? { className: 'muted' } : {})}>
                        Assessing {n(documents)} of {n(discovered)} discovered
                        {' '}{plural(discovered, 'file', 'files')}.
                      </span></span>
                  </label>
                </div>
              )}

              {/* The printed identity. The parts add back up to the whole, on screen. */}
              {excluded > 0 && (
                <div className="muted assesssetup-reconcile"
                     style={{ fontSize: 12, marginTop: 8, fontVariantNumeric: 'tabular-nums' }}>
                  {reconcile}
                </div>
              )}

              {/* The authorized override (include_lifecycle_flagged). A tag is a recommendation a
                  rule wrote, not an action anybody took — so the files are still there to assess. */}
              {lifecycleTagged > 0 && (
                <div className="muted assesssetup-lifecycle" style={{ fontSize: 12, marginTop: 8 }}>
                  {includeFlagged ? (
                    <>The {n(lifecycleTagged)} {plural(lifecycleTagged, 'file', 'files')} tagged for
                      archive or deletion review {plural(lifecycleTagged, 'is', 'are')} included in this
                      run — <button type="button" style={linkBtn}
                                    onClick={() => setIncludeFlagged(false)}>leave them out</button>.</>
                  ) : (
                    <>The {n(lifecycleTagged)} tagged {plural(lifecycleTagged, 'file', 'files')} can be
                      assessed anyway — <button type="button" style={linkBtn}
                                                onClick={() => setIncludeFlagged(true)}>include them</button>.</>
                  )}
                </div>
              )}

              {/* The division this screen exists to make legible. */}
              <div className="muted assesssetup-division"
                   style={{ fontSize: 11.5, marginTop: 9, paddingTop: 9,
                            borderTop: '1px solid var(--line)', lineHeight: 1.55 }}>
                <b style={{ color: 'var(--ink)' }}>This is where exclusions are decided.</b>{' '}
                Everything knowable without opening a file — type, lifecycle tag, folder — is settled
                on this screen. Whether a document can actually be read is only discoverable by
                reading it, so a failure to open appears on the results screen as an outcome of the
                run, not as an exclusion here.
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Nothing to assess: state the CAUSE and offer the control that fixes it ──────────── */}
      {impact && documents === 0 ? (
        <div className="assesssetup-empty" style={{ marginTop: 14 }}>
          <div style={{ fontSize: 15, fontWeight: 650 }}>Nothing to assess</div>
          <p className="muted" style={{ fontSize: 12.5, margin: '6px 0 0', lineHeight: 1.6 }}>
            {discovered === 0
              ? 'No discovery run has listed an estate yet. Discover lists the files before anything '
                + 'can be assessed.'
              : <>Discovery listed {n(discovered)} {plural(discovered, 'file', 'files')}, and none is
                  queued for this run{deselected > 0 && ' once your document-type selection is applied'}
                  {noMethod > 0 && deselected === 0 && ' — none has an assessment method for the criteria you selected'}
                  {lifecycleDrop > 0 && ', and the rest are tagged for archive or deletion review'}
                  . Widening the document types or the criteria will change that.</>}
          </p>
          {discovered > 0 && (
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button type="button" className="ghost small" onClick={() => setEditTypes(true)}>
                Change document types
              </button>
              <button type="button" className="ghost small" onClick={() => setEditCriteria(true)}>
                Change criteria
              </button>
            </div>
          )}
        </div>
      ) : (
        /* ── One action. Nothing competes with it, and no estimate sits beside it. ─────────── */
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 14, flexWrap: 'wrap' }}>
          <button type="button" className="assesssetup-run" disabled={!ready || busy || starting}
                  onClick={start}>
            {starting ? 'Starting…'
              : documents == null ? 'Assess' : `Assess ${n(documents)} ${plural(documents, 'document', 'documents')}`}
          </button>
          {checks != null && criteriaCount > 0 && (
            <span className="muted" style={{ fontSize: 12.5 }}>
              {n(checks)} {plural(checks, 'check', 'checks')}
            </span>
          )}
          {needsAck && !acked && (
            <span style={{ fontSize: 12.5, color: 'var(--ink)' }} role="status">
              Check the box above to continue.
            </span>
          )}
        </div>
      )}

      {/* One number defines the run, and every figure on the results screen is a slice of it. */}
      {checks != null && documents > 0 && criteriaCount > 0 && (
        <div className="muted assesssetup-onenumber"
             style={{ marginTop: 16, padding: '13px 15px', borderRadius: 11, background: 'var(--bg)',
                      border: '1px solid var(--line)', fontSize: 12.5, lineHeight: 1.6 }}>
          <b style={{ color: 'var(--ink)' }}>One number defines this run:</b>{' '}
          {n(documents)} {plural(documents, 'document', 'documents')} × {n(criteriaCount)}{' '}
          {plural(criteriaCount, 'criterion', 'criteria')} ={' '}
          <b style={{ color: 'var(--ink)' }}>{n(checks)} {plural(checks, 'check', 'checks')}</b>.
          Every figure on the results screen is a slice of those {n(checks)}, and the slices are
          shown adding back up to it.
        </div>
      )}

      {msg && <p className="muted setupmsg" role="status" aria-live="polite">{msg}</p>}
    </section>
  )
}
