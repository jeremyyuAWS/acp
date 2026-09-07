# PRD — Scheduling Management Experience

**Product:** ACP  
**Surface:** Platform Settings → Scheduling  
**Status:** Proposed  
**Owner:** Platform Operations  
**Related:** `docs/prd-capacity-scheduling.md`

## 1. Summary

Turn the existing Scheduling page from a technical capacity report into a guided management
experience. Authorized administrators should be able to understand the active policy, edit it,
validate it, save it, apply it to Azure, and create temporary overrides without needing to know
ACP's internal scaling model.

This PRD changes presentation and workflow, not the scheduling semantics defined by the parent
capacity-scheduling PRD. Scheduling still manages warm infrastructure capacity; it does not
schedule scans or remediation runs.

## 2. Problem

The current page successfully reports schedule intent, validation, observed capacity, scaler
health, and attribution. Its management controls exist, but they are easy to miss and expose the
underlying data model as one dense form:

- The page opens with “Proposed schedule — not in force,” but does not lead the user toward the
  next action.
- Schedule status, validation, editing, applying, overrides, and technical diagnostics compete
  for attention in one long page.
- Capacity is expressed as raw replica counts without enough task-level explanation.
- Timezone entry requires an exact IANA identifier.
- Holiday exceptions require comma-separated text.
- Saving intention and applying it to Azure are separate operations, but the user is not given a
  clear staged workflow between them.
- View-only users see why they cannot edit only after inspecting the page; administrators do not
  get an obvious primary action.
- On narrower screens, the four-column capacity table becomes difficult to scan and edit.

## 3. Product outcome

An administrator can answer these questions at a glance:

1. What capacity mode is active now?
2. When will it change next?
3. Is the saved schedule applied to Azure and healthy?
4. How do I change normal weekly capacity safely?
5. How do I make a temporary change without rewriting the schedule?

The experience should feel like editing business hours and service levels, not editing cloud
infrastructure.

## 4. Users and permissions

### Platform administrator

Can edit, validate, save, apply, and temporarily override a schedule. Every mutation still
requires backend authorization and an audit reason.

### View-only Settings user

Can inspect the schedule, validation, observed state, and diagnostics. The page shows a concise
“View only” badge and explains that a platform administrator must make changes. Disabled controls
must not be rendered as though the user could eventually unlock them.

### Ordinary user

Has no Scheduling management access. Existing navigation authorization remains unchanged.

## 5. Information architecture

The page has four layers, in this order.

### 5.1 Status header

Always visible at the top:

- **Active now:** Business hours, Off hours, Disabled, or Temporary override.
- Selected timezone and current local time.
- Next transition in plain language, for example “Switches to off-hours capacity today at 8:00 PM.”
- Application state: **Applied**, **Saved changes not applied**, **Applying**, **Drift detected**, or
  **Could not verify Azure**.
- Primary administrator action: **Edit schedule**.
- Secondary action: **Temporary override**.

If the schedule is disabled, the header says which capacity source remains authoritative instead
of merely showing a “Disabled” chip.

### 5.2 Weekly schedule summary

Show a human-readable sentence before the detailed table:

> Monday–Friday, 6:00 AM–8:00 PM Pacific Time. Off-hours capacity applies at all other times.

Show business-hours and off-hours capacity as two visually distinct cards. Each service row uses:

- service name;
- warm baseline;
- maximum under queue demand;
- observed Azure range when available;
- a short explanation of zero or one-replica consequences where relevant.

Technical scaler and attribution details remain available under a collapsed **Diagnostics**
section. A routine user should not have to read them to manage a valid schedule.

### 5.3 Management workspace

Selecting **Edit schedule** opens an inline workspace or side sheet with three steps:

1. **When** — enablement, timezone, days, start/end, holidays.
2. **Capacity** — business-hours baseline, off-hours baseline, queue maximums.
3. **Review & apply** — impact summary, validation, audit reason, save/apply actions.

The user can move backward without losing edits. Closing with unsaved changes requires a discard
confirmation. Reopening starts from the latest server snapshot, never a stale local draft.

### 5.4 Temporary override

Temporary override is visually separate from the normal weekly schedule. It uses a short guided
dialog:

1. Choose **Business-hours capacity**, **Off-hours capacity**, or **Custom capacity**.
2. Choose duration or “until the next scheduled transition.”
3. Review affected services and estimated impact.
4. Enter a required reason and confirm.

An active override is shown in the status header with actor, reason, expiry countdown, and a
clearly labeled **End override** action. Ending it confirms which saved schedule resumes.

## 6. Interaction requirements

### 6.1 Time and recurrence

- Replace free-form timezone entry with a searchable timezone selector.
- Present common choices using recognizable labels such as “Pacific Time — Los Angeles,” while
  storing the canonical IANA value.
- Use seven toggle buttons for weekdays with full accessible names.
- Use locale-aware time controls while preserving 24-hour values in the API.
- Show a live sentence summarizing the recurrence.
- Explain overnight windows and reject equal start/end times before submission.
- Handle daylight-saving transitions using the selected timezone, as today.

### 6.2 Holidays

- Replace comma-separated input with a date picker and removable date chips.
- Reject duplicates and malformed dates immediately.
- Explain the known Azure cron limitation beside the control.
- If holidays cannot be faithfully applied, show the required operational follow-up in Review.

### 6.3 Capacity controls

- Use a single row per service with three labeled numeric steppers: **Warm during business hours**,
  **Warm off hours**, and **Maximum when busy**.
