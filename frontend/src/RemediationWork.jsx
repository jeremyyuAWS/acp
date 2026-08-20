import { remediationWork, reconcileWork, batchScope, WORK_LANES, LANE_LABEL } from './remediationWork.js'

// R2 + R3 — the work partitioned once, and the batch that acts on one lane of it.
//
// R2 IS THE ASSESSMENT'S OWN TOTAL, RE-CUT. Not a second count of the estate: the same findings,
// the same filter, the same module (`documentRows`), split by who does the work instead of by how
// bad it is. The identity line under the cards is what proves that to a reader — five terms and the
// assessment's total, printed rather than asserted, so a partition that stops summing is visible in
// the same glance as the numbers it breaks.
//
// R3 IS ONE LANE, AND SAYS WHICH. "Apply N automatic fixes" acts on the deterministic lane and
// nothing else. The AI-drafted lane is next to it on screen and is deliberately NOT reachable from
// this button: a run drafts those values and files them for approval, and approving them is a
// separate, explicit, per-item act. The panel says so where the button is, because that is where
// somebody decides.
//
// THE SAFETY STATEMENT IS CONDITIONAL, AND THE BOARD'S VERSION WAS NOT TRUE. The design board says
// "Nothing is written to your drive." That holds only while the Drive mirror is off. With it on
// (the platform default), `remediate_file` writes the corrected copy to Blob AND uploads it to a
// "Remediated" folder in the source drive. So the destination sentence here is driven by the actual
// setting, and when the setting has not been read this screen says nothing about the destination
// rather than guessing the reassuring answer. What is unconditional — and true either way — is that
// remediation produces a COPY and never modifies the original.

const card = { border: '1px solid var(--line)', borderRadius: 12, padding: '12px 14px',
               background: 'var(--surface)' }
const lab = { fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.35 }
const val = { fontSize: 26, fontWeight: 700, fontVariantNumeric: 'tabular-nums', marginTop: 5, lineHeight: 1 }
const sub = { fontSize: 11.5, color: 'var(--muted)', marginTop: 5, lineHeight: 1.45 }
const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }

// Tone marks the two lanes that differ in KIND, not in size: green for the one no person touches,
// amber for the one that looks automatic and is not. The other three are unstyled on purpose —
// colouring five cards makes the two that matter stop reading as different.
const LANE_TONE = { automatic: '#2F7D32', drafted: '#B07A00' }

const LANE_NOTE = {
  automatic: 'No judgement involved — same input, same fix, no model call.',
  drafted: 'An AI wrote a candidate value. Nothing is applied until a person approves it.',
  authored: 'No draft is possible. ACP shows the location and a person writes the fix.',
  applied: 'A corrected copy already carries this fix, confirmed by a re-scan of that copy.',
  unfixable: 'Reported by a run as beyond what can be corrected in the file.',
}

/**
 * @param files              the scan's file rows — the same array the assessment screen was given
 * @param cap                remediation-capability map {fmt:{sc:'auto'|'assisted'|'human'}}
 * @param assessment         assessment-lane map
 * @param criteria           the agreed criteria (defaults to the agreed scope)
 * @param level              conformance target
 * @param appliedCriteria    {[file]: remediation-state rows} — see remediationWork.js
 * @param unfixableCriteria  {[file]: criteria a run reported unfixable}
 * @param driveMirror        null when the platform setting has not been read, else
 *                           {enabled, folder} from GET /settings. Drives the destination sentence
 *                           in R3 — see the note at the top of this file.
 * @param onApplyAutomatic   (files) => void. Omit and no batch button renders at all: this screen
 *                           never shows a control for an action the parent cannot perform.
 * @param applying           true while a batch is in flight, so the button cannot be pressed twice
 */
