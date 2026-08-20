import { verifyState, reconcileVerify } from './verifyState.js'

// R9 — verify after fixing.
//
// THE SCREEN'S ONE JOB IS TO WITHHOLD A WORD. Every other panel in this flow can afford to say
// "fixed"; this one cannot, because it is the panel a reader looks at to find out whether anything
// actually is. So the three columns are "confirmed cleared", "applied but not confirmed" and "not
// yet remediated", the partition sums on screen, and no arrangement of the numbers produces a
// finding marked resolved on the strength of a batch having run.
//
// WHAT THE RE-RUN BUTTON ON THE DESIGN BOARD WOULD HAVE CLAIMED, AND WHY IT IS NOT HERE. The board
// draws "Re-assess the 6 changed documents", described as re-running the criteria over the
// remediated copies. No endpoint does that. `POST /scans/{id}/rescore?file=…` re-DOWNLOADS the
// document from its source and assesses that — and remediation writes a corrected COPY, leaving the
// source untouched. So on an unchanged source that button would re-report every finding it was
// pressed to confirm, and the screen would read as the fixes having failed.
//
// The verification that does exist is the one `remediate_file` performs for itself: after writing
// the corrected bytes it re-scans them and marks a criterion complete only where the criterion has
// actually gone. That is what this panel renders. The re-scan control is still offered, labelled
// for what it really does — re-read the original from its source — because that is genuinely useful
// once somebody has replaced the original themselves, and useless-to-misleading before then. It
// renders only when the parent passes a handler for it.

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const card = { border: '1px solid var(--line)', borderRadius: 12, padding: '12px 14px',
               background: 'var(--surface)' }
const lab = { fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.35 }
const val = { fontSize: 26, fontWeight: 700, fontVariantNumeric: 'tabular-nums', marginTop: 5, lineHeight: 1 }
const sub = { fontSize: 11.5, color: 'var(--muted)', marginTop: 5, lineHeight: 1.45 }
const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }
const th = { textAlign: 'left', color: 'var(--muted)', fontWeight: 600, fontSize: 11,
             letterSpacing: '.04em', textTransform: 'uppercase', padding: '0 12px 8px 0' }
const td = { padding: '9px 12px 9px 0', borderTop: '1px solid var(--line)', fontSize: 12.5,
             verticalAlign: 'top' }

/**
 * @param files            the scan's file rows
 * @param cap              remediation-capability map
 * @param assessment       assessment-lane map
 * @param criteria         the agreed criteria
 * @param level            conformance target
 * @param appliedCriteria  {[file]: remediation-state rows} — see verifyState.js
 * @param onRescanSource   (file) => void. Optional, and deliberately named for what the only
 *                         available endpoint does: re-read the ORIGINAL from its source. Omit it
 *                         and no re-scan control renders.
 * @param rescanning       the file currently being re-read, so its control disables in flight
 */
