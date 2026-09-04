import { useEffect, useState } from 'react'
import { getScanManifest } from './api.js'
import {
  runIntegrity, skippedRulesOf, COMPLETE, INCOMPLETE, UNAVAILABLE, STALE, PENDING,
} from './runIntegrity.js'

// The Assessment Run Integrity Gate — what this run actually checked, and whether its results may
// be read as a conformance result.
//
// It sits ABOVE the summary rather than inside it, and it is not collapsible when the answer is
// "no". A caveat a reader can close is a caveat that is absent from the screenshot, and this screen
// gets screenshotted; the one thing this panel exists to prevent is a clean-looking result being
// circulated as evidence of compliance over a run that did not finish looking.
//
// WHY IT IS NOT A SCORE. It reports four counts that do not add into one number, on purpose:
//
//   Passed          the check ran and found nothing              evidence of compliance
//   Not checked     the check applies and did not run            ABSENCE of evidence
//   Errored         the check was attempted and the engine broke absence of evidence, with a cause
//   Not applicable  the check belongs to another format          nothing was ever owed
//
// "Passed" and "Not checked" are indistinguishable in any total that adds them together, and until
// 2026-09-01 the manifest added them together — every un-run rule was recorded PASS, so a .docx the
// engine could not open reported 17 passes and 100% completeness. api/store.py's _save_file_manifest
// carries that history. A single "coverage score" here would rebuild the same collapse in the UI.
//
// The verdict itself lives in runIntegrity.js and is asserted without a DOM. This file renders it.

const PANEL = {
  border: '1px solid var(--line)', borderRadius: 12, padding: '14px 16px',
  background: 'var(--surface)', marginBottom: 16,
}
const TONE = {
  [COMPLETE]: { c: '#2F7D32', bar: '#2F7D32' },
  [INCOMPLETE]: { c: '#B3261E', bar: '#B3261E' },
  [UNAVAILABLE]: { c: '#B07A00', bar: '#B07A00' },
  [STALE]: { c: '#B07A00', bar: '#B07A00' },
  [PENDING]: { c: 'var(--muted)', bar: '#9A93A0' },
}
const cellNum = { fontVariantNumeric: 'tabular-nums', textAlign: 'right' }

/** One of the four statuses, with the count and the sentence that keeps it distinct. */
function Tally({ label, value, meaning, tone }) {
  return (
    <tr>
      <th scope="row" style={{ textAlign: 'left', fontWeight: 600, padding: '4px 12px 4px 0' }}>
        {label}
      </th>
      <td style={{ ...cellNum, padding: '4px 12px 4px 0', color: tone, fontWeight: 700 }}>{value}</td>
      <td style={{ color: 'var(--muted)', fontSize: 12.5, padding: '4px 0' }}>{meaning}</td>
    </tr>
  )
}

/**
 * Read one run's coverage record.
 *
 * Exported so the SCREEN can own the fetch and hand the same result to both this panel and to
 * whatever else has to be qualified by it. Two callers each fetching would be two round trips and,
 * worse, two answers — and a summary that says "no findings" while the panel above it says
 * "coverage unknown" is precisely the contradiction this feature exists to remove.
 */
export function useScanManifest(scanId, { skip = false } = {}) {
  const [state, setState] = useState({ manifest: null, error: null, loading: false })
  useEffect(() => {
    if (skip || !scanId) return undefined
    let current = true
    setState({ manifest: null, error: null, loading: true })
    getScanManifest(scanId)
      .then((m) => { if (current) setState({ manifest: m, error: null, loading: false }) })
      // The read failing is a REPORTABLE state, not a reason to render nothing. A panel that
      // disappears when it cannot answer leaves the summary below it looking unqualified, which
      // is the exact outcome the gate exists to prevent.
      .catch((e) => { if (current) setState({ manifest: null, error: e, loading: false }) })
    return () => { current = false }
  }, [scanId, skip])
  return state
}

