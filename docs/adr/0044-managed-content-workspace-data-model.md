# ADR 0044 — ACP Managed Content Workspace: the workspace/document/version data model

Status: **Proposed** (workspace table implemented this PR; document/version tables are Phase
1's next slice, described here so that work has an agreed target) · Date: 2026-08-30 ·
Related: [ADR 0003](0003-document-lifecycle-model.md), [ADR 0010](0010-remediated-output-object-store.md)

## Context

The PRD "ACP Managed Content Workspace" (Draft) asks for a self-contained upload → store →
Discover → Assess → Remediate → Review → Release path that does not depend on a connected
Drive or SharePoint session. Its own delivery plan (§33) starts with **Phase 1 — Secure upload
and storage**, which bundles eight things: workspace model, direct upload, staging/
verification, immutable Blob versions, document metadata, upload progress, download original,
retention baseline.

Everything else in Phase 1 needs somewhere to attach to — a workspace, and a document/version
identity within it. Before writing that code, two things needed settling, because getting
either wrong is expensive to unwind once documents and Blob paths exist against it:

**1. Does a workspace's document/version model reuse the existing `documents` table (ADR 0003),
or is it a new concept?**

Checked against `origin/main`: `documents.doc_id` is defined as "source + path hash, or
drive_file_id" (ADR 0003) — identity derived from a CONNECTOR listing (drive/sharepoint/local),
upserted by a scan. `scan_inventory` and `file_records` are similarly scan-shaped: a row exists
because a `_list()` call over an external source produced it. None of the three has a concept
of "an immutable version a user uploaded directly, with no scan and no source connector at
all." Forcing the PRD's upload flow through them would mean either inventing a fake `source`
value and a fake per-upload "scan," or loosening `doc_id`'s identity contract for a case ADR
0003 never anticipated. Both are worse than a new, small set of tables.

**2. Does "customer-isolated" (PRD §10, §29) need a new tenant concept, or does today's
`owner_email` convention already cover it?**

`api/store.py:636`: *"`owner_email` is the ACP tenant identifier until a first-class tenant_id
column is added."* That convention is load-bearing throughout the codebase already — every
per-user isolation boundary in this app (scans, documents, campaigns, org_memory, HITL) is
`owner_email`-scoped, not `tenant_id`-scoped, and `test_foreign_scan_404.py` pins the resulting
behavior (a foreign id 404s, never 403 — an id must not be an existence oracle across owners).
Introducing a parallel `tenant_id` concept for just this one feature would mean two isolation
boundaries in the same app disagreeing about what a "tenant" is, for a distinction (multiple
human users under one paying customer) the PRD's own target-user list does not actually
describe — every listed role (document owner, accessibility specialist, program manager,
platform administrator) already exists in today's single-`owner_email`-per-account model.

## Decision

**New tables, not a reuse of `documents`/`scan_inventory`/`file_records`.** A workspace's
document is a fundamentally different object: it has no source connector, its identity is
"the bytes a user handed us," and its versions are immutable by construction (PRD §11) rather
than a scan's point-in-time snapshot. Bridging to ADR 0003's `documents` table for governance/
disposition reuse is a real, future question (Phase 2's "Blob-backed Discover" will have to
answer how — or whether — a workspace document ever becomes visible to the *existing*
Discover/Assess pipeline) but is explicitly **out of scope for this ADR**, the same way ADR
0003 itself was "the prerequisite for [governance] work; it does not implement the features
themselves."

**`owner_email` is the tenant boundary, reused as-is.** A workspace is created by, and scoped
to, one `owner_email` — the same identifier every other per-user boundary in this app already
uses. No new `tenant_id` column. If a real multi-user-per-customer requirement appears later
(the PRD does not currently ask for one — the "document owner" / "accessibility specialist" /
"program manager" / "platform administrator" roles in §6 read as roles one signed-in account
can hold, not as separate logins sharing one company's data), it is a separate ADR, at which
point every existing `owner_email`-scoped boundary in this app — not just this one — needs the
same answer. Solving it once, narrowly, here would leave the rest of the app inconsistent with
whatever gets decided.

### Schema (Phase 1)

```
content_workspaces                          -- THIS PR
  id                     TEXT PRIMARY KEY    -- uuid4().hex[:12], matching campaign_id/scan_id
  owner_email            TEXT NOT NULL       -- the tenant boundary (see above)
  name                   TEXT NOT NULL
  purpose                TEXT
  business_owner         TEXT                -- PRD §7's free-text "owner" field — NOT owner_email.
                                              -- Named business_owner specifically so nobody reading
                                              -- this table confuses it with the tenant column next to it.
  department             TEXT
  wcag_standard          TEXT                -- e.g. "WCAG 2.1 AA"
  retention_policy       TEXT                -- free text for now (PRD §28's policies: delete-after-N,
                                              -- retain-until-manual, legal-hold, ...); enum once Phase 5's
                                              -- retention engine is built and needs to branch on it
  permitted_file_types   TEXT                -- JSON array, e.g. ["pdf","docx"]
  due_date               TEXT
  project                TEXT
  processing_region      TEXT
  external_ai_policy     TEXT                -- free text; PRD §22's actual on/off gate is a separate,
                                              -- later control, not decided here
  status                 TEXT DEFAULT 'active'  -- active | archived (soft-delete, PRD retention flows)
  created_at             TEXT
  updated_at             TEXT

content_workspace_documents                 -- NEXT SLICE (upload), described here for the record
  id                     TEXT PRIMARY KEY
  workspace_id           TEXT NOT NULL       -- FK content_workspaces.id (app-level, no FK constraint —
                                              -- matches this codebase's existing convention of app-
                                              -- enforced references over DB FKs, e.g. scan_inventory.scan_id)
  owner_email            TEXT NOT NULL       -- denormalized from the workspace, same pattern
                                              -- scan_inventory/documents already use for isolation checks
                                              -- that don't want a join
  display_name           TEXT                -- current filename; PRD §11 says a version records its OWN
                                              -- original_filename too, since a re-upload could rename
  relative_path          TEXT                -- folder path preserved from a folder/ZIP upload
  status                 TEXT                -- PRD §8's upload states: preparing|uploading|verifying|
                                              -- scanning|ready|duplicate|unsupported|quarantined|failed|cancelled
  created_at             TEXT
  updated_at             TEXT

content_workspace_document_versions         -- NEXT SLICE (upload)
  id                     TEXT PRIMARY KEY
  document_id            TEXT NOT NULL
  version_seq            INT NOT NULL        -- 1, 2, 3 — PRD §12's "upload as a new version"
  content_hash           TEXT NOT NULL       -- PRD §12 duplicate detection, §16 hash-before-reuse
  mime_type              TEXT
  size_bytes             INT
  blob_path              TEXT                -- opaque key (PRD §10: "use opaque IDs as Blob keys") —
                                              -- see Blob layout below
  original_filename      TEXT                -- protected metadata (PRD §10), not the Blob key itself
  uploaded_at             TEXT
  uploaded_by             TEXT
  malware_status          TEXT
  lifecycle_state         TEXT                -- ready | quarantined | deleted | ...
  assessment_status       TEXT
  source_version_id       TEXT                -- the assessed version a remediation was produced from
  remediated_from_version_id TEXT
  release_status          TEXT
  retention_date          TEXT
```

`content_workspace_documents`/`content_workspace_document_versions` are not created by this
PR — no upload mechanism exists yet to populate them, and an empty table nobody writes to is
worse than no table (CLAUDE.md's own standing rule on orphaned surfaces applies to schema too).
They are specified here so the upload PR implements against an agreed shape rather than
inventing one under time pressure.

### Blob layout (for the upload PR, not implemented here)

Matches PRD §10 exactly, with `owner_email` standing in for `{tenant_id}`:

```
workspace/{owner_email}/{workspace_id}/{document_id}/source/{version_id}/original
workspace/{owner_email}/{workspace_id}/{document_id}/remediated/{version_id}/artifact
workspace/{owner_email}/{workspace_id}/{document_id}/previews/{version_id}/...
workspace/{owner_email}/{workspace_id}/{document_id}/reports/{assessment_id}/...
workspace/{owner_email}/{workspace_id}/{document_id}/release/{release_id}/artifact
```

**Not `api/blob.py`.** That module is ADR 0010's remediated-output store, and its own
docstring scopes it OUT of general use: *"Scoped to remediated-output artifacts only — not a
general file-storage abstraction (ADR 0010's own non-goals)."* Its container
(`ACP_BLOB_CONTAINER`, default `remediated`) also holds an unrelated shape — `{owner_email}/
{scan_id}/{filename}` — a scan's remediated output, not a workspace's uploaded original. A new
module (working name `api/workspace_blob.py`) mirrors `api/blob.py`'s pattern exactly —
`DefaultAzureCredential` managed-identity auth, a no-op when `ACP_WORKSPACE_BLOB_ACCOUNT` isn't
set, its own container (`ACP_WORKSPACE_BLOB_CONTAINER`, default `workspace-content`) — rather
than overloading ADR 0010's module or its container.

## Consequences

- **Schema**: one new table this PR (`content_workspaces`), additive, no migration risk to
  existing tables. Two more tables specified but not created until the upload PR.
- **No new isolation model.** `owner_email` stays the one tenant boundary across the whole app;
  `GET /content-workspaces/{id}` 404s (never 403) for a foreign id, matching
  `test_foreign_scan_404.py`'s established contract.
- **A real open question deferred, not solved by omission**: whether/how a workspace document
  ever becomes visible to the existing Discover/Assess pipeline (`scan_runs`/`scan_inventory`)
  is Phase 2's problem. This ADR takes no position beyond "not via the `documents` table as it
  exists today" (see Decision).
- **Naming**: `content_workspaces`/`api/routes/content_workspaces.py`, not `workspaces`, to stay
  unambiguous next to the existing, unrelated `api/routes/workspace.py` (`GET /workspace/
  bootstrap` — the app-shell initial-load optimization, nothing to do with this PRD).
