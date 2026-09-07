# Scheduling completion backlog

Updated: 2026-09-07

This is the working backlog for Settings → Scheduling. Items are ordered by operator risk, then
usability. A completed item is backed by a merged change and production verification; an open
item must carry its own regression test before merge.

## Completed

- [x] Load the scheduling tab reliably and expose retryable read failures.
- [x] Provide guided weekly-hours, service-floor, maximum, holiday, and reason controls.
- [x] Detect the user's IANA timezone, offer **Use my timezone**, preserve wall-clock times, and
  explain daylight-saving behavior.
- [x] Validate drafts before save or apply and prevent an unsaved draft from publishing a
  different saved version.
- [x] Apply only to the exact five-app production fleet through an explicit deployment opt-in and
  narrowly scoped managed-identity permissions.
- [x] Provide bounded custom and preset temporary overrides with confirmation and automatic
  expiry.
- [x] Reconcile overrides and local-date holiday exceptions durably, with retry/backoff, audit
  records, cross-replica exclusion, and automatic restoration of the published schedule.
- [x] Show reconciliation state and disable overrides until Azure application is available and
  the current schedule is applied.
- [x] Bound all scheduling mutations and discard stale asynchronous validation results.

## Remaining polish

- [x] Refresh reconciliation progress after an override, holiday transition, retry, or restore so
  an administrator does not have to close and reopen Settings to see the final state.
- [x] Render reconciliation state as plain-language outcomes with a clear retry/review action for
  partial, failed, stale, or backoff states; reserve raw state names for diagnostics.
- [ ] Label all transition, override-expiry, and reconciliation timestamps with the viewer's
  timezone, while retaining the schedule timezone beside schedule wall-clock fields.
- [ ] Separate custom-override floor inputs from the weekly schedule draft so the interaction
  model cannot imply that temporary values edit saved business-hours capacity.
- [ ] Add an explicit success acknowledgement after save, apply, override, and restore instead of
  closing the editor with no durable confirmation.
- [ ] Add DOM-level accessibility coverage for keyboard order, focus return, status announcements,
  validation associations, and confirmation dialogs across the complete scheduling workflow.
- [ ] Add a production-safe read-only verification that compares the effective schedule,
  reconciler desired key, and observed Azure scale blocks without triggering a write.

## Deferred by design

- [ ] Automatic vCPU quota blocking remains unavailable until Azure exposes an applicable
  Container Apps consumption-core quota for this subscription. The product must continue to say
  **not checked** rather than substitute an unrelated quota.
