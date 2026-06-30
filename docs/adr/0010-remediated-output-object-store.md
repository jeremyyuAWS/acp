# ADR 0010 — Azure Blob as the remediated-output store (Drive write becomes opt-in)

Status: **Proposed** · Date: 2026-06-30 · Related: [ADR 0005](0005-server-side-remediation.md)

## Context
Server-side remediation (ADR 0005) writes the corrected copy back to the user's Drive, into
a `Remediated/` folder, via `POST /drive/upload` (`api/routes/drive.py`). That write uses the
per-user GIS token under the `drive.file` scope — Google's narrowest write scope, which only
lets ACP touch files it created itself (never the user's existing documents). Two problems
fall out of "Drive is the only place a remediated file ever lives":

1. **Write access isn't guaranteed.** Some orgs restrict OAuth write scopes for compliance
   tooling, or only grant ACP the read-only `drive.readonly` scope used for scanning. Today
   that means remediation silently can't run — `drive_upload` 401s with "No Drive token", and
   there's no fallback.
2. **No durable artifact independent of the user's Drive.** The remediated copy lives only in
   the user's own folder structure — if they rename/move/delete `Remediated/`, or revoke
   Drive access entirely, ACP has no record of what it produced. The audit trail (`/healthz`,
   `decision_log`, the PDF report) references a `drive_write_url` that can go stale.

This came up directly: *"what do we need to allow server-side remediation to work — should we
store in our own object store to get around the write permissions?"*

## Decision
Add **Azure Blob Storage** as the primary remediated-output store; Drive write-back becomes an
**opt-in mirror**, not a requirement.

1. **New `StorageProvider`-shaped seam** (mirrors the movate-cli adapter-Protocol convention
   ACP itself follows for `api/store.py`'s SQLite/Postgres split): `api/blob.py` wraps
   `azure-storage-blob`, one container (`ACP_BLOB_CONTAINER`, default `remediated`), blob path
   `{owner_email}/{scan_id}/{filename}`. Auth via the Container App's existing managed
   identity — no new secret to provision or rotate.
2. **`emit_remediation_span`'s write step** (currently Drive-only, `api/core.py`) tries the
   blob upload first — always available, no per-user token needed. `file_records` gains a
   `blob_url` column (additive, mirrors the existing `drive_write_url` migration pattern) so a
   file can carry both a blob URL and (optionally) a Drive URL.
3. **Drive write-back stays available, opt-in.** If the user has granted `drive.file` write
   scope, remediation ALSO uploads to `Remediated/` as today (now best-effort: failure there no
   longer fails the whole remediation, since blob already has the durable copy). Users who
   only granted read access still get a fully working remediation pipeline — they download
   from blob instead of finding it in their Drive.
4. **Download surface**: `GET /scans/{sid}/files/{file}/remediated` streams from blob (new
   route) — replaces the current "open `drive_write_url`" link in `FileDrawer`/`BeforeAfter`
   wherever a blob copy exists, with the Drive link as a secondary "also in your Drive" option
   when present.
5. **Retention**: same lifecycle as the rest of a scan's data — no new deletion policy. Listed
   under `reset_analytics`'s scope only if explicitly added; default is keep (it's the actual
   compliance deliverable, not a cache).

## Why Azure Blob (not, say, S3-compatible or a DB blob column)
- **Already in the deploy footprint** — same RG/subscription as the Container App, Postgres,
  and Langfuse; one more managed identity grant, not a new vendor relationship.
- **Not Postgres** — remediated documents are binary, can be MB-sized (PDFs/Office files), and
  have no query/join need; a DB `BYTEA` column would bloat backups and slow every unrelated
  `pg_dump`. Blob is the right shape for "write once, stream out the original bytes."
- **Managed identity, no token to leak/expire** — unlike the Drive `drive.file` token (per-user,
  expires, requires re-consent), the Container App's own identity writes directly; nothing
  user-session-scoped is needed for the upload itself.

## Consequences
- **Schema**: additive `file_records.blob_url TEXT` column (CREATE TABLE + ALTER migration,
  same pattern as `acp_stamped`/`checksum`). No backfill needed — NULL for pre-ADR scans.
- **New dependency**: `azure-storage-blob` (MIT-licensed — passes the license gate). Container
  App needs a `Storage Blob Data Contributor` role grant on the storage account; one
  `deploy.sh` change (analogous to the existing Postgres/Langfuse inherit-on-redeploy guard).
- **Remediation no longer hard-fails for read-only-Drive orgs** — the headline win.
- **Slightly larger blast radius on the remediation write path**: two write targets (blob
  always, Drive conditionally) instead of one. Mitigated by making blob the one that must
  succeed and Drive best-effort (point 3).

## Non-goals
- Replacing Drive/SharePoint as the **scan source** — this ADR is output-only.
- A general-purpose file-storage abstraction for the whole app — scoped to remediated-output
  artifacts. If a second use case appears (e.g. PDF report archival), it can reuse `api/blob.py`
  without a new ADR, since the seam already exists; a *third*, structurally different use would
  warrant revisiting.
- Cross-region replication / lifecycle tiering — single-region, standard tier, matches the
  rest of ACP's current Azure footprint.

## Open questions for review
- Container naming / RBAC scope: one shared container path-prefixed by owner (as drafted), or
  one container per environment (dev/demo/prod) — affects the `deploy.sh` provisioning step.
- Should the Drive mirror upload move to a background job (so it can't slow down the
  user-facing remediation response) now that it's no longer the source of truth?