export default function RemediationVerify({ files, cap, assessment, criteria, level = 'AA',
                                            appliedCriteria, onRescanSource, rescanning = null }) {
  const v = verifyState(files, { cap, assessment, criteria, level, appliedCriteria })
  // Nothing, rather than three zeros. Zeros here would read as "nothing has been verified", which
  // is a finding about the estate rather than the absence of data about it.
  if (!v) return null
  const r = reconcileVerify(v)

  return (
    <section className="panel remediationverify">
      <div style={kicker}>Verify after fixing</div>

      {/* The rule, first, before any number that could be misread as a verdict. */}
      <p style={{ fontSize: 12.5, margin: '9px 0 0', lineHeight: 1.65 }}>
        <b>A fix is a claim until a re-run confirms it.</b> Nothing here is counted as resolved
        because a fix was applied — only because the corrected copy was re-scanned afterwards and
        the criterion had gone.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                    gap: 12, marginTop: 12 }}>
        <div style={card}>
          <div style={lab}>Confirmed cleared</div>
          <div style={{ ...val, color: v.confirmedFindings ? '#2F7D32' : undefined }}>
            {v.confirmedFindings}
          </div>
          <div style={sub}>
            Re-scanned in the corrected copy and no longer present there.
          </div>
        </div>
        <div style={card}>
          <div style={lab}>Applied but not confirmed</div>
          <div style={{ ...val, color: v.unconfirmedFindings ? '#B07A00' : undefined }}>
            {v.unconfirmedFindings}
          </div>
          <div style={sub}>
            A run touched the document and these did not come back clear. Still findings.
          </div>
        </div>
        <div style={card}>
          <div style={lab}>Not yet remediated</div>
          <div style={val}>{v.untouchedFindings}</div>
          <div style={sub}>
            In documents no remediation run has produced a corrected copy of.
          </div>
        </div>
      </div>

      <div className="muted" style={{ fontSize: 12, marginTop: 10, lineHeight: 1.6 }}>
        {r.ok ? r.line
              : <b style={{ color: '#B3261E' }}>{r.line} — these do not add up ({r.sum}); this
                  screen has a bug and its counts should not be relied on.</b>}
      </div>

      {/* The sentence that stops "1.3.1 confirmed cleared" beside a filename being read as a
          statement about the file that filename names. */}
      <p className="muted" style={{ fontSize: 12, margin: '8px 0 0', lineHeight: 1.6 }}>
        Every confirmation on this screen is evidence about the corrected <b>copy</b>. The original
        documents are unchanged and still contain their findings — ACP does not modify them.
      </p>

      {/* ── Per document ─────────────────────────────────────────────────────────────────── */}
      {v.documents.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 14 }}>
          <thead>
            <tr>
              <th style={{ ...th, width: '38%' }}>Document</th>
              <th style={th}>Findings</th>
              <th style={th}>Confirmed cleared</th>
              <th style={th}>Still open</th>
              {onRescanSource && <th style={th} />}
            </tr>
          </thead>
          <tbody>
            {v.documents.map((d) => (
              <tr key={d.file}>
                <td style={td}>
                  <span style={mono}>{d.name}</span>
                  <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                    {d.remediated
                      ? `corrected copy produced${d.verifiedAt ? ` · re-scanned ${d.verifiedAt}` : ''}`
                      : 'no remediation run yet'}
                  </div>
                </td>
                <td style={td}>{d.totalFindings}</td>
                <td style={{ ...td, color: d.confirmed ? '#2F7D32' : 'var(--muted)' }}>
                  {d.confirmed}
                  {d.confirmedCriteria.length > 0 && (
                    <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                      {d.confirmedCriteria.join(', ')}
                    </div>
                  )}
                </td>
                <td style={td}>
                  {d.open}
                  {d.openCriteria.length > 0 && (
                    <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                      {d.openCriteria.join(', ')}
                    </div>
                  )}
                </td>
                {onRescanSource && (
                  <td style={{ ...td, textAlign: 'right' }}>
                    <button className="ghost small" type="button"
                            disabled={rescanning === d.file}
                            onClick={() => onRescanSource(d.file)}>
                      {rescanning === d.file ? 'Re-reading…' : 'Re-scan the original'}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* What the re-scan control is, and what it is not. Next to it, not in a footnote. */}
      {onRescanSource && (
        <p className="muted" style={{ fontSize: 12, marginTop: 12, paddingTop: 10,
                                      borderTop: '1px solid var(--line)', lineHeight: 1.6 }}>
          <b style={{ color: 'var(--ink)' }}>&ldquo;Re-scan the original&rdquo; re-reads the
          document from its source</b> and assesses whatever is there now — it is not a re-run over
          the corrected copy, and ACP has no endpoint that is. Use it once you have replaced the
          original yourself. On a source that has not been replaced it will report the same findings
          again, which is a fact about the original and not a failure of the fix.
        </p>
      )}
    </section>
  )
}