- Enforce non-negative integers.
- Prevent a warm baseline from exceeding its maximum.
- Provide “Use recommended defaults” per row and for the whole table.
- Explain that maximum is a ceiling for queue-driven scale-up, not the normal running count.
- Show estimated vCPU and database connections as calculated outcomes, not editable fields.
- Keep Redis, PostgreSQL, secrets, and raw Azure configuration out of this UI.

### 6.4 Validation

- Revalidate automatically after a short pause when the draft changes.
- Keep an explicit **Check schedule** action for keyboard and recovery use.
- Display blocking problems beside the relevant field and in a Review summary.
- Display warnings separately from blockers.
- Use plain consequences: “Assess cannot scale above 5” or “This could require 17 more database
  connections than available.”
- Never label a schedule safe if quota or Azure state could not be checked; show “Needs review.”
- Server-side validation remains authoritative on every save and apply.

### 6.5 Save and apply

The workflow distinguishes two durable states:

- **Save draft:** records schedule intent and audit history but does not change Azure.
- **Apply to Azure:** publishes the saved version after validation and a confirmation summary.

The Review step shows both actions with their consequences. After saving a new version, the page
must not imply it is active. The primary next action becomes **Apply saved schedule**.

Applying shows progress and ends in one of four explicit outcomes: applied successfully, applied
with warnings, rejected before changes, or failed with the previously applied policy retained.
The UI re-reads the server after either action; it never renders an optimistic applied state.

Every save and apply requires a plain-language reason. A user may reuse the save reason when
applying the exact same version.

### 6.6 Concurrency and recovery

- Carry the snapshot version through save and apply.
- On a version conflict, show who changed it and when when the API provides those facts.
- Offer **Review latest version**; never silently overwrite.
- Bound reads and mutations. A failed read shows Retry; a failed mutation states that no change
  was confirmed.
- Preserve a local draft across a transient validation failure, but not across account or
  workspace changes.

## 7. Responsive behavior

- Desktop: summary cards and capacity columns may share rows.
- Tablet: editor remains a single readable column; actions stay visible at the bottom.
- Mobile/narrow modal: replace capacity tables with service cards. No horizontal scrolling is
  required to edit a schedule.
- The account menu must not obscure primary Scheduling actions; opening Scheduling dismisses an
  idle account menu where applicable.

## 8. Accessibility

- All controls are keyboard operable with a visible focus indicator.
- The edit workflow has a programmatic heading and step status.
- Toggle groups expose selected state and full day names to assistive technology.
- Validation messages associate with their fields and are summarized in an alert region.
- Status is never communicated by color alone.
- Busy actions expose progress and prevent duplicate submission.
- Focus moves to the first blocking error after validation and returns predictably after dialogs.
- Touch targets meet the product's minimum target-size standard.
- The page remains usable at 200% zoom and at a 320 CSS-pixel viewport.

## 9. Audit and telemetry

Continue recording actor, timestamp, reason, prior and requested values, outcome, and correlation
ID for every mutation. Add product telemetry for editor opened, validation outcome, save outcome,
apply outcome, override created/ended, version conflict, and abandoned dirty draft. Do not include
schedule reasons or other user-entered text in analytics.

## 10. Non-goals

- Scheduling scans, assessments, or remediation runs.
- Replacing Monitor → Scheduled re-scans.
- Editing database, Redis, secrets, or Azure credentials.
- Automatically buying quota or resizing PostgreSQL.
- Giving view-only users mutation controls.
- Hiding validation or infrastructure consequences behind simplified language.

## 11. Acceptance criteria

1. An administrator sees clear **Edit schedule** and **Temporary override** actions above the fold.
2. A view-only user sees the active policy and an explicit view-only explanation, with no mutation
   controls.
3. The editor guides the user through When, Capacity, and Review & apply.
4. Timezone uses a searchable labeled selector and persists an IANA identifier.
5. Active days and hours produce a live plain-language schedule summary.
6. Holidays are added as validated dates and removable chips, not comma-separated text.
7. Every service exposes business-hours warm, off-hours warm, and busy maximum values with clear
   definitions.
8. Invalid numeric relationships are identified at the affected service before submission.
9. Validation updates as the draft changes and distinguishes blockers, warnings, and unavailable
   checks.
10. Estimated database and vCPU impact is visible before saving or applying.
11. Saving does not claim Azure changed; it produces a visible “Saved changes not applied” state.
12. Applying requires confirmation, validation, authorization, version, and reason.
13. A successful apply is confirmed by a fresh server read and observed policy state.
14. A version conflict cannot overwrite another administrator's change.
15. Temporary overrides show capacity, duration, actor, reason, expiry, and the policy that resumes.
16. A failed or timed-out request always offers recovery and never leaves an endless loading state.
17. The management experience is usable by keyboard, screen reader, at 200% zoom, and at 320 CSS
   pixels without horizontal editing scroll.
18. DOM-level tests cover administrator and view-only states, step navigation, dirty-close
   confirmation, automatic validation, field errors, save/apply distinction, conflicts, overrides,
   request recovery, focus behavior, and responsive service cards.

## 12. Delivery plan

### Phase A — Structure and clarity

Introduce the status header, summary cards, Diagnostics disclosure, explicit access state, and
responsive service presentation without changing API behavior.

### Phase B — Guided editing

Replace the dense editor with the three-step workspace, timezone selector, weekday toggles, date
chips, capacity steppers, automatic validation, and dirty-close protection.

### Phase C — Save/apply workflow

Expose saved-versus-applied state and the existing application operation as an explicit reviewed
workflow. Add server fields only where the current contract cannot support truthful progress or
conflict messaging.

### Phase D — Overrides and hardening

Add the guided override dialog, responsive and accessibility verification, telemetry, recovery
states, and a staging exercise covering save, apply, transition, override, expiry, and rollback.

