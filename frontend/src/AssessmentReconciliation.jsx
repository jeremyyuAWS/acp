import { reconcileBuckets, bucketEquation } from './estateFunnel.js'
import { reconciliationInputs } from './reconciliationInputs.js'

// "What was assessed, and what was not" — the identity behind the Overview's headline numbers.
//
// The screen shows a discovered total and an assessed total, and until now the distance between
// them was an unexplained gap. This panel closes it by PRINTING THE ARITHMETIC: five mutually
// exclusive buckets, each a real count, added up in front of the reader and compared to the
// discovered total. If the buckets do not reach that total, the panel says so — in the row of
// numbers, not in a comment somebody would have to go and read.
//
// Everything honest about it lives in estateFunnel.reconcileBuckets; this file is the rendering,
// and its only jobs are: never print a `0` where the model returned null, never print a percentage
// without the denominator beside it, and never describe a lifecycle RECOMMENDATION as a completed
// archive or deletion.
//
// Overview-only, deliberately. Discover's copy of EstateCoverage answers "what is in the estate";
// this answers "what did the assessment cover", which is a question a run has to have happened for.

const nf = new Intl.NumberFormat('en-US')

// A share always travels with its denominator — "24.9% of 12,408", never a bare "24.9%". One
// decimal because the small buckets are the interesting ones and a whole number rounds 0.4% to 0%,
// which reads as none.
const share = (row, discovered) =>
  `${(row.share * 100).toFixed(1)}% of ${nf.format(discovered)}`

export default function AssessmentReconciliation({ run, files, inventory }) {
  const inv = inventory || run?.scope?.inventory
  const rec = reconcileBuckets(inv, reconciliationInputs(run, files))
  // No inventory, nothing to partition. Rendering an empty frame would be worse than rendering
  // nothing: it looks like a panel whose numbers failed to load.
  if (!rec) return null

  const equation = bucketEquation(rec)
  const measured = rec.rows.filter((r) => r.measured)
  const unmeasured = rec.rows.filter((r) => !r.measured)
  // Track widths are shares of the DISCOVERED total, so the bar's empty tail is the shortfall made
  // visible — the same fact the arithmetic line states in words.
  const trackDenom = Math.max(rec.discovered, rec.total)

  return (
    <section className="panel" aria-label="What was assessed, and what was not">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>What was assessed, and what was not</h2>
        <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
          every discovered file lands in exactly one row
        </span>
      </div>

      <div style={{ height: 10, background: '#f0edf2', borderRadius: 999, overflow: 'hidden', display: 'flex', marginBottom: 14 }}>
        {measured.map((r) => (
          <i key={r.key} title={`${r.label}: ${nf.format(r.value)}`}
             style={{ display: 'block', height: '100%', background: r.color,
                      width: `${trackDenom ? (r.value / trackDenom) * 100 : 0}%` }} />
        ))}
      </div>

      <dl style={{ margin: 0 }}>
        {rec.rows.map((r) => (
          <div key={r.key}
               style={{ display: 'grid', gridTemplateColumns: '14px 1fr auto', alignItems: 'baseline',
                        gap: 10, fontSize: 13, padding: '8px 0', borderTop: '1px solid var(--line, #ece8ee)' }}>
            <span aria-hidden="true"
                  style={{ width: 11, height: 11, borderRadius: 3, background: r.color,
                           opacity: r.measured ? 1 : 0.35, alignSelf: 'center' }} />
            <dt style={{ margin: 0, fontWeight: 400 }}>
              <b>{r.label}</b> <span className="muted">— {r.note}</span>
              {r.key === 'lifecycle' && rec.overridden > 0 && (
                <span className="muted"> ({nf.format(rec.overridden)} overridden and assessed — counted under Assessed, not here)</span>
              )}
            </dt>
            <dd style={{ margin: 0, textAlign: 'right', whiteSpace: 'nowrap' }}>
              {/* NEVER a zero for an unmeasured bucket. "0 flagged for archive review" and "we did
                  not record whether anything was flagged" are opposite claims, and the reassuring
                  one is the wrong default. */}
              {r.measured ? (
                <>
                  <b style={{ fontVariantNumeric: 'tabular-nums' }}>{nf.format(r.value)}</b>
                  <span className="muted" style={{ fontSize: 11.5, display: 'block' }}>{share(r, rec.discovered)}</span>
                </>
              ) : (
                <span className="muted" title="This scan did not record this count — it is not zero, it is unknown.">
                  not recorded
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>

      {/* THE ARITHMETIC, ON SCREEN. A reader can add these up; that is the entire point. */}
      <div style={{ display: 'grid', gridTemplateColumns: '14px 1fr auto', gap: 10, alignItems: 'baseline',
                    padding: '11px 0 0', marginTop: 6, borderTop: '2px solid var(--line, #ece8ee)', fontSize: 13 }}>
        <span />
        <span className="muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {equation ? `${equation} =` : 'nothing measured'}
        </span>
        <b style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{nf.format(rec.total)}</b>
      </div>

      {rec.reconciles ? (
        <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
          ✓ The rows account for all {nf.format(rec.discovered)} discovered files.
        </p>
      ) : (
        // Said out loud, with role="status", rather than left for a reader to discover by adding up
        // a column that does not reach the headline. Same discipline as the age-band reconciliation.
        <p role="status" style={{ fontSize: 12.5, margin: '8px 0 0', lineHeight: 1.55, color: 'var(--warn-fg)' }}>
          <strong>
            {rec.overlap
              ? `These rows total ${nf.format(rec.total)}, which is ${nf.format(-rec.unaccounted)} MORE than the ${nf.format(rec.discovered)} files discovered — they overlap, so some files are counted twice.`
              : `These rows total ${nf.format(rec.total)} of ${nf.format(rec.discovered)} discovered files — ${nf.format(rec.unaccounted)} ${rec.unaccounted === 1 ? 'file is' : 'files are'} in no row above.`}
          </strong>{' '}
          {unmeasured.length > 0
            ? `${unmeasured.length === 1 ? 'One bucket was' : `${unmeasured.length} buckets were`} not recorded by this scan (${unmeasured.map((r) => r.label).join(', ')}), so this total cannot be complete.`
            : 'Treat the split as indicative until the counts agree.'}
        </p>
      )}

      <p className="muted" style={{ fontSize: 11.5, margin: '10px 0 0', lineHeight: 1.55 }}>
        The rows are mutually exclusive. A file that is both flagged for lifecycle review and of an
        unselected type is counted once, under lifecycle — the earlier reason wins, so the same file
        is never counted twice.
        {rec.truncated && ' The listing hit its cap, so the discovered total is a floor and every row here is a floor with it.'}
      </p>
      <p className="muted" style={{ fontSize: 11.5, margin: '6px 0 0', lineHeight: 1.55 }}>
        “Assessed” means every selected criterion that applies to a file was evaluated — not that the
        file conforms to WCAG 2.1 AA, and not that the criteria this run did not select were checked.
      </p>
    </section>
  )
}
