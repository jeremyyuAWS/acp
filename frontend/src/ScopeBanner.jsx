import { SCOPE_SIZE, SCOPE_LABEL, OUT_OF_SCOPE_SCS, outOfScopeNote } from './activeScope.js'
import { scopeSentence, isNarrowScope } from './scanScope.js'

// What the numbers on this screen are counting — stated ON the screen that shows them.
//
// Discover, Assess, Overview and Transparency all name their scope. Remediate and Publish did
// not: zero references to activeScope in either, so an operator read finding counts, remediation
// progress and a certification decision with no statement of what was assessed to produce them.
//
// That is the same defect class this codebase has fixed twice already — a header reading
// "20 of 20 criteria automated" above six rows (ruleBreakdownScope14.test.jsx), and the dashboard
// totals in #77/#84. A number a reader cannot reconcile against what is in front of them costs
// more confidence than an unflattering one. It is worse on Publish than anywhere else, because
// the artifact that screen produces is a compliance record: "certified" against an unstated scope
// is a claim nobody can check later.
//
// TWO SCOPES, BOTH NAMED, because they answer different questions and either can silently shrink
// a result:
//   * WHICH CRITERIA were assessed — the operator's scan_scope, mirrored by activeScope. This is
//     what the backend gated on inside _rule_outcome, so it decides which findings can exist.
//   * WHICH FILES were scanned — run.scope, the folder/site narrowing. A one-folder scan and a
//     whole-drive scan produce very different totals from the same estate.
//
// THREE now. The per-document selection is the third: marking one document in scope excludes
// every unmarked one, and that restriction lived entirely inside Remediate — Publish, which
// produces the compliance record, had no idea it existed. An operator could mark 2 of 258
// documents, remediate those two, and read a report whose every number is about 258.
//
// It comes in as a SENTENCE rather than as `triage`, so this component keeps knowing nothing
// about triage semantics and the two screens cannot word the same fact differently
// (remediableScope.documentScopeSentence owns it).
//
// Rendered whether or not the scope is narrow, and that is deliberate: a caveat that appears only
// sometimes teaches a reader to read its absence as "everything", which is exactly how the
// original folder-scan incident went unnoticed (see scanScope.js). The document clause is the
// exception — it is absent precisely when there IS no per-document restriction, and saying "all
// 258 documents in scope" on every screen would be noise around the one case that matters.
export default function ScopeBanner({ run, fileCount, findings = 0, docScope = null }) {
  const fileScope = scopeSentence(run?.scope, fileCount)
  const narrow = isNarrowScope(run?.scope) || !!docScope
  return (
    <div className={`scopebanner${narrow ? ' scopebanner-narrow' : ''}`} role="note">
      <span className="scopebanner-lead">Counting</span>
      <span>
        <b>{SCOPE_SIZE}</b> criteria in the {SCOPE_LABEL}
        {fileScope ? <> · {isNarrowScope(run?.scope) ? '⚠ ' : ''}{fileScope}</> : null}
        {docScope ? <> · ⚠ {docScope}</> : null}
      </span>
      {OUT_OF_SCOPE_SCS.size > 0 && (
        <span className="scopebanner-note">{outOfScopeNote(findings)}</span>
      )}
    </div>
  )
}