export default function AssessRunIntegrity({
  scanId, manifest: given = null, verdict: providedVerdict = null,
  runInFlight = false, currentScanId = null,
}) {
  // A caller that already computed the verdict (the Assess screen does, so the summary beside
  // this panel can carry the same caveat) hands it in, and nothing is fetched.
  const fetched = useScanManifest(scanId, { skip: providedVerdict != null || given != null })
  const { manifest, error, loading } = fetched

  const verdict = providedVerdict ?? runIntegrity(given ?? manifest, {
    error, loading, runInFlight,
    manifestScanId: (given ?? manifest)?.scan_id ?? null,
    currentScanId: currentScanId ?? scanId ?? null,
  })
  const tone = TONE[verdict.status] || TONE[PENDING]
  const c = verdict.counts

  return (
    <section
      className="panel"
      style={{ ...PANEL, borderLeft: `4px solid ${tone.bar}` }}
      aria-labelledby="run-integrity-h"
    >
      <h2 id="run-integrity-h" style={{ fontSize: 15, margin: '0 0 2px' }}>Run integrity</h2>

      {/* role=status rather than alert: this is a standing statement about the run, not an
          interruption, and it is re-read on every state change. */}
      <p role="status" style={{ margin: '6px 0 2px', color: tone.c, fontWeight: 600 }}>
        {verdict.headline}
      </p>
      {verdict.detail && (
        <p style={{ margin: '2px 0 0', color: 'var(--muted)', fontSize: 12.5 }}>{verdict.detail}</p>
      )}
      {verdict.readError && (
        <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: 12 }}>
          Reason: {verdict.readError}
        </p>
      )}

      {/* Deliberately absent on STALE and PENDING. Rendering the previous run's numbers under this
          run's heading is how they get quoted as this run's. */}
      {c && (
        <>
          <p style={{ margin: '10px 0 4px', fontSize: 13 }}>
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{c.checked}</b> of{' '}
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{c.expected}</b> applicable checks
            completed{' '}
            <span style={{ color: tone.c, fontWeight: 700 }}>({c.completenessPct}%)</span>
            {' · '}
            {c.filesTotal} file{c.filesTotal === 1 ? '' : 's'}
          </p>

          <table style={{ borderCollapse: 'collapse', fontSize: 13, margin: '8px 0 0' }}>
            {/* `sronly` is this codebase's visually-hidden class (styles.css). A caption gives the
                table a name for anyone navigating by table, without repeating the heading on
                screen — and it must be the class that actually exists, or it renders as stray
                text under the panel heading. */}
            <caption className="sronly">
              Check outcomes for this run, counted separately
            </caption>
            <thead>
              <tr>
                <th scope="col" style={{ textAlign: 'left' }}>Outcome</th>
                <th scope="col" style={{ textAlign: 'right' }}>Checks</th>
                <th scope="col" style={{ textAlign: 'left' }}>What it means</th>
              </tr>
            </thead>
            <tbody>
              <Tally label="Passed" value={c.checked} tone="#2F7D32"
                     meaning="Ran and found nothing. The only outcome that is evidence of compliance." />
              <Tally label="Not checked" value={c.notChecked} tone={c.notChecked ? '#B3261E' : 'inherit'}
                     meaning="Applies to the file and did not run. Absence of evidence, not a pass." />
              <Tally label="Errored" value={c.errored} tone={c.errored ? '#B3261E' : 'inherit'}
                     meaning="Attempted; the engine failed on it." />
              {c.unattributed > 0 && (
                <Tally label="Errored (unidentified)" value={c.unattributed} tone="#B3261E"
                       meaning="The engine counted these failures but did not record which checks they were." />
              )}
              <Tally label="Not applicable" value={c.notApplicable} tone="var(--muted)"
                     meaning="Belongs to another file format. Nothing was owed, so it counts neither way." />
            </tbody>
          </table>

          {/* The arithmetic, rendered rather than only asserted — a partition that stops summing
              should be visible to the reader, not only to whoever reads the query. */}
          <p style={{ margin: '8px 0 0', color: c.reconciles ? 'var(--muted)' : '#B3261E', fontSize: 12 }}>
            {c.checked} passed + {c.errored} errored + {c.notChecked} not checked
            {c.unattributed > 0 ? ` + ${c.unattributed} unidentified` : ''} ={' '}
            {c.expected} applicable
            {c.reconciles ? '' : ' — these do not add up; treat every figure here as unreliable.'}
          </p>
        </>
      )}

      {verdict.files.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <h3 style={{ fontSize: 13, margin: '0 0 6px' }}>
            Affected files ({verdict.files.length})
          </h3>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
            {verdict.files.map((f) => (
              <li key={f.file} style={{ marginBottom: 6 }}>
                <b>{f.file}</b>{' — '}
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {f.checked} of {f.expected} checks completed
                </span>
                {f.why && <span style={{ color: 'var(--muted)' }}>{' · '}{f.why}</span>}
                <SkippedRules manifest={given ?? manifest} file={f.file} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

/**
 * The named checks that did not run on one file.
 *
 * Behind a disclosure because it is long and the counts above already carry the verdict — but
 * present, because "17 checks did not run" and "1.1.1, 1.3.1, 2.4.2 … did not run" are different
 * amounts of help to somebody deciding whether the gap matters for their document.
 */
function SkippedRules({ manifest, file }) {
  const entry = (manifest?.files || []).find((f) => f.file === file)
  const rules = skippedRulesOf(entry)
  if (!rules.length) return null
  return (
    <details style={{ marginTop: 3 }}>
      <summary style={{ cursor: 'pointer', color: 'var(--muted)' }}>
        Which checks ({rules.length})
      </summary>
      <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
        {rules.map((r) => (
          <li key={r.ruleId}>
            <code>{r.ruleId}</code>{' — '}
            {r.status === 'ERROR' ? 'engine error' : 'not checked'}
          </li>
        ))}
      </ul>
    </details>
  )
}
