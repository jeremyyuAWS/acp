import { docRemediationProgress, remainingSummary, allBlocked } from './docRemediationProgress.js'

// R7 · Per-document progress — where this document is in the remediation pipeline, and what is left.
//
// Not a second opinion about stages: the counts come from `docRemediationProgress`, which is
// `workflowStatusOf` (the shipped definition behind the workflow tabs) with its `completed` bucket
// split into "the re-scan confirmed it" versus "settled with no fix written". Those two are the same
// number on the tabs and must not be the same number here.
//
// Two things it will not do:
//   • Zero is not a loading state. `queue == null` renders "not loaded yet" — never a full bar of
//     zeros that reads as a clean document.
//   • ADR 0020: Discover lists files and opens none, so there is no discovery stage on this rail and
//     nothing here suggests the document had been read before it was assessed. The pipeline starts
//     at the assessment, which is what actually opened it.

const DOT = (tone) => ({
  width: 9, height: 9, borderRadius: 999, flex: '0 0 auto',
  background: tone, border: '1px solid rgba(0,0,0,.08)',
})
const TONE = {
  'to-review': '#2f6fed', authoring: '#c2871a', written: '#8a8f98',
  confirmed: '#1f9d6b', settled: '#b3aeb8', blocked: '#c0553f',
}

function Bar({ p }) {
  // Only ever drawn from a real fraction. `pct` is null when there is nothing to take a fraction of.
  if (p.pct == null) return null
  return (
    <div className="docprog-bar" role="img"
         aria-label={`${p.done} of ${p.total} findings are through the pipeline`}
         style={{ height: 6, borderRadius: 999, background: 'var(--surface-2,#f6f5f8)', overflow: 'hidden', margin: '8px 0 10px' }}>
      <div style={{ width: `${p.pct}%`, height: '100%', background: 'var(--ok-ink,#217a3b)' }} />
    </div>
  )
}

function StageRow({ s, current }) {
  return (
    <li className={`docprog-stage${current ? ' current' : ''}`}
        style={{ display: 'flex', alignItems: 'baseline', gap: 9, padding: '6px 0',
                 borderTop: '1px solid var(--line,#eceff4)', opacity: s.count === 0 ? .55 : 1 }}>
      <span aria-hidden="true" style={{ ...DOT(TONE[s.key] || '#b3aeb8'), alignSelf: 'center' }} />
      <span style={{ flex: '1 1 auto', fontSize: 13, fontWeight: current ? 700 : 500 }}>
        {s.label}
        {current && <span className="muted" style={{ fontWeight: 500, fontSize: 12 }}> — where it is now</span>}
      </span>
      <span style={{ fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{s.count}</span>
    </li>
  )
}

export default function RemediationDocProgress({ queue, file = null, decisions = {}, showStageHints = true }) {
  const p = docRemediationProgress(queue, file, decisions)

  // Missing is not zero. A pending fetch says so and renders no counts at all.
  if (!p) {
    return (
      <section className="docprog docprog-unloaded" aria-label="Remediation progress">
        {file && <h4 style={{ margin: '0 0 4px', fontSize: 14 }}>{file}</h4>}
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          Remediation progress hasn’t loaded yet.
        </p>
      </section>
    )
  }

  if (p.total === 0) {
    return (
      <section className="docprog docprog-none" aria-label="Remediation progress">
        {file && <h4 style={{ margin: '0 0 4px', fontSize: 14 }}>{file}</h4>}
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          No remediation findings were recorded for this document in this assessment.
        </p>
      </section>
    )
  }

  const remaining = remainingSummary(p)
  return (
    <section className="docprog" aria-label="Remediation progress">
      {file && <h4 style={{ margin: '0 0 2px', fontSize: 14 }}>{file}</h4>}

      {/* One dominant statement, then one progress indicator — the redesign's rule for the header. */}
      <p className="docprog-headline" style={{ margin: '0 0 2px', fontSize: 13.5 }}>
        {allBlocked(p)
          ? `All ${p.total} finding${p.total === 1 ? '' : 's'} on this document are blocked — none can be remediated as they stand.`
          : p.complete
            ? `All ${p.total} finding${p.total === 1 ? '' : 's'} on this document are through the pipeline.`
            : `${p.done} of ${p.total} finding${p.total === 1 ? '' : 's'} through the pipeline`}
      </p>
      {remaining && (
        <p className="docprog-remaining muted" style={{ margin: 0, fontSize: 12.5 }}>{remaining}</p>
      )}
      <Bar p={p} />

      <ol className="docprog-stages" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {p.stages.map((s) => (
          <StageRow key={s.key} s={s} current={p.at?.key === s.key} />
        ))}
      </ol>

      {showStageHints && p.at && (
        <p className="docprog-hint muted" style={{ margin: '10px 0 0', fontSize: 12.5 }}>{p.at.hint}</p>
      )}

      {/* The estimate, labelled as one. It is remediationInboxModel's per-lane figure — the same
          number the workspace bar shows — not a measured duration. */}
      {p.remainingLabel && (
        <p className="docprog-effort muted" style={{ margin: '6px 0 0', fontSize: 12 }}>
          {p.remainingLabel} — an estimate from the kind of work left, not a measured time.
        </p>
      )}

      {/* The partition, on screen. If it ever stops holding, the reader sees it here rather than
          trusting a total that disagrees with its own parts. */}
      <p className="docprog-reconcile" style={{
        margin: '10px 0 0', fontSize: 11.5,
        color: p.reconcile.ok ? 'var(--muted,#8a8f98)' : 'var(--bad-ink,#a33b28)',
        fontWeight: p.reconcile.ok ? 400 : 700,
      }}>
        {p.reconcile.ok
          ? p.reconcile.line
          : `Stage counts do not add up: ${p.reconcile.line} (they sum to ${p.reconcile.sum})`}
      </p>
    </section>
  )
}
