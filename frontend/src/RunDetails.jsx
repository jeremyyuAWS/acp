import { useState } from 'react'
import CoverageScorecard from './CoverageScorecard.jsx'
import ScanHistory from './ScanHistory.jsx'
import { TraceChip } from './Transparency.jsx'
import { assessMetrics } from './assessMetrics.js'

// Run details — the secondary surface the Assess results screen sends technical detail to.
//
// Three things were taken OFF the results screen and land here, for three different reasons:
//
//   1. THE CAPABILITY SCORECARD (5/20, 14/20 …). It is a property of ACP and of the customer's
//      document formats, IDENTICAL before and after any run. Sitting among results, its "5/20"
//      read as this run's score — the one reading it can never be. It is reframed here as a
//      reference: the page says, in its own copy, that these numbers do not change when you run
//      an assessment. That sentence is the whole reason the panel moved, so it is not decoration.
//
//   2. THE "UNABLE TO ASSESS" EXPLANATION. The single most-questioned number on the results
//      screen. A large count of selected checks comes back with no verdict, and the reason is
//      structural rather than a failure: most WCAG criteria describe barriers that can only occur
//      in some formats, and some can only be judged by a person. ACP traces every criterion in
//      scope against every document so the arithmetic is complete, and only claims a verdict where
//      it has a method.
//
//   3. SCAN TRACES. Engineering diagnostics. They belong behind a secondary action, not on an
//      operator's results page, so they are collapsed by default here — one more click than
//      before for the engineer, and off the page entirely for everyone else.
//
// WHAT THIS VIEW MAY NOT DO, and the tests assert each one:
//   · No score. No percentage. No estimate of time or human effort. All three were removed from
//     the results screen for want of an evidence base and none of them may re-enter through the
//     back door of a "details" page.
//   · No zeros standing in for absent data. Where the metrics have not arrived, this renders
//     NOTHING — a run that has not happened is not a run that found nothing.
//   · A criterion ACP has no method for is neither a pass nor a failure, and this page says so
//     wherever such a count appears. Reporting them as passes would be the most damaging thing
//     this product could do, and it is the specific mistake a "details" page invites.
//
// Every derived number comes from assessMetrics.js — the one place the screen's arithmetic is
// defined. Nothing here recomputes a count from the file list, so this page and the results
// screen cannot drift into quoting two different totals for one quantity.

// The criteria with no method, named rather than only counted. A reader who is told 563 checks
// returned nothing and not WHICH cannot check the claim; a reader who is told which can.
function UnassessableCriteria({ scs }) {
  if (!scs || scs.length === 0) return null
  return (
    <p className="muted" style={{ fontSize: 11.5, margin: '8px 0 0', lineHeight: 1.55 }}>
      No method for these formats: {scs.map((sc, i) => (
        <span key={sc}>{i > 0 ? ', ' : ''}<b style={{ fontVariantNumeric: 'tabular-nums' }}>{sc}</b></span>
      ))}.
    </p>
  )
}

// The "no method" panel — the honest framing of the grey bar people ask about.
//
// Renders one of two statements, never a blank and never a zero dressed as a result:
//   · some checks had no method — say how many, over what, which criteria, and that they are
//     neither passes nor failures;
//   · every check reached a verdict — say THAT, positively, rather than staying silent. An absent
//     warning has to be a statement, otherwise a reader cannot tell it apart from a missing panel.
function NoMethod({ m }) {
  const complete = m.unableToAssess === 0
  return (
    <section className="panel" style={{ borderLeft: '4px solid #D9D5DD' }}>
      <h2 style={{ color: 'inherit', fontSize: 14.5, fontWeight: 650, margin: '0 0 7px' }}>
        {complete
          ? `Every one of your ${m.selectedChecks} checks reached a verdict`
          : `Why ${m.unableToAssess} of your ${m.selectedChecks} checks came back “no method”`}
      </h2>
      {complete ? (
        <p className="muted" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.65, maxWidth: 940 }}>
          ACP had a method for every criterion in scope against every document it opened, so no
          check in this run sits in the “no method” bucket. That is a statement about this run's
          formats and criteria, not a claim that the documents conform.
        </p>
      ) : (
        <>
          <p className="muted" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.65, maxWidth: 940 }}>
            Most WCAG success criteria describe barriers that can only occur in some formats, and
            some can only be judged by a person looking at the document. ACP traces every criterion
            in scope against every document so the arithmetic is complete — but it only claims a
            verdict where it has a method. The {m.unableToAssess} are the cells where it does not,
            and reporting them as passes would be the single most damaging thing this product could
            do.
          </p>
          <p style={{ margin: '9px 0 0', fontSize: 12.5, lineHeight: 1.6, maxWidth: 940 }}>
            <b>They are not passes and they are not failures.</b> A criterion ACP has no method for
            has no verdict at all — it is neither evidence that the document is fine nor evidence
            that it is broken, and it stays on the list of work someone still has to do.
          </p>
          <UnassessableCriteria scs={m.unassessableCriteria} />
        </>
      )}
      {/* The arithmetic, printed rather than asserted in a test, so a partition that stops
          summing is visible to the reader and not only to whoever reads the query. */}
      <p className="muted" style={{ fontSize: 11.5, margin: '10px 0 0', paddingTop: 9,
                                    borderTop: '1px solid var(--line)', lineHeight: 1.6 }}>
        {m.checksEvaluated} checks evaluated + {m.unableToAssess} with no method
        = {m.selectedChecks} selected checks
        ({m.documentsAssessed} documents opened × {m.coverageSelected} criteria in the {m.scopeLabel}).
        One check is one criterion judged against one document.
      </p>
    </section>
  )
}

