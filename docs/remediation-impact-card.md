# Remediation impact card

Implementation outline for the approved two-slider remediation planner. The assessment remains
the historical source of findings; changing this card previews remediation routing only.

```text
Completed assessment (all unresolved findings)
                    |
                    v
       +---------------------------+
       | Rule-based application    |
       | Review / Verified /       |
       | Eligible                  |
       +---------------------------+
       | AI assistance             |
       | Off / Draft for review    |
       | Automatic tiers: limited  |
       +---------------------------+
                    |
                    v
       Authoritative routing forecast
                    |
          +---------+----------+----------+
          |         |          |          |
          v         v          v          v
        Auto      Review     Manual     Blocked
          |         |          |          |
          +---------+----------+----------+
                    |
             File outlook
                    |
     +--------------+--------------+
     |              |              |
     v              v              v
 Could complete  Human work    Incomplete /
 automatically   remains      unavailable
```

## Units and integrity

- Finding counts use the full unresolved assessment population, including findings without a
  proposal or review card. Review cards enrich that population; they are not extra findings.
- Routing buckets are exclusive and reconcile to unresolved findings.
- Distinct files within finding buckets can overlap. File-outlook groups are exclusive.
- An eligible fix is not an applied fix. An applied fix is not a verified resolution.
- A potential AI draft is not an existing proposal or a guaranteed resolution.
- Missing coverage evidence must not produce an automatic-completion claim.

## Execution contract

New jobs seal `remediation_impact_policy` and an authoritative
`remediation_impact_allowed_rules` list. Workers intersect the rule list with assessment failures
and the recorded assessment scope. Browser-supplied allowed-rule lists must never be trusted.

Review-first permits no automatic document mutations, even if a malformed job contains allowed
rules. Proposal-only routines may still prepare review work. With no permitted rules the worker
queues remaining failures for review and returns before writing a corrected artifact.

AI drafting is enabled only when both the sealed policy and the current global AI permission
allow it. Media transcription is covered by that gate. OCR proposals remain available with AI
off, but their optional vision-model logotype hint is disabled.

Format remediators contain inline AI mutation paths. New-policy jobs therefore disable AI in
those writers and generate supported AI drafts through proposal-only routines instead. The
automatic AI slider tiers are not executable until the worker can select, apply, and verify
eligible individual AI proposals. Unsupported policies fail closed; the UI must explain this
capability limit rather than promise automation.

The current format writers operate at criterion granularity. If a file has both an automatic
and a protected finding for the same criterion, the forecast must route the whole criterion
to review. Per-finding permission cannot safely be enforced by a criterion-wide writer.

Legacy queued jobs without a remediation impact policy retain their existing execution behavior.
Existing assessment results and prior proposals are not rewritten by slider changes.

Planning includes human-only files and residual findings after earlier remediation. Only explicit
document selection, N/A, or deferral narrows the cohort. The same cohort reaches preview and execution.

The previous `AutomationPolicyControl` is deliberately unmounted and retained, with the retirement
recorded in the component wiring tests and `CLAUDE.md`.

## Assignment

The planner can seed missing review tasks from its authoritative human-work population and assign
selected files to an email address. Only pending tasks are assigned; approvals and work already under
review are preserved. Assignment is owner-scoped, does not send notifications, and reports partial
progress so a failure cannot disguise earlier successful writes. Finding and task counts remain separate.

## Current capability limits

- Automatic AI application is unavailable because the current format writers cannot selectively
  apply eligible individual AI proposals. These tiers are visibly unavailable, not simulated.
- Verified-only routing requires source-bound validation evidence. Legacy queue validation is
  post-write evidence without that binding, so it never grants automatic permission in this preview.
- Human-work teams are suggested through action categories; assignment persists an individual owner.
- The Accessibility menu's session AI toggle remains unchanged. Its relocation to assessment setup
  is a separate UI change; it does not configure the provider credentials or this execution policy.

## Provider settings

Provider/model selection and credentials remain independent of the sliders. Display connection
status and the effective text/vision routes without exposing secrets. A configured key does not
itself authorize a model call or automatic application. Historical proposals retain their actual
provider provenance.

## Verification

`tests/test_remediation_impact_execution.py` exercises the worker boundary: review-first avoids
mutators, the allowed criterion intersection reaches the real writer call, inline AI is disabled,
AI-off prevents media transcription and optional vision hints, unsupported AI automation fails
before drafting, and the global kill switch overrides a drafting snapshot.

Frontend interaction checks must run against the isolated worktree using DOM tests. The shared
preview server is not evidence about this branch.
