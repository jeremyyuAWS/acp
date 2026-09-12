# Visual AI remediation drawer

The Remediate waterfall opens a right drawer with Overview, Changes, Attempts, and
Evidence. The selected run and model remain visible while the user explores it.

## Implemented behavior

- Overview presents the saved model journey, recorded reviewers, whole-run result
  cards, and settled/reserved/remaining budget meter. Selecting a journey item
  selects its exact graph node and saved attempt IDs.
- Changes offers document selection, recorded location navigation, highlighted
  before/proposed values, full retained values, and paginated supporting evidence.
  Values remain proposals unless their exact version has verification evidence.
- Automatic approvals display an indigo badge, separate from the existing green
  Verified finding pill. Approval is an authorization event, not an application or
  verification result. Finding categories and accounting remain unchanged.
- New automatic decisions retain structured evidence for scope, completeness,
  supported correction, current source, exact model provenance, and required AI
  review. Application and post-change checks are recorded as pending at approval
  time. Historical records without this evidence remain readable.
- Full-document AI summaries use saved run records. A selected model does not
  acquire credit for unlinked document-wide activity.

## Automatic approval

Existing run-plan defaults and eligibility enforcement are retained. Starting an
accepted plan with automatic approval authorizes qualifying exact suggestions,
including eligible fallbacks, without another approval dialog. Optional AI review
must accept the draft when required by the immutable saved policy. Current source,
selected criteria, complete proposals, supported writers, and exact run provenance
remain required. Existing application and verification checks remain in place.
These UI changes do not grant authorization to previously started runs or change
publication policy.

No model self-reported confidence score is presented as proof of correctness.

## Pill meanings

Reuse RemediationCategoryPill for existing finding states: Auto, Approve, AI,
Manual, No ACP, Blocked, Pending, AI applied, and Verified. The separate indigo
Auto-approved badge records a decision; it must not replace a finding category or
be counted as a verified fix. Model-stage accents identify workflow positions and
are independent of finding outcome colors.

## Data boundaries

Saved excerpts are available for content and structural changes. The insights
contract does not retain matching original/corrected page images for every run;
this drawer therefore does not display a synchronized page-image comparison or
invent a page map. Recorded locators remain navigable as text. A future page-image
viewer needs artifact-version identities and original/corrected image access tied
to the selected run before it can make trustworthy before/after claims.

Missing data remains missing, rather than zero or success. Attempt counts,
proposal versions, changes, review items, and findings keep their original units.
Whole-run results are explicitly distinct from selected-model activity. Budget
proportions appear only for complete, balanced amounts.

## Verification

Verify branch changes with worktree DOM tests in Vitest, backend approval/insights
fixtures, the frontend build, and repository coverage/backlog/progress guards.
The shared preview server is not evidence about worktree changes.
