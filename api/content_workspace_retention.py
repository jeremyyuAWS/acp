"""ACP Managed Content Workspace (ADR 0044) — retention sweep, PRD §28.

Same shape as sweeper.py's run_sweep(): a pure, store-injected function, safe to call
repeatedly and concurrently, that a background thread (or a cron trigger) calls once per tick.
Kept as its own module rather than folded into sweeper.py — that module's docstring scopes it
to job-queue reconciliation (ADR 0004 step 5), a different concern from document retention,
and mixing them would make either harder to reason about on its own.

This is a BASELINE: it expires whatever content_workspace_document_versions.retention_date is
already set (an ISO-8601 string, comparable lexically against store._now()'s own format), but
nothing yet computes that column FROM a workspace's retention_policy — that mapping (what
"90 days" or a named policy actually means as a date) is a separate, later piece of work. Until
that exists, this sweep has nothing to do and returns all-zero counts, which is the correct,
inert behavior for a baseline with no inputs yet rather than a bug.

"Expiring" a version here means: best-effort delete its blob (workspace_blob.delete_document_
version — failure is not fatal, matching every other blob write/delete in this codebase) and
flip its lifecycle_state to "expired" in place. The DB row itself is never deleted — retention
here means the bytes stop being retrievable, not that the audit trail disappears, matching this
whole table's write-once-then-flip-state pattern (see e.g. the quarantine and duplicate states).
"""
from __future__ import annotations


def run_content_workspace_retention_sweep(store, *, as_of: str | None = None) -> dict[str, int]:
    """Run the sweep once. Returns {"versions_expired", "blobs_deleted"} — the two can differ
    (blobs_deleted <= versions_expired) when a blob was already gone or blob storage isn't
    configured; that's an expected, non-error outcome, not a partial failure."""
    import workspace_blob

    expired = store.list_expired_content_workspace_document_versions(as_of=as_of)
    blobs_deleted = 0
    for version in expired:
        if workspace_blob.delete_document_version(
                version["owner_email"], version["workspace_id"], version["document_id"],
                version["id"]):
            blobs_deleted += 1
        store.update_content_workspace_document_version_lifecycle_state(version["id"], "expired")

    result = {"versions_expired": len(expired), "blobs_deleted": blobs_deleted}
    if result["versions_expired"]:
        print(f"[content_workspace_retention] tick: versions_expired={result['versions_expired']} "
              f"blobs_deleted={result['blobs_deleted']}", flush=True)
    return result