// Scan traces, behind a secondary action.
//
// TraceChip renders nothing when tracing is not configured, so the whole block is gated on a
// scanId rather than on a probe — an empty "Scan traces" heading over no chips would read as a
// broken panel rather than an unconfigured one.
function ScanTraces({ scanId, rows }) {
  const [open, setOpen] = useState(false)
  if (!scanId) return null
  return (
    <section className="panel">
      <h2 style={{ color: 'inherit', fontSize: 14.5, fontWeight: 650, margin: '0 0 6px' }}>Scan traces</h2>
      <p className="muted" style={{ margin: '0 0 10px', fontSize: 12.5, lineHeight: 1.6, maxWidth: 940 }}>
        The step-by-step record ACP wrote while it worked — what each detector was handed and what
        it returned. Engineering diagnostics: useful when a result needs explaining, never needed to
        act on one.
      </p>
      <button className="ghost small" onClick={() => setOpen((v) => !v)}
              title="Per-step diagnostics for this run — not part of the assessment result">
        {open ? 'Hide scan traces' : 'Show scan traces'}
      </button>
      {open && (
        <div style={{ marginTop: 12 }}>
          <TraceChip scanId={scanId} kind="session" label="View this scan’s traces" />
          {rows && rows.length > 0 && (
            <ul style={{ listStyle: 'none', padding: 0, margin: '12px 0 0', display: 'grid', gap: 6 }}>
              {rows.map((r) => (
                <li key={r.file} style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                                 fontSize: 12, flex: '1 1 260px' }}>{r.name || r.file}</span>
                  {/* An unopened file still has a trace — it is where the reason it could not be
                      read is recorded — so it is listed, and labelled rather than dropped. */}
                  {!r.opened && <span className="muted" style={{ fontSize: 11 }}>could not be opened</span>}
                  <TraceChip scanId={scanId} kind="file" file={r.file} label="View trace" />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

export default function RunDetails({ scanId, files, cap, assessment, onBack }) {
  // Nothing has arrived yet. Render NOTHING — not a skeleton of zeros. "0 checks with no method"
  // is a completed run that had a method for everything, and a run that has not reported is not
  // that. assessMetrics returns null for the same reason and by the same contract.
  if (!Array.isArray(files) || files.length === 0) return null
  const m = assessMetrics(files, { cap, assessment })
  if (!m) return null

  return (
    <div className="rundetails">
      <div className="muted" style={{ fontSize: 12.5 }}>
        <button className="ghost small" onClick={onBack}>← Assessment results</button>
      </div>
      <h1 style={{ margin: '10px 0 0', fontSize: 20, fontWeight: 650 }}>Run details</h1>
      <p className="muted" style={{ margin: '7px 0 0', maxWidth: 900, lineHeight: 1.6 }}>
        Everything behind the summary: why some selected checks returned no verdict, what ACP is
        able to check for these document formats at all, and the engineering traces for this run.
        The results screen stays a short summary because this page exists.
      </p>

      <NoMethod m={m} />

      {/* ── The capability reference. NOT a result, and the copy has to say so. ───────────── */}
      <section>
        <h2 style={{ margin: '22px 0 0', fontSize: 15, fontWeight: 650 }}>What ACP can check</h2>
        <p className="muted" style={{ margin: '7px 0 0', maxWidth: 940, lineHeight: 1.6, fontSize: 12.5 }}>
          A property of ACP and of your document formats.{' '}
          <b style={{ color: 'var(--ink)' }}>These numbers do not change when you run an
          assessment</b> — they are the same before this run and after it, and they would be the
          same if you never ran one. That is exactly why they no longer sit among the results,
          where a capability count like “5 of 20” read as this run's score.
        </p>
        <p className="muted" style={{ margin: '7px 0 0', maxWidth: 940, lineHeight: 1.6, fontSize: 12.5 }}>
          Read it as a reference, not a result: a criterion ACP has no method for is counted below
          as a gap in capability, and in a run it is neither a pass nor a failure.
        </p>
        <CoverageScorecard files={files} />
      </section>

      {/* ADR 0042 · the run's own durable lifecycle log. Belongs here for the same reason scan
          traces do (reason 3 in this file's header): operator diagnostics behind a secondary
          action, not on the results page. Collapsed by default and fetched only on expand. */}
      <ScanHistory scanId={scanId} />

      <ScanTraces scanId={scanId} rows={m.rows} />
    </div>
  )
}