export default function RemediationWork({ files, cap, assessment, criteria, level = 'AA',
                                          appliedCriteria, unfixableCriteria, driveMirror = null,
                                          onApplyAutomatic, applying = false }) {
  const w = remediationWork(files, { cap, assessment, criteria, level,
                                     appliedCriteria, unfixableCriteria })
  // Nothing, rather than five zeros. A remediation screen over a run that has not happened is not a
  // remediation screen that found no work.
  if (!w) return null

  const r = reconcileWork(w)
  const batch = batchScope(w)

  return (
    <section className="remediationwork">

      {/* ── R2 · the work, partitioned once ──────────────────────────────────────────────── */}
      <div style={kicker}>The work</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
                    gap: 12, marginTop: 9 }}>
        {WORK_LANES.map((k) => (
          <div key={k} style={card}>
            <div style={lab}>{LANE_LABEL[k]}</div>
            <div style={{ ...val, color: LANE_TONE[k] }}>{w.lanes[k].count}</div>
            <div style={sub}>{LANE_NOTE[k]}</div>
          </div>
        ))}
      </div>

      {/* The identity, printed. Either it holds on screen or it is a visible bug. */}
      <div className="muted" style={{ fontSize: 12, marginTop: 10, lineHeight: 1.6 }}>
        <div>{r.line}</div>
        <div>
          {r.ok
            ? <>The same {w.assessmentTotal} finding{w.assessmentTotal === 1 ? '' : 's'} the assessment
                counted, partitioned by <b>who does the work</b> rather than by severity.</>
            : <b style={{ color: '#B3261E' }}>These do not add up to the {w.assessmentTotal} findings
                the assessment counted ({r.sum}) — this screen has a bug and its numbers should not
                be relied on.</b>}
        </div>
      </div>

      {/* ── R3 · the batch ───────────────────────────────────────────────────────────────── */}
      {batch && (
        <div className="panel" style={{ marginTop: 16, borderLeft: '4px solid #2F7D32' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                        gap: 20, flexWrap: 'wrap' }}>
            <div style={{ maxWidth: 780 }}>
              <div style={{ fontSize: 15, fontWeight: 650 }}>
                Apply {batch.count} automatic fix{batch.count === 1 ? '' : 'es'}
              </div>
              <p className="muted" style={{ margin: '6px 0 0', fontSize: 12.5, lineHeight: 1.6 }}>
                {/* Criteria, not a prose list of fix names: the prose would be a second, hand-kept
                    copy of the capability table and would go quietly wrong the moment the table
                    gains a criterion. */}
                Covers {batch.criteria.length} criteri{batch.criteria.length === 1 ? 'on' : 'a'}
                {' '}({batch.criteria.join(', ')}) across {batch.documents} document
                {batch.documents === 1 ? '' : 's'}. Each is deterministic — the same input produces
                the same fix, with no model involved.
              </p>

              {/* Where the batch stops. Said here, beside the button, not in a footnote. */}
              <p className="muted" style={{ margin: '8px 0 0', fontSize: 12.5, lineHeight: 1.6 }}>
                <b style={{ color: 'var(--ink)' }}>Nothing is applied without this explicit
                action, and no AI draft is ever approved by it.</b> A run also drafts values for the
                criteria it cannot decide — those are filed for your approval and are never written
                on their own.
              </p>

              {/* The safety statement. The unconditional half first, because it is the half that is
                  true regardless of how the platform is configured. */}
              <p className="muted" style={{ margin: '8px 0 0', fontSize: 12.5, lineHeight: 1.6 }}>
                <b style={{ color: 'var(--ink)' }}>Your original documents are never
                modified.</b> ACP produces a corrected copy of each one and leaves the source
                exactly as it was.
                {driveMirror && driveMirror.enabled === false && (
                  <> The copies stay in ACP&rsquo;s own storage — nothing is written to your drive.</>
                )}
                {driveMirror && driveMirror.enabled === true && (
                  <> Each copy is <b style={{ color: 'var(--ink)' }}>also written to your drive</b>,
                    into a separate{driveMirror.folder ? ` “${driveMirror.folder}”` : ''} folder
                    beside the original — a new file, never an overwrite.</>
                )}
              </p>
              {!driveMirror && (
                <p className="muted" style={{ margin: '6px 0 0', fontSize: 11.5, lineHeight: 1.6 }}>
                  Where the copies are stored is a platform setting this screen has not read, so it
                  is not stated here.
                </p>
              )}
            </div>

            {onApplyAutomatic && (
              <div style={{ textAlign: 'right', flex: '0 0 auto' }}>
                <button type="button" disabled={applying}
                        onClick={() => onApplyAutomatic(batch.files)}>
                  {applying ? 'Applying…' : `Apply ${batch.count} fix${batch.count === 1 ? '' : 'es'}`}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* The deterministic lane being empty is a RESULT, not an absent panel. Without this the
          screen simply has no batch section and reads as though the feature failed to load. */}
      {!batch && (
        <p className="muted" style={{ fontSize: 12.5, marginTop: 14, lineHeight: 1.6 }}>
          No finding here has a deterministic fix, so there is no batch to apply. Every outstanding
          finding needs a person — either to approve a draft or to write the fix.
        </p>
      )}
    </section>
  )
}
