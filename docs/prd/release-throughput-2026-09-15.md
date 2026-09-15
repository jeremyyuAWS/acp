# Release throughput: isolated workers and immediate bounded publishing

## Problem
Release continuation currently competes with remediation, wakes every 20 seconds, and serializes SharePoint dispatch behind a scan-wide release batch. Observed remediation took about 7.5 minutes; seven-second uploads were spaced about 25 seconds apart.

## Requirements
1. Continue PR2078: dedicated private Release worker capacity, reserved delivery/report slots, opt-in routing, guarded environment provisioning, heartbeat and version checks. Start with one replica and three slots (two delivery, one report); document staging-first rollout and rollback.
2. On durable remediation/write/rescore or publishing completion, wake the saved automatic permission immediately. Coalesce duplicate events into its existing queued continuation; retain recovery polling for missing events and restarts. Stop, expiry, source revision, current approval and exact artifact checks remain authoritative.
3. Admit at most two outstanding automatic uploads per permission, counting queued, running and provider retry jobs. Append SharePoint work only to an execution owned by the same permission and release. Preserve job/work-item identities, explicit reconnect/resume, receipt reservations and throttling; never adopt an unrelated or cancelled/paused execution.

## Validation and rollout
Offline fixtures must cover immediate wake, event replay, Stop, overlapping dispatch, the two-job bound, unrelated intent, changed artifact and receipt reuse. Run focused suites, repository guards and required PR CI. No model evaluations, production uploads, merge or deployment in this task. Parent coordinates staging verification and production rollout after all parallel tasks and scans settle.
