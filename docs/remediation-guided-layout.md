# Guided Remediate layout

Remediate presents permissions on the left and assessment results plus a remediation
forecast on the right. The layout stacks on smaller screens. The prior sliders remain
available under Advanced for individual permission control.

The three control choices map to the existing rule-based policy levels: review every
change (0), qualifying validated fixes (1), and all eligible rule-based fixes (2).
Choosing a rule-based mode never enables AI implicitly. No AI and Use configured AI map
to the existing AI-off (0) and draft-for-review (1) execution policies.

Assessment status, coverage, severity and totals retain their assessment meaning. The
Auto-fix available and Human review required tiles explicitly show a plan preview for
the selected remediation scope. Human review combines proposal review and manual work;
blocked findings remain a separate category. Unavailable previews never display zero.
Both tiles open the shared accessible right drawer. Files and finding reasons come
from the authoritative forecast; a finding drilldown stays within the selected route.

Configured text and vision provider names, models and reported processing zones are
shown when AI is enabled. They do not establish organizational approval or connectivity.
Per-run private/cloud routing, provider overrides, cost estimates and enforceable
spending caps are not implemented by the execution service. The screen states those
limits and does not offer controls that imply otherwise. Automatic AI application
remains unavailable on the current execution path.

Verification uses worktree DOM tests, including permission payloads, live tiles,
historical totals, drawer filtering, Escape and focus restoration. The shared preview
server does not serve this worktree and is not used as evidence for this change.
