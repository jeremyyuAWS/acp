# Automatically release files when ready

Automatic release is off unless the signed-in owner explicitly authorizes an
already-admitted Remediate run, its exact selected files and destination. It is
separate from AI or human approval: enabling it neither approves proposals nor
applies changes. New proposals still follow their normal review, application and
verification paths. A new run or selection never inherits an older authorization.

The first implementation supports tracked SharePoint and Google Drive sources.
Every selected file requires its provider identity and assessed modification
metadata; unsupported or incomplete inputs produce an explicit unavailable
reason. The destination remains in the source provider and is frozen along with
the existing or newly chosen Release folder. The authorization expires after
24 hours. Progress and scheduled work live in the database, so closing the browser
does not cancel or duplicate delivery.

The read-only `GET /scans/{sid}/release/automatic?files=a&files=b` returns
`available`, `reason`, current `run_id`, `destination`, `destination_label` and the
current run's `authorization` (or null). It keeps that authorization inspectable
when the displayed file selection changes, allowing the owner to stop the original
scope. It does not present a previous run as enabled. Opening or refreshing the
page creates no authorization, job, approval or provider write.

`POST /scans/{sid}/release/automatic` takes `run_id`, `files`, the destination from
preview, and a unique `request_id`. It returns an authorization containing `id`,
`status`, frozen `files` and `run_id`, destination, `expires_at` (ISO UTC), revision,
`progress` counts (`published`, `pending`, `blocked`, `failed`) and file details.
Replaying the same request returns the same durable permission, including after
it is stopped; changing its scope or destination is rejected. Only one active
authorization can exist for the same owner/scan/run.

`POST /scans/{sid}/release/automatic/{id}/stop` atomically prevents future automatic
dispatch permits. Queued SharePoint jobs recheck the authorization before entering
the existing publication handler. A delivery already admitted before Stop may
finish; its exact receipt stays visible without reactivating permission. Manual
Release remains a separate action and authority.

The worker uses the existing `release_continue` job type with explicit automatic
mode, so there is no new scaler or capacity requirement. Each tick admits at most
one new document, waits while a release stage is active, then schedules a bounded
successor. It rechecks owner grants, admitted run membership, assessment identity,
source identity, document selection, per-file job completion, current reviews,
applied approvals and a compliant verified corrected artifact. The normal
publisher independently verifies actual bytes, source freshness, destination,
side-effect reservation and receipt. Automatic authority is included in queued
payloads and their execution fingerprint; stopped automatic jobs cannot silently
become the authority for a later manual retry.

The first delivery admission freezes its exact artifact. Concurrent ticks cannot
admit it twice. Later versions or unknown delivery outcomes require reconciliation
and a fresh explicit authorization, not blind automatic retry. A queued worker can
reuse the normal idempotent provider receipt. Published progress requires an exact
durable artifact/destination receipt, not a request being accepted or a model
claim. Duplicate ticks can schedule only one successor under the durable tick
revision fence; independent delivery progress does not invalidate that successor.

Schema 50 adds owner-scoped `automatic_release_authorizations`, including immutable
request intent, progress, status, revision and stop time. Owner/scan erasure
includes the new records. Tests use isolated databases and synthetic providers;
no customer approvals, files or publications are performed by development tests.


The status response also includes a read-only `planning` object with `available`,
`reason`, sorted `files`, `source_revision`, `destination`, and `destination_label`.
It validates the owned, selected assessment records and release grant without
requiring an accepted remediation run, calling a provider, or recording consent.
The existing top-level availability and authorization remain scoped to an accepted run.

A Plan choice becomes permission only through an explicit authorization POST after
Start returns its accepted execution ID. Callers may bind that choice with
`expected_source_revision`; a mismatch with the accepted run is rejected. Public
authorization includes `request_id` and `source_revision` so a lost response can be
reconciled against the exact submitted request without choosing a different run.
