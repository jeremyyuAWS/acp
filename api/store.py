"""SQLite (local / test) + Postgres (deploy) persistence for scan results.

Set DATABASE_URL=postgresql://user:pass@host:5432/dbname to use Postgres.
Without it, falls back to a local SQLite file — convenient for local dev.

Postgres is the target for the live demo: it handles concurrent scans without
serializing writes and survives container restarts across all replicas.
"""
from __future__ import annotations
import contextlib
import json
import logging
import os
import re
import time
import sqlite3
import uuid
from pathlib import Path

from swallowed import swallowed

logger = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get("DATABASE_URL")
_SQLITE_PATH = Path(__file__).resolve().parent.parent / "acp.db"

# Friendly source labels for the "By source system" breakdown (get_scan). Mirrors
# lf._SOURCE_LABEL; duplicated rather than imported to avoid store.py depending on lf.py
# for 3 strings.
_SOURCE_LABEL = {"drive": "Google Drive", "sharepoint": "SharePoint / OneDrive", "local": "Local upload"}

# Mirrors pii._SEV_RANK; duplicated (not imported) for the same reason as _SOURCE_LABEL —
# find_by_checksum needs it to recompute the rolled-up severity for a copied PII summary.
_PII_SEV_RANK = {"critical": 3, "moderate": 2, "low": 1}

# WCAG issue severity (issue_records.severity / config/rule-catalog.json) — a DIFFERENT
# vocabulary from the PII one above (these are uppercase, PII's are lowercase). Used by
# get_scan_diff to pick the worst severity when a SC's findings are mixed.
_ISSUE_SEV_RANK = {"CRITICAL": 4, "SERIOUS": 3, "MODERATE": 2, "MINOR": 1}


def _parse_worker_tier_heartbeat(raw: str) -> tuple[str, int | None, str | None]:
    """Split a `worker_tier_heartbeat` setting value into (iso_timestamp, pool_size, version).

    Formats have to coexist across a rolling deploy: the OLD bare ISO string (`worker_main.py`
    before the envelope landed, or any value written before it) and the JSON envelope
    `{"at": "<iso>", "pool_size": <int>, "version": "<calver>"}`. Any mix of pre- and
    post-rollout API and worker must keep working — so this tries JSON first and falls back to
    treating `raw` itself as the bare timestamp whenever it isn't a `{"at": ...}` dict. Every
    optional field is None when the format is older, or when the envelope omits or mistypes it —
    never a crash.

    WHY `version` IS HERE. It is the only way to find out which image the worker tier is running.
    The API tier answers that about ITSELF on /healthz, but acp-worker has NO INGRESS — nothing
    can be asked of it directly — and the heartbeat carried only a timestamp and a pool size, so
    "did the worker actually take the deploy?" had no answer at all from outside the cluster.
    That question is not academic: app and worker deploy from different images with nothing
    sequencing them (ADR 0045 §6), so they are routinely, briefly, on different code.

    The `worker_instances` table would have carried this properly (it has `revision_name` and
    `software_version` columns) but has NO WRITER — deliberately, as PR 1 of a 5-PR plan whose
    emit sites are explicitly deferred for human review. This does not pre-empt any of that: it
    adds one string to an envelope that already exists.

    None and "dev" are DIFFERENT ANSWERS and must not be collapsed. None means the beat came from
    a worker that predates this field — the deploy has not reached the worker tier, which is
    itself the answer somebody was looking for. "dev" means the worker is running an image that
    never went through deploy.sh, matching what /healthz reports for the API tier so the two are
    directly comparable strings.

    A module-level function, not a method: test_readiness.py's FakeStore borrows
    `worker_tier_status`/`worker_tier_alive` straight off the real class without instantiating
    it as a full Store, so this must not depend on `self`.
    """
    pool_size: int | None = None
    version: str | None = None
    iso = raw
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    if isinstance(obj, dict) and "at" in obj:
        iso = obj["at"]
        ps = obj.get("pool_size")
        if isinstance(ps, int) and not isinstance(ps, bool):
            pool_size = ps
        v = obj.get("version")
        if isinstance(v, str) and v.strip():
            version = v.strip()
    return iso, pool_size, version


def _issue_location(i: dict) -> str | None:
    """Where a finding is, from either of the two keys detectors use for it.

    TWO NAMES FOR ONE COLUMN, AND ONE OF THEM WAS BEING DROPPED. The vendored .NET rules write
    `location` ("docx:hyperlink:paragraph:115:url:…"). Several first-party Python detectors write
    `locator` ("word/header1.xml#Picture 1") — see formats/docx/detectors/non_text_content.py.
    Both INSERTs below persisted `i.get("location")` only, so every Python-detected finding was
    stored with location NULL and its position was lost at the database boundary. The finding
    survived; the ability to point at the thing it is about did not, which is what a review card
    reads.

    Measured, not inferred: saving one .NET finding and one Python finding through
    save_file_result stored "docx:image:3" for the first and NULL for the second.

    NOT a rename, and that distinction is why this is a fallback rather than a merge. The two
    keys are not synonyms elsewhere: a `locator` is a RESOLVABLE WRITE TARGET that
    apply_alt.parse_locator turns back into an element, while `location` is a position string for
    a human. On a FINDING they answer the same question, and the locator is the better answer
    because it is resolvable — so it is used when `location` is absent, and nothing that consumes
    `locator` as a write target is touched.

    One accessor, used by both INSERT sites, so the fallback cannot be applied at one and
    forgotten at the other — which is the shape of the bug it fixes.
    """
    return i.get("location") or i.get("locator")

# Schema is identical between SQLite and Postgres (UPSERT syntax is the same).
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS scan_runs (
      id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, source TEXT,
      rubric_name TEXT, rubric_hash TEXT,
      files INT, certifiable INT, uncertain INT, error INT, avg_score INT,
      status TEXT, files_done INT, owner_email TEXT, assessed_at TEXT, finalized_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS file_records (
      scan_id TEXT, file TEXT, engine TEXT, status TEXT, score INT,
      compliant INT, skipped_rules INT,
      drive_file_id TEXT,
      remediated_at TEXT,
      drive_write_url TEXT,
      acp_stamped TEXT,
      checksum TEXT,
      published_at TEXT,
      blob_url TEXT,
      size_kb INT,
      pages INT,
      sheets INT,
      source_modified TEXT,
      PRIMARY KEY (scan_id, file)
    )""",
    # Per-scan decision snapshots (PRD: time-travel). kind='triage' (value inscope|na|defer),
    # 'action' (value = JSON {state, action}), or 'assignee' (value = assignee email, for the
    # "Assigned to me" inbox filter). Owner-scoped, one row per (scan,file,kind).
    """CREATE TABLE IF NOT EXISTS scan_decisions (
      scan_id TEXT, file TEXT, kind TEXT, value TEXT,
      owner_email TEXT, updated_at TEXT,
      PRIMARY KEY (scan_id, file, kind)
    )""",
    # Fan-out scan pipeline (ADR 0007): scan_runs is created at 'discover' with
    # status=running + a files_done counter, then finalized once all per-file jobs land.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS status TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS files_done INT",
    # Per-user isolation: scans are scoped to the signed-in user's email.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS owner_email TEXT",
    # Presentation decouple: set when the user runs Assess — results views gate on it.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS assessed_at TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS finalized_at TEXT",  # ADR 0013 finalize-once guard
    # WHAT the scan covered, as JSON (scanner._list scope_out). A file count is a fact about a
    # boundary, not about an estate: without this the UI could only ever state the number, so a
    # one-folder scan reading "1 document" was indistinguishable from a whole-Drive scan that
    # found one. NULL on scans predating this column — the UI must treat that as "unknown scope"
    # and say nothing rather than guessing "whole Drive".
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS scope TEXT",
    # WHEN the discovery phase finished — the instant the inventory describes.
    #
    # `completed_at` cannot answer this under ADR 0020. A Discover-only run stops at
    # status='discovered' and completed_at stays NULL until somebody runs Assess and the run
    # finalizes; previous_run_for_source already documents that and works around it with
    # COALESCE(completed_at, started_at). `started_at` is not the answer either — it is when the
    # LISTING BEGAN, which on a large estate is a long way from when the inventory was complete,
    # and it is written even for a run that then died mid-listing.
    #
    # So an inventory had no date of its own at the run grain, and every count rendered from it
    # was a snapshot presented without its instant. This is that instant, stamped once, when the
    # inventory has been persisted and the lifecycle rules have run.
    #
    # NULL on runs discovered before this column existed. A reader must treat that as "not
    # recorded" — the newest scan_inventory.discovered_at is the honest derivation for those, and
    # the frontend does exactly that rather than dating them to the render.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS discovered_at TEXT",
    # Staging → published snapshot (#1 resilience). Stamped only after discovery passes all
    # completeness checks (enumeration was not truncated and was not a suspicious zero).
    # NULL means either the scan predates this column, or it completed but had concerns that
    # prevented publishing — callers treat NULL as "unpublished" and fall back to the previous
    # published scan. The scan selection query prefers rows where published_at IS NOT NULL.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS published_at TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS size_kb INT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS pages INT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS sheets INT",
    # Migrations for existing deployments
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS drive_file_id TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS remediated_at TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS published_url TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS drive_write_url TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS acp_stamped TEXT",
    # Drive's md5Checksum (free in the same files().list() call) — lets a scan recognize
    # byte-identical duplicates uploaded under different names/folders and skip re-running
    # the (expensive) engine analysis + PII extraction for the 2nd+ copy. Scoped to ONE
    # scan only (find_by_checksum filters on scan_id) — reusing analysis ACROSS scans is
    # the bigger incremental-fingerprinting feature, not this.
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS checksum TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS published_at TEXT",
    # ADR 0010 — the remediated output's durable Blob URL, additive alongside
    # drive_write_url (a file can carry both; Drive is now a best-effort mirror).
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS blob_url TEXT",
    # Source-staleness baseline: the source file's modifiedTime (RFC3339) at scan time, so the
    # Release Center can tell whether the upstream Drive file changed since we fixed it. NULL for
    # pre-existing scans and for non-Drive / SharePoint / upload files — those are "untracked",
    # never falsely "unchanged".
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS source_modified TEXT",
    """CREATE TABLE IF NOT EXISTS issue_records (
      scan_id TEXT, file TEXT, rule_id TEXT, wcag TEXT, severity TEXT, detail TEXT,
      page INT, location TEXT
    )""",
    "ALTER TABLE issue_records ADD COLUMN IF NOT EXISTS detail TEXT",
    # WHERE the finding is — 1-based page/slide the analyser attributed, plus its structured
    # hint ('pptx:slide:0', an XPath). Feeds "locate in document" so a reviewer never hunts.
    # Nullable: NULL means the analyser could not attribute a location — never a page-1 default.
    "ALTER TABLE issue_records ADD COLUMN IF NOT EXISTS page INT",
    "ALTER TABLE issue_records ADD COLUMN IF NOT EXISTS location TEXT",
    """CREATE TABLE IF NOT EXISTS inventory (
      file TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
      last_status TEXT, last_score INT
    )""",
    """CREATE TABLE IF NOT EXISTS schedule_config (
      key TEXT PRIMARY KEY, value TEXT
    )""",
    # PRD Phase 3 (incremental connector sync). One row per source: the connector-native
    # cursor (Drive's changes.list page token today; a Graph delta link would be a future
    # row) that lets the scheduled sweep ask "what changed since last time" instead of
    # re-listing the whole estate. owner_email is carried for attribution/debugging only —
    # the cursor itself is source-scoped, not per-user (the scheduled sweep is a single
    # service-account identity, see core._do_scheduled_scan). Customer/scan-derived state,
    # not configuration — cleared by reset_analytics like scan_inventory/documents.
    """CREATE TABLE IF NOT EXISTS sync_cursors (
      source TEXT PRIMARY KEY, owner_email TEXT, page_token TEXT, updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS scan_rule_traces (
      scan_id TEXT, file TEXT, rule_id TEXT, rule_name TEXT, plain_name TEXT,
      level TEXT, fix_mode TEXT, outcome TEXT, finding_count INT,
      PRIMARY KEY (scan_id, file, rule_id)
    )""",
    # plain-English label (ADR: non-technical surfaces). Backfilled per scan.
    "ALTER TABLE scan_rule_traces ADD COLUMN IF NOT EXISTS plain_name TEXT",
    # Historic rows said NOT_APPLICABLE where the truth was "we never ran this check".
    # Idempotent, and readers accept both tokens anyway, so a rollback to an older image
    # (which would write the old token again) degrades to mixed rows, not wrong counts.
    "UPDATE scan_rule_traces SET outcome='NOT_EVALUATED' WHERE outcome='NOT_APPLICABLE'",
    # ADR 0037 Step 0 — per-file stage timings (download vs analyse), a SIDE-CHANNEL kept entirely off
    # the scoring path: written best-effort AFTER save_file_result, read only by /scans/{id}/timings.
    # Idempotent per file (same PK discipline as file_records) so a retried job re-writes, never doubles.
    """CREATE TABLE IF NOT EXISTS file_stage_timings (
      scan_id TEXT, file TEXT, timings TEXT,
      PRIMARY KEY (scan_id, file)
    )""",
    """CREATE TABLE IF NOT EXISTS hitl_queue (
      id TEXT PRIMARY KEY,
      created_at TEXT,
      scan_id TEXT,
      file TEXT,
      rule_id TEXT,
      rule_name TEXT,
      finding_count INT,
      status TEXT DEFAULT 'pending',
      reviewed_at TEXT,
      reviewer_note TEXT,
      page INT,
      pages TEXT
    )""",
    # WHERE this criterion fails in the document, so the reviewer never hunts for it.
    # page  = the first (lowest) page/slide the analysers attributed — enough to jump to.
    # pages = every distinct page, comma-separated; a criterion failing on 11 slides must not
    #         be rendered as if it failed on one. Both NULL when nothing was attributed
    #         (xlsx locates by cell; some rules are file-level) — we show no page, never a wrong one.
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS page INT",
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS pages TEXT",
    # ADR: AI-draft + human-approve lane. The reviewer's final, possibly-edited
    # value for a semantic finding (alt text / link text / title) — durable
    # compliance evidence of what was actually approved, distinct from the
    # ai.py-generated draft (which is regenerated on demand, not persisted).
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS approved_value TEXT",
    # AI-proposes → validate → one-click-approve lane. `proposals` is a JSON array of
    # {locator, before, proposed_value, rationale, source, thumb?} — one entry per
    # finding instance (3 vague links → 3 entries), so the reviewer sees a concrete,
    # pre-computed value to approve in one click instead of an on-demand /ai/suggest
    # blank. Distinct from approved_value (the human's final single value). `validated`
    # is 1 only when the proposal batch cleared its SC on the file's post-apply re-scan
    # — a persisted, honest signal confidence.js can key a Medium ("validated by
    # re-scan — awaiting approval") off of, since detection-tier confidence alone can't
    # tell a validated proposal from an unvalidated one.
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS proposals TEXT",
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS validated INT",
    # [{locator, thumb}] for each image this row asks a human to describe. NOT a proposal:
    # there is no value to approve. It is the picture — a 1.1.1 card without it asks someone
    # to write alt text for an image they cannot see. Populated whether or not the AI ran.
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS evidence TEXT",
    # 1 once the approved values on this row were actually WRITTEN into the document
    # (handlers.apply_approved_values → apply_alt.apply_alt_text → Blob/Drive). Until then an
    # approved row holds content the document does not carry, and the file must not certify —
    # see count_unapplied_approved_values. This is the difference between a promise and a fix.
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS applied INT",
    # The WCAG exception a reviewer applied INSTEAD of authoring a value: 'decorative' (1.1.1 —
    # the image conveys nothing, so no text alternative is required) or 'essential_exception'
    # (1.4.5/1.4.9 — a logotype is exempt from images-of-text). NULL for an ordinary decision.
    #
    # It has to live on the ROW, not only in the decision log, because the certify gate reads
    # rows. routes/hitl.py recorded the exception in a log detail and nowhere else, so
    # _row_approved_values still fell back to the card's `proposed_value` — the UI label "Mark as
    # decorative" — and the file was left owing the document a value nobody ever meant to write.
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS resolution TEXT",
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS assignee TEXT",
    # Where the finding IS, in words, for the formats that have no page number. `page`/`pages`
    # above are integers and answer this for PDF only; a spreadsheet's answer is "Sheet
    # 'Findings' cell B2" and a deck's is "Slide 3". Without this column the review card's
    # location chip was empty for every Office finding — the detectors emit `location` and
    # issue_records stores it, but the queue row carried only the integer.
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS location TEXT",
    # Per-file, per-rule-id (from rule-catalog.json) execution manifest.
    # PASS = rule ran, no findings; FAIL = findings found; ERROR = engine error.
    """CREATE TABLE IF NOT EXISTS scan_file_manifests (
      scan_id TEXT, file TEXT, rule_id TEXT, status TEXT, finding_count INT,
      PRIMARY KEY (scan_id, file, rule_id)
    )""",
    # The actual value an AI fix WROTE (e.g. the vision-generated alt text) + a tiny
    # base64 image thumbnail, so the "Recent AI fixes" surface shows what was really
    # applied instead of a canned template. One row per fixed element (seq disambiguates
    # several images in one file). Best-effort telemetry — never on the remediation path.
    """CREATE TABLE IF NOT EXISTS applied_fixes (
      scan_id TEXT, file TEXT, rule_id TEXT, seq INT,
      value TEXT, source TEXT, thumb TEXT, created_at TEXT,
      PRIMARY KEY (scan_id, file, rule_id, seq)
    )""",
    # Append-only AI-call provenance (ADR 0019): which provider/model ran, WHERE the bytes
    # were processed (local/cloud zone), latency, ok, cost. The queryable, certification-
    # embeddable record behind the review card's "Generated by … · 🟢 Local only" line —
    # persisting what already flows through Langfuse so it survives + joins to scans.
    """CREATE TABLE IF NOT EXISTS ai_calls (
      id TEXT PRIMARY KEY, ts TEXT, scan_id TEXT, file TEXT, surface TEXT,
      provider TEXT, model TEXT, zone TEXT, latency_ms INT, ok INT, cost_usd REAL
    )""",
    # WHY the call ended as it did (providers.REASON_*: ok / transport_error / http_<status> /
    # empty_response / reply_unusable). ok=0 alone is not actionable — an unreachable endpoint, a
    # 502, and a model that answered 200 with an empty string are three different fixes, and this
    # column is what tells them apart without shelling into the container. A stable short token
    # only: the response body stays in the log, never in a row a governance view renders.
    "ALTER TABLE ai_calls ADD COLUMN IF NOT EXISTS reason TEXT",
    # Reproducibility metadata (P4.7): the sampling temperature the model received, and a short
    # tag identifying the prompt template (e.g. "explain-v2"). Together with model+revision these
    # let an operator re-run a call with the exact same settings to verify a result or compare
    # behaviour across prompt iterations. Both nullable — populated per-surface, None for calls
    # whose temperature/prompt is not yet threaded through (see ai._trace_ai).
    "ALTER TABLE ai_calls ADD COLUMN IF NOT EXISTS temperature REAL",
    "ALTER TABLE ai_calls ADD COLUMN IF NOT EXISTS prompt_version TEXT",
    # Admin-controlled platform settings (key/value). e.g. ai_enabled='false'
    # forces deterministic-only mode for the whole platform (overrides per-scan ?ai=).
    """CREATE TABLE IF NOT EXISTS app_settings (
      key TEXT PRIMARY KEY, value TEXT
    )""",
    # Append-only audit log of every consequential decision (HITL review, scan
    # mode, remediation, disposition). Never updated or deleted — the immutable
    # record an auditor asks for. id is monotonic via created_at + a uuid tiebreak.
    """CREATE TABLE IF NOT EXISTS decision_log (
      id TEXT PRIMARY KEY, ts TEXT, actor TEXT, action TEXT,
      scan_id TEXT, file TEXT, rule_id TEXT, detail TEXT
    )""",
    # R18 · Comments on a finding — a human discussion thread anchored to ONE finding
    # (scan × file × criterion × instance), so a judgement call and any disagreement about it
    # live next to the finding rather than in a chat elsewhere. Append-only, like decision_log:
    # comments are a record, never edited. `finding_key` is the frontend-computed stable identity
    # of the finding within the scan (file||rule||location); `file`/`rule_id` are stored alongside
    # so a comment is legible without re-deriving them. `author` is the acting user's email.
    """CREATE TABLE IF NOT EXISTS finding_comments (
      id TEXT PRIMARY KEY, ts TEXT, scan_id TEXT, finding_key TEXT,
      file TEXT, rule_id TEXT, author TEXT, body TEXT
    )""",
    # Durable job queue (ADR 0004). Survives restarts; retried with backoff;
    # exhausted jobs become 'dead' (dead-letter). Timestamps are ISO-8601 TEXT so
    # they sort chronologically and compare portably across Postgres + SQLite.
    """CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, type TEXT, payload TEXT,
      status TEXT DEFAULT 'queued',
      priority INT DEFAULT 100, attempts INT DEFAULT 0, max_attempts INT DEFAULT 5,
      run_after TEXT, locked_at TEXT, locked_by TEXT,
      campaign_id TEXT, batch_id TEXT, scan_id TEXT,
      last_error TEXT, created_at TEXT, updated_at TEXT,
      phase TEXT
    )""",
    # Durable least-recently-served cursor for work-conserving tenant fairness. It contains no
    # document data, only ACP's existing owner_email tenant key and the last claim instant.
    """CREATE TABLE IF NOT EXISTS tenant_queue_state (
      tenant_key TEXT NOT NULL, lane_key TEXT NOT NULL, last_claimed_at TEXT NOT NULL,
      PRIMARY KEY(tenant_key, lane_key)
    )""",
    # What the job is doing RIGHT NOW, written by the handler as it works. The queue panel
    # used to render a hardcoded list of WCAG criteria cycled by a timer, which had nothing
    # to do with the running job. Nullable: a handler that reports nothing shows nothing.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS phase TEXT",
    # Cooperative cancellation (ADR 0004 step 4): caller sets this; running handler calls
    # worker.check_cancel() at checkpoints and raises JobCancelledError when set.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cancel_requested_at TEXT",
    # Priority/run_after remains the eligibility spine for claims. Tenant-fair selection also
    # counts active claims and reads the most recent locked_at for the candidate's scan owner;
    # this companion index keeps those correlated reads bounded to the relevant status/scan.
    "DROP INDEX IF EXISTS idx_jobs_claim",
    "CREATE INDEX IF NOT EXISTS idx_jobs_claim2 ON jobs(status, priority, run_after)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_tenant_fair ON jobs(status, scan_id, locked_at)",
    # Inspectable lease expiry: set at claim time to now + ACP_JOB_LEASE_S, refreshed by
    # touch_job heartbeat. reclaim_stuck_jobs uses this instead of the opaque locked_at
    # arithmetic so operators can see exactly when a lease will expire.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lease_expires_at TEXT",
    # Error class persisted on failure so operators can diagnose dead-lettered jobs by
    # category (rate_limit / auth / corrupt / transient) without parsing last_error text.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error_class TEXT",
    # Sensitive-data (PII) findings per document (ADR 0006). A detection dimension
    # orthogonal to WCAG. samples holds JSON array of MASKED strings only — never
    # raw PII (the masking is enforced in api/pii.py).
    """CREATE TABLE IF NOT EXISTS pii_findings (
      scan_id TEXT, file TEXT, pii_type TEXT, label TEXT,
      count INT, severity TEXT, samples TEXT,
      PRIMARY KEY (scan_id, file, pii_type)
    )""",
    # Document-centric layer (ADR 0003, Phase 1): a long-lived governed object a scan
    # upserts into, distinct from file_records (a per-scan snapshot). doc_id is stable
    # across renames/scans (see api/documents.py:resolve_doc_id).
    """CREATE TABLE IF NOT EXISTS documents (
      doc_id TEXT PRIMARY KEY, source TEXT, path TEXT, content_hash TEXT,
      owner TEXT, department TEXT, created_at TEXT, last_seen TEXT,
      usage_signal INT, regulatory_tags TEXT, business_criticality TEXT,
      triage_score INT, triage_rationale TEXT
    )""",
    # WHICH TENANT a document belongs to. This separates two meanings that are currently
    # COLLAPSED INTO ONE COLUMN, and the collapse is the hazard — not an absence.
    #
    # `documents.owner` is populated with the scan's owner_email (save_scan passes the same
    # report["owner"] it writes to scan_runs.owner_email; handlers passes payload["user"]). So
    # the tenant IS recorded today. But this table is the document-GOVERNANCE layer (ADR 0003):
    # `owner` sits beside `department`, `business_criticality` and `regulatory_tags`, and those
    # are facts about the customer's document, not about which customer we are. The column was
    # designed for a business owner and is being fed a tenant id.
    #
    # That works right up until somebody populates `owner` as designed — which ADR 0003 intends
    # and OwnerDelegate already implies — at which point every tenant-scoped read silently starts
    # matching on a person's name. Nothing errors. The estate simply becomes visible to the wrong
    # customer. `documents` is also the only table carrying `department`, so it is exactly where
    # a "filter by dept" view would be built.
    #
    # NULL means "tenant unknown", and a scoped read must EXCLUDE it rather than treat it as a
    # wildcard. Rows predating this column stay NULL until backfilled (below): the cost of
    # excluding them is a document nobody sees, the cost of including them is a document the
    # wrong customer sees, and those are not the same size of mistake.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_email TEXT",
    # ADR 0020 stage 2 — lightweight Discover-side classification (inventory, not conformance).
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS pages INT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS images INT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS has_text INT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS has_images INT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_scanned INT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_class TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS classified_at TEXT",
    # File size (Lifecycle Rules build-plan item #3 — a "larger than" condition). The scanner
    # already computes this per file (api/scanner.py's size_kb, written to scan_inventory) but
    # never carried it to `documents`, the table the disposition matcher actually reads —
    # doc_class had the identical gap once, closed by the two migrations just above.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS size_kb INT",
    # Per-violation remediation state machine (ADR 0003, Phase 2). Keyed by
    # (doc_id, rule_id) so "3 of 5 violations fixed" is first-class -- supersedes the
    # binary file_records.remediated_at as the governing truth (file_records stays the
    # per-scan snapshot; this is the long-lived state). hitl_queue remains the work-list;
    # this is the state hitl_queue resolution (and auto-remediation) write into.
    """CREATE TABLE IF NOT EXISTS remediation_state (
      doc_id TEXT, rule_id TEXT, state TEXT, updated_at TEXT, last_scan_id TEXT,
      PRIMARY KEY (doc_id, rule_id)
    )""",
    # Per-fix before→after evidence (what actually changed), keyed by the scan+file the
    # UI has on hand. Written by the remediate_file worker ONLY for fixes that verifiably
    # cleared on the post-fix re-scan, so the certification PDF's "Before → After" section
    # never shows a diff for a fix that didn't take. rule_id is the dotted WCAG SC.
    """CREATE TABLE IF NOT EXISTS remediation_diff (
      scan_id TEXT, file TEXT, rule_id TEXT, seq INT,
      before TEXT, after TEXT, note TEXT,
      PRIMARY KEY (scan_id, file, rule_id, seq)
    )""",
    # HITL review telemetry — one row per human decision, so the Intelligent Review
    # Workspace can report the metric that matters (reviewer TIME eliminated) and calibrate
    # confidence from the human's edit/reject signal. action: approve|edit|reject|skip;
    # edited = the reviewer changed the AI draft before approving (the calibration signal);
    # review_ms = client-measured time from card-open to decision.
    """CREATE TABLE IF NOT EXISTS hitl_events (
      id TEXT PRIMARY KEY, scan_id TEXT, file TEXT, rule_id TEXT, item_id TEXT,
      action TEXT, edited INT, review_ms INT, ai_value TEXT, final_value TEXT,
      reviewer TEXT, created_at TEXT
    )""",
    # Reviewer Feedback Intelligence: WHY a rejection happened (enum: incorrect_object, too_vague,
    # hallucinated, missed_text, org_preference, other, unspecified). Additive; placed AFTER the
    # CREATE above — init_schema runs this list in order.
    "ALTER TABLE hitl_events ADD COLUMN IF NOT EXISTS reject_reason TEXT",
    # Configurable file disposition (ADR 0003, Phase 3). PREVIEW ONLY as of this
    # migration -- api/disposition.py's matches() tells you which documents a policy
    # would select; nothing executes a real move/rename/archive/delete yet. That
    # execution path (gated on requires_approval + this audit table) is a deliberately
    # separate, later decision, not bundled with the schema.
    """CREATE TABLE IF NOT EXISTS disposition_policy (
      policy_id TEXT PRIMARY KEY, name TEXT, match TEXT, action TEXT,
      action_config TEXT, requires_approval INT, enabled INT
    )""",
    """CREATE TABLE IF NOT EXISTS disposition_audit (
      id TEXT PRIMARY KEY, ts TEXT, doc_id TEXT, policy_id TEXT,
      action TEXT, result TEXT, detail TEXT
    )""",
    # Lifecycle-rule tenant isolation: disposition_policy/disposition_audit shipped with NO
    # ownership column at all, so every signed-in user saw and could toggle every OTHER
    # tenant's rules (including the demo account's) — same owner_email pattern and
    # NULL-excluded semantics as documents.owner_email above.
    "ALTER TABLE disposition_policy ADD COLUMN IF NOT EXISTS owner_email TEXT",
    "ALTER TABLE disposition_audit ADD COLUMN IF NOT EXISTS owner_email TEXT",
    # Explicit rule priority (Lifecycle Rules build-plan item #6). Evaluation order used to be
    # implicit — name, alphabetically, an accident of list_disposition_policies' own ORDER BY —
    # so reordering rules meant renaming them. NULL (every pre-existing row) sorts LAST, after
    # every rule that has a real priority, and is broken by name among itself — the exact order
    # those rows already evaluated in, so this migration changes nothing for a tenant until they
    # actually reorder something. A brand new rule is assigned the next integer past the current
    # max on create (see create_disposition_policy), so it starts last too — the safe default —
    # rather than silently jumping ahead of rules that were already there.
    "ALTER TABLE disposition_policy ADD COLUMN IF NOT EXISTS priority INTEGER",
    "ALTER TABLE disposition_policy ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1",
    # The version of the policy AS EVALUATED, stamped on the audit row at discover time.
    # PRD §8 permits a grouped approval only when every selected row shares a policy version,
    # and §11 makes source mutations idempotent on (document_id, policy_version, action) — both
    # are unanswerable from a row that only records which policy fired, not which version of it.
    # Rows written before this column exists read NULL, and the batch route refuses them rather
    # than guessing a version on a reviewer's behalf.
    "ALTER TABLE disposition_audit ADD COLUMN IF NOT EXISTS policy_version INTEGER",
    # What the file looked like BEFORE an applied action — the prior Drive parents for a move,
    # the prior name for a rename, "not trashed" for a delete. Without it PRD §8's undo cannot
    # exist at all: disposition.execute_action used to read exactly these values and discard them
    # the instant it had used them, so nothing in the system could put a file back.
    # NULL on every row written before this column, and undo refuses those rather than guessing.
    "ALTER TABLE disposition_audit ADD COLUMN IF NOT EXISTS before_state TEXT",
    "ALTER TABLE disposition_policy ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE disposition_policy ADD COLUMN IF NOT EXISTS updated_at TEXT",
    """CREATE TABLE IF NOT EXISTS lifecycle_evaluation (
      evaluation_id TEXT PRIMARY KEY, scan_id TEXT, document_id TEXT,
      policy_id TEXT, policy_version INTEGER, result TEXT, evidence_json TEXT,
      proposed_action TEXT, priority INTEGER, evaluated_at TEXT, owner_email TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS effective_disposition (
      document_id TEXT, scan_id TEXT, winning_evaluation_id TEXT,
      lifecycle_status TEXT, precedence_reason TEXT, approval_status TEXT,
      override_reason TEXT, updated_at TEXT, owner_email TEXT,
      PRIMARY KEY(scan_id, document_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_lifecycle_evaluation_scan ON lifecycle_evaluation(scan_id, owner_email)",
    "CREATE INDEX IF NOT EXISTS idx_lifecycle_evaluation_file ON lifecycle_evaluation(scan_id, document_id)",
    # Per-file WCAG scope rules (Discover/Assess Lifecycle PRD §4.4 / AC-09, "C4"). A rule
    # targets files by folder / owner / department and assigns a Core-17 subset; the effective
    # code-set for a file is resolved from matching rules (union, or a higher-priority override
    # replaces — see api/scope_resolver.py). `codes` is a JSON array of SC ids; `is_override`
    # and `enabled` are 0/1; `priority` orders overlapping overrides. Config, not scan output —
    # a survivor of RESET (see _ANALYTICS_TABLES).
    """CREATE TABLE IF NOT EXISTS scope_rule (
      rule_id TEXT PRIMARY KEY, name TEXT, selector TEXT, value TEXT, codes TEXT,
      priority INT, is_override INT, enabled INT, created_at TEXT, created_by TEXT
    )""",
    # Phased remediation campaigns (ADR 0003, Phase 4). "Remediation Programs" existed
    # only as a client-derived view (Monitor.jsx useProgramBatches, computed fresh from
    # files/decisions props on every render, nothing persisted) -- these tables make a
    # campaign a real, durable object: pause/resume survives a reload, and batch
    # membership is a snapshot taken at creation time, not silently recomputed.
    """CREATE TABLE IF NOT EXISTS campaign (
      campaign_id TEXT PRIMARY KEY, name TEXT, status TEXT, scope TEXT, created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_batch (
      batch_id TEXT PRIMARY KEY, campaign_id TEXT, seq INT, status TEXT,
      filter TEXT, deadline TEXT
    )""",
    # ADR 0019 §1/§6 — per-provider AI gateway config. NON-SECRET only: the endpoint, model, and
    # the NAME of the container/Key-Vault secret that holds the key (key_secret_ref) — never the
    # key value itself. The adapter resolves the key from the ops-provisioned environment secret at
    # call time; nothing here, in the request path, or in the browser ever sees it.
    """CREATE TABLE IF NOT EXISTS ai_provider_config (
      provider TEXT PRIMARY KEY, enabled INT DEFAULT 0, endpoint TEXT, deployment TEXT,
      model TEXT, key_secret_ref TEXT, updated_at TEXT, updated_by TEXT
    )""",
    # ADR 0020 stage 3 — the Discover-phase inventory: what was FOUND, from source metadata only
    # (no file opened). Distinct from file_records, which holds ASSESSED results written later at
    # Assess time. Keeping them separate means the finalize machinery (count_files_done over
    # file_records) is untouched by deferral — file_records still fill 0→N only during Assess.
    """CREATE TABLE IF NOT EXISTS scan_inventory (
      scan_id TEXT, file TEXT, drive_file_id TEXT, mime TEXT, size_kb INT,
      doc_class TEXT, checksum TEXT, path TEXT,
      PRIMARY KEY (scan_id, file)
    )""",
    # Discover-completeness PRD (ADR 0003 lifecycle). The inventory must record EVERY file with
    # full source metadata so lifecycle rules (folder/path, created/modified date) and the estate
    # export can run off a durable per-file row — not just a capped sample. All additive, all
    # source-metadata (no file opened). `discovered_at` is the per-file discovery timestamp (the
    # scan's started_at is not per-row). `parent_folder` is the folder id/name lineage for the
    # Document Location filter and folder-scoped rules. `source_modified` is the file's own modified
    # time (distinct from ACP's discovery time); `created_at` its source creation time.
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS created_at TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS source_modified TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS owner TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS parent_folder TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS discovered_at TEXT",
    # SharePoint's Content Type name, best-effort and SharePoint-only — None for every other
    # source and None whenever the tenant did not return one (scanner._sp_enrich_content_types).
    # The one field of "read SharePoint-native metadata as a rule input" (docs/sharepoint-gaps.md)
    # this build is confident enough to ship UNVERIFIED against a live tenant: `fields.ContentType`
    # is the standard column every SharePoint list item carries. Additive, source-metadata only —
    # no file opened, same ADR 0020 discipline as every other inventory column.
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS content_type TEXT",
    # The Graph DRIVE the item was listed from. Graph item ids are unique only WITHIN a drive, so
    # `drive_file_id` alone does not identify a SharePoint item — asking /me/drive for a site's
    # item id 404s or, worse, returns a different document with the same id (scanner._sp_download).
    # Null for Drive/local/SMB rows, and null for a OneDrive listing, which legitimately has no
    # driveId; both mean "no drive to name", which _sp_base already reads as /me/drive.
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS drive_id TEXT",
    # The Google account a Drive row's listing ran as (scanner.drive_account_id) — the SIBLING
    # identity concept to drive_id above, on its own column since the two are unrelated: a
    # Graph drive names WHICH library a SharePoint item came from, this names WHO a Drive item
    # was listed as. A Drive token is a per-request browser credential, not a server-bound
    # "connected account", so nothing else records whether two Drive scans for the same ACP
    # owner even used the same Google identity. Null for non-Drive rows and for a Drive listing
    # where the identity call itself failed. Read back by
    # core._drive_prior_inventory_for_account before a prior scan's inventory is trusted as a
    # delta-sync baseline — the Drive mirror of drive_id's role in
    # core._sp_prior_inventory_for_drive.
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS drive_account_id TEXT",
    # WHICH SharePoint site and WHICH document library each row came from. `drive_id` above is
    # already the library's Graph drive id — half the identity — but a scan can now span up to 30
    # sites, and a drive id names nothing to a reader and does not say which site it belongs to.
    #
    # Recorded at the grain the row is, not derived from the scan's scope, because the scope holds
    # a SET of sites once a run spans several: "which site is this document in" stops being
    # answerable from the run at all. Everything Phase 2 onwards depends on that boundary —
    # per-site metadata, per-library delta cursors, per-site exception reports, write-back
    # targeting — so it is stored now rather than reconstructed later from an id that was thrown
    # away. NULL for every non-SharePoint source and for a OneDrive listing, which has no site.
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS site_id TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS library_name TEXT",
    # Per-document lifecycle status (PRD §4.3). One of: Active, Archive Candidate, Archived,
    # Delete Candidate, Deleted, Failed, Exempted. Defaults to Active on first discovery; a rule
    # run (Discover) or a manual action moves it. `lifecycle_rule_id`/`lifecycle_reason` record
    # WHICH rule produced the status and why (PRD §4.3 "record the matching rule ID and reason").
    # `exclusion_reason` is the human-readable reason Assess skipped the file (PRD §4.5).
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS lifecycle_status TEXT DEFAULT 'Active'",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS lifecycle_rule_id TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS lifecycle_reason TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS exclusion_reason TEXT",
    # Lifecycle rules #8: a human's reasoned disagreement with a rule's Archive/Delete Candidate
    # recommendation for THIS file. Deliberately separate from lifecycle_status/lifecycle_rule_id/
    # lifecycle_reason above, which stay untouched — those record what the RULE said; these record
    # what the HUMAN said in response. An override does not change lifecycle_status: it is itself
    # only a recommendation ("keep this despite the rule"), matching every other lifecycle surface's
    # "nothing is moved" discipline, and it keeps DiscoveryResults' bucket reconciliation a true
    # partition of what the rule pass produced.
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS lifecycle_override_reason TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS lifecycle_overridden_by TEXT",
    "ALTER TABLE scan_inventory ADD COLUMN IF NOT EXISTS lifecycle_overridden_at TEXT",
    # The file's own source-modified time on the governed document (mirrors scan_inventory.
    # source_modified). The disposition rules engine reads this for "modified before <date>"
    # conditions — documents.created_at already exists; this adds the modified axis.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_modified TEXT",
    # Per-file tags (PRD §4.2 Tag action + §3 auto-tagging). kind: 'system' (rule-applied) or
    # 'user' (manual). rule_id names the lifecycle rule that applied a system tag (NULL for user
    # tags). Keyed per (scan_id, file, tag) to match scan_inventory's grain; idempotent re-tagging
    # (PRD §4.3 idempotent re-runs) falls out of the primary key.
    """CREATE TABLE IF NOT EXISTS file_tags (
      scan_id TEXT, file TEXT, tag TEXT, kind TEXT, rule_id TEXT, created_at TEXT,
      PRIMARY KEY (scan_id, file, tag)
    )""",
    # ADR 0021 — enterprise review memory. Org-scoped guidance that shapes AI draft PROMPTS
    # (never model weights). kind: 'style'/'glossary' (admin-authored, apply when status
    # 'active') or 'derived' (behaviour-proposed, inert until an admin accepts it). guidance
    # IS the prompt fragment; evidence holds the real hitl_events count for a derived rule
    # (ADR 0016 — a real count or it does not exist). Org-isolated; no memory crosses tenants.
    """CREATE TABLE IF NOT EXISTS org_memory (
      id TEXT PRIMARY KEY, org TEXT NOT NULL, kind TEXT NOT NULL,
      rule_id TEXT, format TEXT, guidance TEXT NOT NULL, status TEXT NOT NULL,
      evidence TEXT, author TEXT, created_at TEXT, updated_at TEXT
    )""",
    # Atomic enqueue (Stage 1 item 2): client-supplied deduplication key so a retried
    # submission with the same key returns the original scan without creating a duplicate.
    # Scoped to owner_email — keys are tenant-local, not global. NULL means "no key provided";
    # the unique index only covers non-null rows (WHERE idempotency_key IS NOT NULL) so
    # NULL never collides.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS idempotency_key TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_runs_idempotency ON scan_runs(owner_email, idempotency_key) WHERE idempotency_key IS NOT NULL",
    # Immutable input snapshot (Stage 1 item 3): everything known at enqueue time that
    # governs how the scan executes, written atomically with scan_runs + jobs. Workers read
    # this before processing; a rule or config change after enqueue cannot silently alter
    # an already-queued scan.
    # SECURITY: no access tokens, credentials, or secrets stored here. connection_ref
    # identifies the authorized source connection (e.g. "drive:user@example.com"); the
    # worker acquires live credentials at execution time from the token store / job payload.
    # provider_config omits key_secret_ref — snapshot captures endpoint/model, not the
    # secret reference name.
    """CREATE TABLE IF NOT EXISTS scan_inputs (
      scan_id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      folder_ids TEXT,
      exclude_folder_ids TEXT,
      scan_options TEXT NOT NULL,
      actor TEXT NOT NULL,
      connection_ref TEXT,
      feature_flags TEXT,
      provider_config TEXT,
      lifecycle_rules TEXT,
      app_version TEXT,
      captured_at TEXT NOT NULL
    )""",
    # ADR 0004 item 6 — per-folder checkpoint columns. total_folders is set by the
    # scan_discover job when it fans out to per-folder work; completed_folders is
    # atomically incremented by each scan_folder job once it finishes its subtree.
    # Together they drive the finalization trigger and the "N/M folders scanned" UI.
    # WHICH job, and which ATTEMPT of it, wrote this result. The fence for a stale writer — see
    # save_file_result. Both NULL on every row written before these columns existed and on any
    # caller that passes no job; a NULL on either side always ALLOWS the write rather than
    # blocking it, because an old row must never become unwritable.
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS written_job TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS written_attempt INT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS total_folders INT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS completed_folders INT",
    # Which folders that counter has already counted. The counter alone cannot answer that —
    # `completed_folders + 1` is a fact about how many times the increment RAN, and the thing it
    # is read as ("how many folders are done") is a fact about the folder SET. Those two diverge
    # the moment a folder job runs twice, which is a routine event and not a rare one: a worker
    # reclaimed after it incremented but before its job row reached 'done' re-lists the same
    # folder and increments again, and so does a retry of a job whose enqueue_job("scan_finalize")
    # raised. The overshoot is not the damage — a scan of two folders that counts one of them
    # twice reaches `done >= total` while the OTHER folder is still being scanned, so both the
    # in-handler trigger and rescue_unfinalized_scans finalize a partial estate and report it
    # complete. A silent wrong answer, in the direction of claiming more coverage than was read.
    #
    # PRIMARY KEY(scan_id, folder_id) is what makes the second increment a no-op: the claim is
    # an INSERT … ON CONFLICT DO NOTHING, so deduplication is the database's, decided in one
    # statement, and two workers racing on the same folder cannot both win it.
    """CREATE TABLE IF NOT EXISTS scan_folder_completions (
      scan_id TEXT NOT NULL,
      folder_id TEXT NOT NULL,
      counted_at TEXT,
      PRIMARY KEY (scan_id, folder_id)
    )""",
    # Discovery acknowledgement (PRD §EX-10): the operator reviews lifecycle recommendations
    # and explicitly acknowledges the snapshot before Assess can consume it.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS acknowledged BOOLEAN DEFAULT FALSE",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS acknowledged_at TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS acknowledged_by TEXT",
    # Sparse durable recovery checkpoint for live Discover progress (Redis live-state spec,
    # 2026-08-26). The Redis-backed job state (core.update_job/get_job_state) is the fast,
    # frequent live source the SSE stream normally reads — but it is EPHEMERAL: gone if Redis is
    # unreachable, a key TTLs out, or a replica with no Redis configured falls to its own
    # in-memory JOBS dict that no other replica can see. Without a durable fallback, that failure
    # mode reads as "the scan card went dark" with nothing to show instead. This is that fallback:
    # written sparsely (on phase changes, and otherwise at most once per _CHECKPOINT_INTERVAL_S —
    # see core.py's checkpoint throttle), NOT on every progress tick, so it never approaches the
    # write volume that caused 2026-08-26's Postgres connection exhaustion. JSON text, matching
    # the existing `scope` column's convention (portable across the SQLite/Postgres dual schema).
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS live_checkpoint TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS live_checkpoint_at TEXT",
    # Active-Discovery concurrency guard (resilience Phase 1). Exactly one active Discovery
    # per (owner_email, source) at any time. Claimed transactionally when a discover job starts
    # and released in the same transaction that sets the terminal scan status — so a crash or
    # disconnect cannot release it; only durable finalization can. scan_id is UNIQUE so the
    # finalizer can release by scan_id without knowing the source.
    #
    # `owner_email` is the ACP tenant identifier until a first-class tenant_id column is added.
    # A future Temporal migration keeps the same guard row — only the execution mechanism changes.
    """CREATE TABLE IF NOT EXISTS active_discovery_guard (
      owner_email TEXT NOT NULL,
      source TEXT NOT NULL,
      scan_id TEXT NOT NULL,
      acquired_at TEXT NOT NULL,
      updated_at TEXT,
      PRIMARY KEY (owner_email, source)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_adg_scan ON active_discovery_guard(scan_id)",
    # Bumped on every write that changes what the Overview snapshot would report
    # (assessment finishing, remediation, a review decision, publishing — see
    # bump_scan_revision). NULL/0 for a scan that has never been mutated since this column
    # was added. Part of the overview_snapshots cache key so a stale snapshot is never served
    # after one of those writes, without having to hunt down and delete the cached row itself.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS revision INT",
    # Server-generated Overview snapshot cache (workspace-bootstrap redesign, Phase 1). One row
    # per (owner, scan, revision, rubric_hash) — owner is part of the key for tenant isolation,
    # not just an access filter, so a lookup under the wrong owner is a cache MISS, never a
    # cross-tenant read. revision+rubric_hash change whenever the underlying scan does, which is
    # what makes the cache safe to keep forever instead of expiring it on a timer (scan history
    # is immutable evidence unless a recorded mutation changes it).
    """CREATE TABLE IF NOT EXISTS overview_snapshots (
      owner_email TEXT NOT NULL,
      scan_id TEXT NOT NULL,
      scan_revision INT NOT NULL,
      rubric_hash TEXT NOT NULL,
      snapshot TEXT NOT NULL,
      generated_at TEXT NOT NULL,
      PRIMARY KEY (owner_email, scan_id, scan_revision, rubric_hash)
    )""",
    # Durable scan-lifecycle event log (ADR 0042). Append-only: rows are never updated, and
    # deleted only when the scan they describe is (delete_scan / reset_user_data / reset_analytics
    # — scan_events is in _RESET_USER_SCAN_TABLES, so it inherits all three).
    #
    # WHAT GOES IN HERE, and why the line is drawn where it is. Run-level TRANSITIONS only —
    # queued, claimed, listing started/complete, inventory saved, lifecycle applied, retrying,
    # cancelled, completed, failed. NOT activity.py's headline (up to 5 writes/second), and NOT
    # per-file completion (file_records already persists that with timestamps, and
    # document_timeline already reads it). That scope rule is doing three jobs at once:
    #   * ~15-30 rows per scan makes "never delete" affordable (~225 MB/yr at 100 scans/day)
    #     rather than the ~60 GB/yr per-file events would cost — at which point this would need
    #     partitioning or a retention window instead. A later ADR admitting per-file events must
    #     ship a retention decision with them.
    #   * it keeps the seq assignment below effectively uncontended: run-level transitions come
    #     from one job's thread at a time, not from the 8-way assessment fan-out.
    #   * it keeps the Postgres write volume orders of magnitude below the cadence
    #     core._maybe_checkpoint was throttled to after the 2026-08-26 connection exhaustion.
    #     This table is emphatically not a live feed; Redis stays the live current-state cell.
    #
    # ORDERING is (scan_id, seq), and the UNIQUE index below is what makes that a constraint
    # rather than a convention. seq is assigned by the INSERT itself (see append_scan_event) —
    # NOT a BIGSERIAL/AUTOINCREMENT column, since this schema is shared with SQLite and no table
    # in this file uses one, and NOT an occurred_at cursor: events for one scan can be written
    # from two replicas at once (a reclaimed job's second worker, see test_job_completion_race),
    # so a wall-clock cursor would silently SKIP a late event stamped before the reader's
    # position. occurred_at is for humans and auditors; seq is the sort key and resume cursor.
    #
    # owner_email is denormalized from scan_runs so a read scopes without a join, matching how
    # live_snapshot gates. detail is a small JSON object (per-kind narration — a file count, an
    # error class); it is never a second source of truth for a number scan_runs already holds.
    """CREATE TABLE IF NOT EXISTS scan_events (
      event_id TEXT PRIMARY KEY,
      scan_id TEXT NOT NULL,
      seq INT NOT NULL,
      occurred_at TEXT NOT NULL,
      kind TEXT NOT NULL,
      phase TEXT,
      job_id TEXT,
      worker_id TEXT,
      attempt INT,
      detail TEXT,
      owner_email TEXT
    )""",
    # Serves BOTH jobs — it is the uniqueness constraint that makes seq an ordering guarantee,
    # and the index every read below uses (WHERE scan_id=? [AND seq>?] ORDER BY seq). ADR 0042
    # named a second, non-unique index on the same two columns in the same order; it would be
    # pure dead weight beside this one, so only this ships.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_events_seq ON scan_events(scan_id, seq)",
    # ADR 0044 — ACP Managed Content Workspace, Phase 1. A workspace is the tenant-scoped
    # container a customer creates before uploading anything; `content_workspace_documents`/
    # `content_workspace_document_versions` (the actual upload targets) are deliberately NOT
    # created yet — see the ADR for why an empty, unpopulated table is worse than no table.
    # `owner_email` is the tenant boundary, same convention as every other per-user isolation
    # boundary in this app (scan_runs, documents, campaign, ...) — no new tenant_id concept.
    """CREATE TABLE IF NOT EXISTS content_workspaces (
      id TEXT PRIMARY KEY,
      owner_email TEXT NOT NULL,
      name TEXT NOT NULL,
      purpose TEXT,
      business_owner TEXT,
      department TEXT,
      wcag_standard TEXT,
      retention_policy TEXT,
      permitted_file_types TEXT,
      due_date TEXT,
      project TEXT,
      processing_region TEXT,
      external_ai_policy TEXT,
      status TEXT DEFAULT 'active',
      created_at TEXT,
      updated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_content_workspaces_owner ON content_workspaces(owner_email)",
    # ADR 0044 — the document/version tables the workspace model was built to attach to.
    # `workspace_id`/`document_id` are app-level references, not DB foreign keys — matching
    # this codebase's existing convention (scan_inventory.scan_id, campaign_batch.campaign_id,
    # ...) of enforcing referential integrity in the store layer rather than the schema.
    # `owner_email` is denormalized onto BOTH tables (not just looked up via a join to
    # content_workspaces) for the same reason scan_inventory/documents already denormalize it:
    # every isolation check reads it directly, with no join, the same way
    # get_content_workspace already does for the workspace row itself.
    """CREATE TABLE IF NOT EXISTS content_workspace_documents (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      display_name TEXT,
      relative_path TEXT,
      status TEXT,
      created_at TEXT,
      updated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cw_documents_workspace ON content_workspace_documents(workspace_id)",
    # `version_seq` is 1-based per document (PRD §12's "upload as a new version"); `content_hash`
    # is NOT NULL because every version is bytes that were actually uploaded and verified (PRD
    # §9) — a version row is only ever created after the hash is known, never speculatively.
    """CREATE TABLE IF NOT EXISTS content_workspace_document_versions (
      id TEXT PRIMARY KEY,
      document_id TEXT NOT NULL,
      version_seq INT NOT NULL,
      content_hash TEXT NOT NULL,
      mime_type TEXT,
      size_bytes INT,
      blob_path TEXT,
      original_filename TEXT,
      uploaded_at TEXT,
      uploaded_by TEXT,
      malware_status TEXT,
      lifecycle_state TEXT,
      assessment_status TEXT,
      source_version_id TEXT,
      remediated_from_version_id TEXT,
      release_status TEXT,
      retention_date TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_cw_versions_document ON content_workspace_document_versions(document_id)",
    # Duplicate detection (PRD §12) is a per-document-set, cross-document lookup by hash — this
    # is the index that query needs; scoped further to (workspace, hash) at the query layer via
    # a join through content_workspace_documents, since the hash column itself has no
    # workspace_id of its own.
    "CREATE INDEX IF NOT EXISTS idx_cw_versions_hash ON content_workspace_document_versions(content_hash)",
    # ── Operational event stream (orchestration_events / worker_instances) — PR 1 of a 5-PR
    # delivery plan, schema + store methods ONLY, zero callers, zero behaviour change. Modeled
    # deliberately on scan_events (ADR 0042, directly above) but is NOT that table and does not
    # replace it:
    #   scan_events          — the CUSTOMER-FACING scan-lifecycle narrative. Always scan-anchored.
    #   orchestration_events — the broader OPERATIONAL layer: job attempts, worker identity and
    #                          readiness, Azure capacity transitions, dependency health. Many rows
    #                          have NO scan_id at all — a worker becoming ready or a replica being
    #                          provisioned isn't about any one scan.
    #
    # ORDERING is deliberately (occurred_at, event_id), NOT scan_events' per-scan `seq`. `seq`
    # exists specifically because scan_events is a resume cursor for a LIVE SSE stream (ADR
    # 0042's own reasoning) — orchestration_events' read APIs (a later PR) are plain paginated
    # REST reads, not a stream, and most event kinds here have no scan_id to scope a per-scan
    # counter against anyway, so there is no natural "one counter" for a monotonic sequence to
    # attach to. Instead this follows decision_log's already-reviewed pattern immediately above
    # in this file: order by (occurred_at, event_id), a timestamp with a stable uuid tiebreak,
    # no monotonic sequence needed. This is a deliberate choice matching an existing pattern, not
    # an oversight — see append_orchestration_event's docstring for the concurrency argument that
    # makes it safe here (unlike scan_events, there is no shared per-key counter to race over).
    #
    # detail_json — WHAT MAY GO IN HERE, matching the house redaction contract api/routes/
    # system.py already enforces for secret-shaped values ("a secret REFERENCE is an
    # environment-variable name... never a key value"): this column may hold small, narrative
    # facts about an operational transition (a file count, a retry attempt, an error class, a
    # capacity delta) and MUST NEVER hold document contents, access tokens, prompts, model
    # responses, PHI, or credentials of any kind — a reference (an env var name, a job id, a
    # worker id) is fine, a value never is. It is capped at a fixed size (see
    # append_orchestration_event) and truncated with an explicit marker rather than cut mid-JSON,
    # matching SUBSTR(last_error,1,200)'s spirit of bounding free text elsewhere in this file.
    #
    # owner_email is required on every row (append_orchestration_event raises without it) so a
    # read scopes without a join, matching scan_events/live_snapshot's convention — including for
    # scan_id-less rows, which is why it is NOT relied on as a join key the way scan_events' is.
    """CREATE TABLE IF NOT EXISTS orchestration_events (
      event_id TEXT PRIMARY KEY,
      occurred_at TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      scan_id TEXT,
      job_id TEXT,
      job_type TEXT,
      attempt INT,
      workflow TEXT,
      stage TEXT,
      kind TEXT NOT NULL,
      severity TEXT,
      worker_id TEXT,
      replica_id TEXT,
      revision_name TEXT,
      correlation_id TEXT,
      provider TEXT,
      error_class TEXT,
      duration_ms INT,
      detail_json TEXT,
      schema_version INT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_orch_events_owner ON orchestration_events(owner_email, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_orch_events_scan ON orchestration_events(scan_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_orch_events_job ON orchestration_events(job_id, attempt, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_orch_events_worker ON orchestration_events(worker_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_orch_events_kind ON orchestration_events(kind, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_orch_events_error_class ON orchestration_events(error_class, occurred_at)",
    # Current-state worker registry — one row PER WORKER, upserted, NOT append-only (unlike
    # orchestration_events above). Answers "what workers exist and what state are they in right
    # now", the same current-state-cell shape store.worker_tier_status already holds for the
    # tier as a whole (a single app_settings heartbeat), but per-instance: replica identity,
    # concurrency, and the individual worker's lifecycle state. No owner_email — a worker isn't
    # scoped to a tenant, so this table is deliberately absent from the per-owner reset paths
    # below (see upsert_worker_instance / _RESET_USER_SCAN_TABLES comment).
    """CREATE TABLE IF NOT EXISTS worker_instances (
      worker_id TEXT PRIMARY KEY,
      replica_id TEXT,
      revision_name TEXT,
      started_at TEXT,
      last_heartbeat_at TEXT,
      supported_job_types TEXT,
      concurrency_limit INT,
      active_job_count INT,
      available_slots INT,
      state TEXT,
      last_claimed_job_id TEXT,
      software_version TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_worker_instances_state ON worker_instances(state)",
    # ADR 0044 — links a scan_runs row back to the content_workspace_document_versions row it
    # assessed, when the scan's source is "workspace" rather than a connector. NULL for every
    # connector-sourced scan (the overwhelming majority). App-level reference, not a DB FK,
    # matching every other cross-table pointer in this schema (scan_id on file_records, etc.).
    # Set atomically at enqueue time (see enqueue_scan) so a scan_runs row is never observable
    # without its link, the same "no orphan stubs" guarantee idempotency_key already gives that
    # insert.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS content_workspace_version_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_scan_runs_cw_version ON scan_runs(content_workspace_version_id) "
    "WHERE content_workspace_version_id IS NOT NULL",

    # ── Accessibility Conformance Report (ACR) workspace — ADR 0047, PRD Phase 1 ──────────────
    # An ACR is a VPAT-structured statement about ACP'S OWN WEB UI, against WCAG 2.2 A+AA. It is
    # NOT about the customer documents ACP remediates, and nothing in these tables joins to
    # scan_runs / issue_records for that reason: docs/conformance-report.md already draws that
    # line in prose, and a schema-level join is how it would be crossed by accident. Evidence
    # about ACP's UI arrives from axe-core runs over ACP's screens and from human testers.
    #
    # App-level references, not DB foreign keys, matching every other cross-table pointer in this
    # schema (scan_inventory.scan_id, content_workspace_documents.workspace_id, ...). owner_email
    # is denormalized onto every table so an isolation check reads it with no join, the same
    # convention content_workspace_documents and scan_events already follow.
    """CREATE TABLE IF NOT EXISTS acr_report (
      id TEXT PRIMARY KEY,
      owner_email TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'draft',
      catalog_hash TEXT NOT NULL,
      supersedes_id TEXT,
      revision INT NOT NULL DEFAULT 1,
      report_title TEXT, product_name TEXT, product_version TEXT, build_id TEXT,
      release_date TEXT, vendor_name TEXT, vendor_contact TEXT, product_description TEXT,
      evaluation_scope TEXT, excluded_functionality TEXT, deployment_environment TEXT,
      vpat_edition TEXT, wcag_version TEXT, wcag_levels TEXT,
      evaluation_methods TEXT, browsers_tested TEXT, operating_systems_tested TEXT,
      assistive_technologies_tested TEXT, automated_tools TEXT,
      testing_period_start TEXT, testing_period_end TEXT,
      evaluators TEXT, approver TEXT, general_notes TEXT, known_dependencies TEXT,
      evidence_validity_days INT,
      created_at TEXT, updated_at TEXT, published_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_acr_report_owner ON acr_report(owner_email)",

    # One row per applicable criterion, per report — the PRD §9 criteria matrix.
    #
    # final_status and workflow_state are TWO COLUMNS ON PURPOSE. PRD §9 permits ACP's internal
    # states ("Not evaluated", "Needs review") but forbids them appearing as VPAT conformance
    # levels. One column holding both vocabularies is exactly how "Not evaluated" ends up printed
    # in a customer's conformance table, so they never share a column. final_status is constrained
    # to the four VPAT terms in the store layer (see save_acr_decision); workflow_state carries
    # everything else and is never exported.
    """CREATE TABLE IF NOT EXISTS acr_criterion (
      report_id TEXT NOT NULL,
      criterion_num TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      criterion_name TEXT, level TEXT, principle TEXT, guideline TEXT,
      applicable INT NOT NULL DEFAULT 1,
      workflow_state TEXT NOT NULL DEFAULT 'not_evaluated',
      draft_status TEXT,
      final_status TEXT,
      remarks TEXT,
      evaluator TEXT,
      reviewer TEXT,
      approval_state TEXT NOT NULL DEFAULT 'unapproved',
      decided_at TEXT, approved_at TEXT, updated_at TEXT,
      PRIMARY KEY (report_id, criterion_num)
    )""",

    # APPEND-ONLY (PRD §12 "remains visible for audit history", §17 additions AND removals are
    # audited). Nothing here is ever UPDATEd or DELETEd except `stale_reason`, which is a DISPLAY
    # CACHE of what api/acr_freshness.py derives — never the input to a publication decision. A
    # retraction is a tombstone in acr_decision_log plus a superseding row, not an edit.
    #
    # `coverage` is the field the automated-evidence honesty rule turns on: an assessment.Coverage
    # value declaring how much of the criterion the producing technique actually reaches. Required
    # for automated rows (acr_model refuses to build one without it) and meaningless for human
    # ones. See ADR 0031 for why coverage, not accuracy, is the axis that gates a pass.
    """CREATE TABLE IF NOT EXISTS acr_evidence (
      id TEXT PRIMARY KEY,
      report_id TEXT NOT NULL,
      criterion_num TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      source_kind TEXT NOT NULL,
      result TEXT NOT NULL,
      tester TEXT, tested_at TEXT, product_version TEXT, build_id TEXT,
      environment TEXT, workflow TEXT, browser TEXT, assistive_tech TEXT,
      tool_name TEXT, tool_version TEXT, rule_id TEXT, tested_url TEXT, coverage TEXT,
      method TEXT, notes TEXT, attachments TEXT, related_finding_ids TEXT,
      stale_reason TEXT,
      created_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_acr_evidence_criterion ON acr_evidence(report_id, criterion_num)",

    # Guided manual test plan instances (PRD §14). Phase 1 creates the table and no rows — the
    # plan catalog itself is Phase 3. It ships now so the evidence a Phase-1 manual test records
    # has somewhere to point, rather than a schema change landing under live reports later.
    """CREATE TABLE IF NOT EXISTS acr_manual_test (
      id TEXT PRIMARY KEY,
      report_id TEXT NOT NULL,
      criterion_num TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      plan_id TEXT NOT NULL,
      result TEXT,
      evidence_id TEXT,
      tester TEXT, notes TEXT, created_at TEXT, updated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_acr_manual_test_report ON acr_manual_test(report_id, criterion_num)",

    # One recorded outcome per step of a plan run (PRD §14, Phase 3). A SEPARATE TABLE rather than
    # columns on acr_manual_test, for two reasons. Plans have different step counts, so columns
    # would mean either a fixed ceiling or a JSON blob nothing can query. And the ACR schema is
    # additive-only under ADR 0045 — test_acr_no_regression asserts every acr_ statement is a
    # CREATE, so widening a live table is not available here even if it were desirable.
    #
    # `environment` holds the per-run tester metadata the plan's own `needs` list demands
    # (browser, os, assistive_tech, viewport…), which is what makes the run reproducible under
    # PRD §4.5. It lives on the RUN, not the step: one session, one environment.
    """CREATE TABLE IF NOT EXISTS acr_manual_step (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL,
      report_id TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      step_index INTEGER NOT NULL,
      outcome TEXT NOT NULL,
      notes TEXT, recorded_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_acr_manual_step_run ON acr_manual_step(run_id, step_index)",

    # Append-only audit trail (PRD §17). Mirrors decision_log's shape and its never-updated,
    # never-deleted contract; separate from it because decision_log is scan-anchored (its scan_id/
    # file/rule_id columns) and an ACR event has no scan at all.
    """CREATE TABLE IF NOT EXISTS acr_decision_log (
      id TEXT PRIMARY KEY,
      ts TEXT NOT NULL,
      report_id TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      actor TEXT,
      action TEXT NOT NULL,
      criterion_num TEXT,
      detail TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_acr_decision_log_report ON acr_decision_log(report_id, ts)",

    # IMMUTABLE published snapshots (PRD §17, §21.12). Written once, never updated — a change
    # after publication creates a NEW acr_report row with supersedes_id set, and this row stays
    # exactly as it was.
    #
    # content_digest is a recomputable SHA-256 over content_json. It is a DIGEST, not a digital
    # signature: no key, no non-repudiation. api/report.py's _content_digest carries the same
    # warning and the same instruction — never relabel it.
    """CREATE TABLE IF NOT EXISTS acr_snapshot (
      id TEXT PRIMARY KEY,
      report_id TEXT NOT NULL,
      owner_email TEXT NOT NULL,
      revision INT NOT NULL,
      catalog_hash TEXT NOT NULL,
      content_json TEXT NOT NULL,
      content_digest TEXT NOT NULL,
      docx_blob_path TEXT,
      published_at TEXT NOT NULL,
      published_by TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_acr_snapshot_report ON acr_snapshot(report_id, revision)",

    # ACR-scoped roles (PRD §18). DELIBERATELY NOT the platform admin model.
    #
    # core.is_admin() returns True for ANY authenticated user under the default OPEN_ACCESS=1 —
    # which is the right call for the rest of the product and the wrong one here: PRD §21.11
    # requires that only an approver may publish, and an "approver" that means "everyone who can
    # sign in" is not one. So authority to approve/publish an ACR is granted HERE and nowhere
    # else, and core.OPEN_ACCESS does not confer it. This is the first place in ACP where being
    # an admin is not sufficient; see api/acr_authz.py for the gate and the reasoning.
    #
    # report_id '*' is an account-wide grant; a specific id scopes the role to one report.
    """CREATE TABLE IF NOT EXISTS acr_role (
      owner_email TEXT NOT NULL,
      report_id TEXT NOT NULL,
      email TEXT NOT NULL,
      role TEXT NOT NULL,
      granted_by TEXT, granted_at TEXT,
      PRIMARY KEY (owner_email, report_id, email, role)
    )""",

    # Workspace roles — which TABS an identity may see, and what they may do inside them.
    #
    # A THIRD authorization boundary, next to the two above it, and the distinction is the whole
    # design: core.is_admin() answers "may this identity touch platform settings" (and under
    # OPEN_ACCESS=1 that is everyone); acr_role answers "may this identity approve THIS report";
    # these tables answer "which workflow surfaces does this identity have, and at what level".
    # They do not confer ACR roles and ACR roles do not confer them. See api/workspace_rbac.py.
    #
    # `tenant_id` carries the owner-email tenant identifier, the same convention every other
    # table in this file uses (see the note above scan_runs.owner_email) — spelled `tenant_id`
    # because that is what it means here and because a role set is not owned by a scan owner in
    # the way a scan is. It is not a new tenancy concept.
    #
    # `version` is the optimistic-concurrency token of PRD §14: an update carrying a stale version
    # is refused rather than applied, so two administrators editing the same role in two tabs
    # cannot silently overwrite one another. `is_system` marks a role this build ships (it can be
    # duplicated, and a copy is an ordinary custom role); `is_protected` marks Owner, which cannot
    # be edited, deleted, or assigned by anyone but the current Owner.
    """CREATE TABLE IF NOT EXISTS workspace_roles (
      id TEXT NOT NULL,
      tenant_id TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT,
      is_system INT NOT NULL DEFAULT 0,
      is_protected INT NOT NULL DEFAULT 0,
      created_by TEXT, created_at TEXT, updated_at TEXT,
      version INT NOT NULL DEFAULT 1,
      PRIMARY KEY (tenant_id, id)
    )""",
    # Role names are unique within a tenant (PRD §14). Enforced by the DATABASE and not only by
    # the route: two administrators creating "Reviewer" in the same second both pass a
    # read-then-check in the route and one of them is wrong. Lowercased in the index so "Reviewer"
    # and "reviewer" collide, because to a human reading the role list they are the same name.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_roles_name "
    "ON workspace_roles(tenant_id, LOWER(name))",

    # One row per (role, capability). `capability` holds a TAB KEY for a tab-access row and a
    # grant capability id for an administrative permission; `access_level` is hidden/view/operate
    # for the former and 'granted' for the latter. One table rather than two because they are read
    # together on every request and a join that can half-fail is a way to compute a partial role
    # and not notice — api/workspace_rbac.tab_access_from_rows drops what it does not recognise
    # rather than defaulting it.
    """CREATE TABLE IF NOT EXISTS workspace_role_permissions (
      tenant_id TEXT NOT NULL,
      role_id TEXT NOT NULL,
      capability TEXT NOT NULL,
      access_level TEXT NOT NULL,
      PRIMARY KEY (tenant_id, role_id, capability)
    )""",
]

# One-time backfill: assign pre-isolation (NULL-owner) scans to a configured owner so
# existing history isn't orphaned when per-user isolation turns on. Idempotent — only
# touches NULL-owner rows, and new scans always carry an owner. Value is validated to
# plain email characters before interpolation (no params in DDL-style _SCHEMA execution).
_LEGACY_OWNER = os.environ.get("ACP_LEGACY_SCAN_OWNER", "").strip().lower()
if _LEGACY_OWNER and "@" in _LEGACY_OWNER and all(c.isalnum() or c in ".+-_@" for c in _LEGACY_OWNER):
    _SCHEMA.append(f"UPDATE scan_runs SET owner_email='{_LEGACY_OWNER}' WHERE owner_email IS NULL")
    # Same env var, same one-time shape, for the documents table. Deliberately the SAME switch
    # rather than a second one: an operator who has already decided who owns pre-isolation
    # history should not have to decide it twice, and two switches is how the two tables end up
    # disagreeing about the same scan's documents.
    _SCHEMA.append(f"UPDATE documents SET owner_email='{_LEGACY_OWNER}' WHERE owner_email IS NULL")

# ── Power BI read-only views (Postgres only) ────────────────────────────────
# Three views that expose ACP scan data for Power BI DirectQuery. They are
# created by _PgAdapter.init_schema() after the main _SCHEMA tables are ready.
# `CREATE OR REPLACE VIEW` is Postgres-specific; SQLite tests that cover the
# same logic use `CREATE VIEW IF NOT EXISTS` (see tests/test_powerbi_views.py).
#
# Companion role: scripts/create_powerbi_role.sql grants SELECT on these views
# to the `powerbi_ro` login — no access to underlying tables, no write access.
_PG_VIEWS = [
    # Scan-level summary: one row per scan, aggregated findings and certifiability.
    # Powers the overview page of the Power BI compliance dashboard.
    """CREATE OR REPLACE VIEW vw_scan_summary AS
SELECT
    sr.id            AS scan_id,
    sr.owner_email,
    sr.completed_at,
    sr.source,
    sr.rubric_name,
    sr.avg_score,
    sr.files         AS total_files,
    sr.certifiable,
    sr.uncertain,
    sr.error,
    COUNT(ir.rule_id) FILTER (WHERE ir.severity = 'CRITICAL')  AS critical_findings,
    COUNT(ir.rule_id) FILTER (WHERE ir.severity = 'SERIOUS')   AS serious_findings,
    COUNT(ir.rule_id) FILTER (WHERE ir.severity = 'MODERATE')  AS moderate_findings,
    COUNT(ir.rule_id) FILTER (WHERE ir.severity = 'MINOR')     AS minor_findings,
    COUNT(DISTINCT pf.file)                                    AS pii_docs_affected,
    CASE WHEN COALESCE(sr.files, 0) > 0
         THEN ROUND(100.0 * sr.certifiable / sr.files)
         ELSE 0 END                                            AS audit_ready_pct
FROM scan_runs sr
LEFT JOIN issue_records ir ON ir.scan_id = sr.id
LEFT JOIN pii_findings  pf ON pf.scan_id = sr.id
GROUP BY sr.id, sr.owner_email, sr.completed_at, sr.source, sr.rubric_name,
         sr.avg_score, sr.files, sr.certifiable, sr.uncertain, sr.error""",

    # Per-finding detail: one row per WCAG issue, enriched with scan/file metadata.
    # Powers the findings drill-through report and the by-criterion breakdown.
    """CREATE OR REPLACE VIEW vw_finding_detail AS
SELECT
    ir.scan_id,
    sr.owner_email,
    sr.completed_at,
    ir.file,
    fr.engine,
    ir.wcag                                   AS wcag_criterion,
    ir.severity,
    ir.rule_id,
    COALESCE(rt.plain_name, ir.rule_id)       AS plain_name,
    ir.detail,
    ir.page,
    ir.location
FROM issue_records ir
JOIN  scan_runs       sr ON sr.id      = ir.scan_id
LEFT JOIN file_records   fr ON fr.scan_id = ir.scan_id AND fr.file = ir.file
LEFT JOIN scan_rule_traces rt ON rt.scan_id = ir.scan_id
                              AND rt.file    = ir.file
                              AND rt.rule_id = ir.rule_id""",

    # Per-rule-per-file outcomes: which rules were evaluated and what happened.
    # Powers the rule-coverage heatmap (pass / fail / error / not-evaluated).
    """CREATE OR REPLACE VIEW vw_rule_coverage AS
SELECT
    rt.scan_id,
    sr.owner_email,
    sr.completed_at,
    rt.file,
    fr.engine,
    rt.rule_id,
    rt.rule_name,
    COALESCE(rt.plain_name, rt.rule_id)  AS plain_name,
    rt.level,
    rt.fix_mode,
    rt.outcome,
    rt.finding_count
FROM scan_rule_traces rt
JOIN  scan_runs    sr ON sr.id      = rt.scan_id
LEFT JOIN file_records fr ON fr.scan_id = rt.scan_id AND fr.file = rt.file""",
]

_UPSERT_INV = (
    "INSERT INTO inventory(file,first_seen,last_seen,last_status,last_score) "
    "VALUES(%s,%s,%s,%s,%s) "
    "ON CONFLICT(file) DO UPDATE SET last_seen=EXCLUDED.last_seen, "
    "last_status=EXCLUDED.last_status, last_score=EXCLUDED.last_score"
)

# ── Assessment policy ───────────────────────────────────────────────────────
# The capability tables and the outcome gate now live in assessment_policy; this module is the
# persistence layer again. Re-exported rather than repointed at ~40 call sites: `from store
# import RULE_FORMATS` still works, so the move carries no behavioural risk and no caller churn.
from assessment_policy import (  # noqa: F401,E402  (re-export)
    RULE_CATALOG, RULE_FORMATS, REVIEW_FORMATS, SCOPE_PRESETS, SCOPE_SETTING,
    LEVEL_RANK, TARGET_LEVELS, DEFAULT_TARGET, NOT_EVALUATED, REVIEW,
    _LEGACY_NOT_EVALUATED, _SUPERSEDING_OUTCOMES, _SC_LEVEL, _ALL_FORMATS,
    active_scope, scope_problem, parse_scope_setting,
    in_scope, in_target, parse_target, config_target,
    formats_in_scope, file_in_scope, selected_documents, assignments, files_assigned_to,
    scope_as_json, scope_from_json, criteria_for_format,
    filter_issues_to_target, filter_issues_to_scope, _rule_outcome, _certify, _registry_for,
    _split_sc_counts, _file_format, _extract_sc, _pages_csv,
)

# WCAG's four top-level principles, keyed by the leading digit of a success-criterion number
# (1.x.x Perceivable · 2.x.x Operable · 3.x.x Understandable · 4.x.x Robust). Used to group
# evaluated criteria into a per-principle pass rate for the certification report (backlog R8).
_WCAG_PRINCIPLE = {"1": "Perceivable", "2": "Operable", "3": "Understandable", "4": "Robust"}

# Rule catalog loaded once at import time (grouped by engine — the raw JSON shape, NOT the flat
# RULE_CATALOG list). Used by _save_file_manifest via catalog.get(ext, []). Single read instead
# of one per file in the fan-out path.
_CATALOG_JSON: dict = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "rule-catalog.json").read_text()
)
# Sentinel for scope cache: distinguishes "not cached yet" from None ("no restriction").
_SCOPE_ABSENT = object()


# `from assessment_policy import X` binds a VALUE, not a reference — so any global that module
# REBINDS at runtime would freeze here at its pre-init snapshot. `_CAN_CERTIFY_PASS` and
# `_NEEDS_REVIEW_ON_CLEAN` are exactly that: empty until the first `_rule_outcome` call performs
# the lazy registry init, after which the eagerly-imported copy stays empty forever. Reading
# `store._CAN_CERTIFY_PASS` then silently reports "nothing may certify a pass".
#
# PEP 562 module __getattr__ keeps those live: it fires only for names this module does not
# already define, so the eager imports above stay fast and statically visible, and anything
# rebound is fetched fresh from where it actually lives.
def __getattr__(name: str):
    import assessment_policy as _p
    try:
        return getattr(_p, name)
    except AttributeError:
        raise AttributeError(f"module 'store' has no attribute {name!r}") from None

# ── Adapters ────────────────────────────────────────────────────────────────

class _SQLiteAdapter:
    def __init__(self, path: str):
        self._path = path

    def init_schema(self) -> None:
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.cursor()
            for stmt in _SCHEMA:
                # The migration ALTERs use Postgres's ADD COLUMN IF NOT EXISTS,
                # which SQLite rejects as a syntax error — a fresh checkout could
                # not boot in SQLite mode at all. Translate to plain ADD COLUMN
                # and treat "duplicate column" (already migrated) as success.
                if stmt.strip().upper().startswith("ALTER TABLE"):
                    try:
                        cur.execute(stmt.replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN"))
                    except sqlite3.OperationalError as e:
                        if "duplicate column" not in str(e).lower():
                            raise
                else:
                    cur.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    @contextlib.contextmanager
    def cursor(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, cur, sql: str, params: tuple = ()) -> None:
        cur.execute(sql.replace("%s", "?"), params)

    def executemany(self, cur, sql: str, params_list) -> None:
        cur.executemany(sql.replace("%s", "?"), params_list)

    def fetchall(self, cur) -> list[dict]:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def fetchone(self, cur) -> dict | None:
        if cur.description is None:
            return None
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    supports_skip_locked: bool = False


def logical_name(name: str) -> str:
    """Strip the ' (N)' disambiguation suffix to recover the logical document name.

    Drive appends it on a duplicate upload, and scanner._dedupe_names appends it when one
    listing contains two files with the identical name (Drive permits that; a filesystem
    doesn't).
    """
    return re.sub(r" \(\d+\)(\.[^.]+)$", r"\1", name or "")


# get_scan is a READ path the dashboard polls every second or two. Logging the shadow filter
# on every call printed the same line 26 times in five minutes. Remember which scans have
# already been reported; a restart re-reports once, which is the point of the line.
_shadow_logged: set[str] = set()


def shadowed_acp_outputs(files: list[dict]) -> set[str]:
    """The file names in this scan that are ACP's OWN output shadowing the source document it
    was made from — the "1 Drive document, 2 scanned files" bug.

    Discriminated by the in-document ACP stamp (file_records.acp_stamped, set by
    detect_acp_stamp over the real bytes), NEVER by the ' (N)' suffix: _dedupe_names renames
    whichever item Drive happened to return second, which may just as easily be the user's
    original.

    A stamped file is shadowing only when an UNSTAMPED file shares its logical name. A
    certified document published back into the estate stands alone under its own name, and
    must still be scanned, counted, and monitored for drift — so it is never dropped here.
    """
    by_name: dict[str, list[dict]] = {}
    for f in files:
        by_name.setdefault(logical_name(f.get("file", "")), []).append(f)
    shadowed: set[str] = set()
    for group in by_name.values():
        if len(group) < 2:
            continue
        if not any(not f.get("acp_stamped") for f in group):
            continue        # every copy is ACP output — none of them shadows a source
        shadowed.update(f["file"] for f in group if f.get("acp_stamped"))
    return shadowed


_SC_DEFERRED = re.compile(r"^(\d+\.\d+\.\d+)/deferred$")


def _canonical_rule_id(rule_id: str) -> str:
    """The one hitl_queue.rule_id a WCAG criterion may occupy for a given (scan, file).

    '1.1.1/deferred' → '1.1.1'. A deferral is the same criterion as the proposals and the
    residual-review rows; three writers used to open up to three rows for it, all rendering as
    "WCAG 1.1.1" once scOf() strips the suffix.

    Anything that is not a dotted SC with a '/deferred' suffix is returned untouched —
    'auto/verify' is a pseudo-rule ("an automatic fix was applied, please eyeball it"), not a
    criterion, and must keep a row of its own.
    """
    m = _SC_DEFERRED.match(rule_id or "")
    return m.group(1) if m else rule_id


def db_max_conn(env: dict | None = None) -> int:
    """How many Postgres connections this replica may hold.

    Two INDEPENDENT terms, added together — conflating them was the 2026-08-30 production bug
    (`psycopg2.pool.PoolError: connection pool exhausted` from POST /discovery/preflight and
    POST /scans, 16-64 times per revision across 5 revisions):

    - `workers` — in-process worker THREADS (ACP_WORKERS, api/worker_main.py). Each one holds a
      connection while it runs a job. Real concurrency for the WORKER container, which defaults
      ACP_WORKERS>0; correctly 0 for the API container, which runs ACP_WORKERS=0 by design (the
      split topology, ADR 0013/#113) and has no local worker threads at all.
    - `_API_HEADROOM_CONN` — concurrent DB-touching HTTP handlers. This is NOT scaled by
      `workers`: the API container serves however many requests land on it regardless of its own
      (deliberately zero) worker-thread count. Inventory pagination, /jobs polling,
      queue-estimate, HITL and decision reads all land on the SAME api container simultaneously
      whether or not it runs any local workers.

    The old formula was `max(2, workers) + _API_HEADROOM_CONN`: with ACP_WORKERS="0" (a
    non-empty string, so it survives the `or 4` fallback below) that collapsed to
    `max(2, 0) + 8 == 10` — the API replica's own pool floored at 10 connections while serving
    real concurrent HTTP traffic that routinely exceeded that. `workers` is no longer routed
    through `max(2, ...)` for exactly that reason: 0 is a legitimate value for a serve-only
    replica, not a degenerate one to be floored away. The overall `max(2, ...)` below stays only
    as a final sanity floor (moot at any headroom this repo has ever configured; kept for a
    hypothetical near-zero override).

    Sized against the two constraints that actually bound it in production: Postgres's own
    max_connections (150, confirmed live) and the API/worker container replica counts
    (deploy/public/deploy.sh — API is `--min-replicas 1 --max-replicas 1`, ALWAYS exactly one
    replica; the worker tier is `--min-replicas 1 --max-replicas 3` at `ACP_WORKER_COUNT:-2`
    workers/replica by default). See the PR body for the full arithmetic — this is deliberately
    not a bigger magic number picked without that check.

    Override with ACP_DB_MAX_CONN if the worker count, replica count, or Postgres tier changes
    enough to invalidate that arithmetic.
    """
    e = os.environ if env is None else env
    explicit = e.get("ACP_DB_MAX_CONN")
    if explicit:
        return max(2, int(explicit))
    try:
        workers = int(e.get("ACP_WORKERS") or 4)
    except ValueError:
        workers = 4
    workers = max(0, workers)  # a bad/negative override must not go on to STARVE the headroom term
    return max(2, workers + _API_HEADROOM_CONN)


# Concurrent DB-touching HTTP handlers this replica may need to serve at once, independent of
# ACP_WORKERS entirely (see db_max_conn's docstring for why the two must not be conflated).
#
# Raised from 8 to 16 after the 2026-08-30 incident — deliberately NOT raised further, and this
# is a considered stopping point, not a shortfall of nerve. Two separate resource dimensions are
# in play, and only one of them is this constant's business:
#   - CONNECTION COUNT: the incident's own read was "comfortably more than 10 concurrent
#     DB-touching HTTP handlers" (inventory pagination + /jobs polling + queue-estimate + HITL +
#     decision reads, simultaneously) against the old formula's 10-connection floor. 8 of pure
#     headroom was already short of that before the ACP_WORKERS=0 conflation bug shaved it down
#     further; 16 clears the documented traffic with real margin, checked against the deployed
#     fleet's real replica counts in db_max_conn's docstring and tests/test_db_pool.py.
#   - CPU: a separate, parallel incident-review thread (not independently verified from this
#     PR — see the PR body) reported the production Postgres server near-continuously
#     CPU-saturated (~98% mean, ~24h). Connection-slot headroom and CPU headroom are ORTHOGONAL —
#     a server can have free connection slots while being fully CPU-bound — and more concurrent
#     connections against an already CPU-saturated server can worsen contention rather than help.
#     This constant cannot see that dimension at all, so it deliberately stops at "clearly enough
#     to fix the incident's own documented connection-count shortfall" rather than reaching for
#     a larger number the connection arithmetic alone would also technically clear (this repo's
#     replica counts leave room past 16 — see the docstring). Raising it further than this is an
#     operational capacity decision that needs BOTH dimensions checked, not a code default a
#     formula fix should make unilaterally — use ACP_DB_MAX_CONN for that, once made.
_API_HEADROOM_CONN = 16


class _PgAdapter:
    _MIN_CONN = 1
    _MAX_CONN = db_max_conn()

    def __init__(self, url: str):
        # Strip query params that confuse psycopg2 (e.g. ?sslmode=require can
        # get mangled when stored via az containerapp secret set). Pass them as
        # explicit kwargs instead.
        import urllib.parse as _up
        parsed = _up.urlparse(url)
        params = dict(_up.parse_qsl(parsed.query))
        clean = parsed._replace(query="").geturl()
        self._url = clean
        self._ssl_kwargs: dict = {}
        if "sslmode" in params:
            self._ssl_kwargs["sslmode"] = params["sslmode"]
        self._pool = None  # lazy init after schema is applied

    def _connect_kwargs(self) -> dict:
        return {"dsn": self._url, **self._ssl_kwargs}

    def _get_pool(self):
        if self._pool is None:
            import psycopg2.pool
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                self._MIN_CONN, self._MAX_CONN, self._url, **self._ssl_kwargs)
        return self._pool

    _SCHEMA_VERSION_TABLE = "acp_schema_version"

    # ORDERING, not identity — and the distinction is the whole reason this is an integer.
    #
    # The first version of this used the checksum alone: migrate when the marker differs from
    # what this build would apply. That is correct with one version of the code running and
    # WRONG during every rolling deploy, which is the only time it matters. A checksum has no
    # order, so an OLD replica booting after a new one has migrated sees "different" and
    # migrates backwards, rewriting the marker with its own checksum; the next new replica sees
    # "different" again and migrates forwards. Measured on a real server, alternating versions
    # across five boots: five migrations, marker flapping e92e54c9 / 3d9ee8f7 / e92e54c9 / …
    # — the exact lock storm this class exists to prevent, reappearing precisely while both
    # versions are booting and traffic is live.
    #
    # An integer fixes it because it can be COMPARED. A replica migrates only when the database
    # is behind what this build needs; an older replica meeting a newer schema does nothing,
    # which is the correct behaviour — additive migrations leave it able to run (see
    # docs/adr/0045 for why every migration must be additive for that to hold).
    #
    # BUMP THIS whenever _SCHEMA or _PG_VIEWS changes. Forgetting is caught, not trusted:
    # _SCHEMA_CHECKSUM_AT_VERSION below pins the DDL this version corresponds to, and
    # test_the_schema_version_was_bumped_with_the_schema fails when they drift apart.
    # v2 adds scan_folder_completions (additive, per docs/adr/0045 — an older replica keeps
    # serving: it neither reads nor writes that table, and the counter it guards behaves for
    # that replica exactly as it did at v1).
    # v3 adds scan_runs.content_workspace_version_id (ADR 0044) plus its partial index
    # (additive — a NULL-defaulting nullable column and an index neither read nor written by
    # an older replica, which keeps serving every connector-sourced scan exactly as before).
    # v4 adds file_records.written_job / .written_attempt, the result-write fence
    # (save_file_result). Additive on the same terms, and additive in BEHAVIOUR too, which is the
    # part worth checking rather than assuming: a v3 replica writes NULL into both columns, and
    # the fence reads a NULL on either side as ALLOW — so an old replica keeps writing results
    # exactly as it did, it simply is not fenced. The failure mode a non-additive change would
    # have had here (old replica's writes rejected, results silently lost) is the reason the
    # predicate is built out of allow-clauses with a single fall-through refusal.
    # (v3 was independently assigned to two different additive changes by two concurrent
    # sessions — this repo squash-merges, so both landed — and is renumbered to v4 here rather
    # than picking one side's checksum over the other's real, both-present DDL.)
    # v5 AND v6 were each assigned twice, exactly as v3 was, and are resolved the same way — by
    # renumbering over the union of every side's DDL rather than picking one side's checksum.
    # Three collisions on this one constant now (v3, v5, v6), all from concurrent branches that
    # were each correct in isolation:
    #   * #1155's lifecycle control plane — disposition_policy gains version/description/
    #     updated_at, plus the lifecycle_evaluation and effective_disposition tables and indexes.
    #   * #1169/#1170 — disposition_audit gains policy_version.
    #   * ADR 0047's seven ACR workspace tables and their indexes.
    # Every one really landed, so no previously-recorded checksum describes the schema that now
    # exists; keeping any of them would tell a booting replica the DDL matches while part of it is
    # missing from that hash. v7 is computed over the merged _SCHEMA below.
    #
    # WORTH NOTICING, because the pattern is the point rather than any one collision: this
    # constant is hand-maintained and every long-lived branch that touches _SCHEMA collides on it,
    # deterministically. The renumber-over-the-union rule resolves each instance correctly and does
    # nothing to stop the next. Deriving the version from the checksum (bump iff the hash moved)
    # would remove the class, but that changes migration bookkeeping for everyone and belongs in
    # its own change, not smuggled into a feature branch's conflict resolution.
    #
    # Still additive, and additive in BEHAVIOUR on every half. For the ACR tables the argument is
    # simpler than v4's fence: a replica without ACR code never reads or writes them — they are
    # inert until a replica carrying api/acr_*.py serves a request against them.
    # v10 adds tenant_queue_state plus idx_jobs_tenant_fair. Older replicas ignore both and keep
    # their original FIFO claim; newer replicas can use them immediately, so rollout is safe.
    # v11 adds workspace_roles, workspace_role_permissions and idx_workspace_roles_name (the
    # workspace RBAC catalog, PRD §12). Additive on the same terms as the ACR tables at v7, and
    # additive in BEHAVIOUR for the stronger reason: the whole feature is behind
    # ACP_WORKSPACE_RBAC_ENABLED, so a replica that carries the code but not the flag reads these
    # tables and enforces nothing from them, and a replica without the code never touches them at
    # all. Neither can lose access to a surface it has today, because nothing consults these rows
    # until the flag turns the enforcement on.
    # v12 adds scan_inventory.site_id and .library_name — which SharePoint site and which document
    # library each discovered row came from, now that one run can span up to 30 sites and the
    # scan's scope holds a SET rather than one site id. Additive on the usual terms, and additive
    # in BEHAVIOUR for the same reason v4's fence was: a replica without this code writes neither
    # column, add_inventory COALESCEs both through its ON CONFLICT, and every consumer reads them
    # as optional — so an older replica keeps listing and inventorying exactly as it does today,
    # it simply records no site attribution. Nothing reads these columns to decide anything yet;
    # they are the identity the later SharePoint phases (per-site metadata, per-library delta
    # cursors, exception reports, write-back targeting) need preserved at the row grain, because
    # once a run covers a set of sites the run itself can no longer answer "which site is this
    # document in" for any individual file.
    _SCHEMA_VERSION = 12
    _SCHEMA_CHECKSUM_AT_VERSION = "1b63b55167c0def43a08e47542ff986e"
    # Namespaced so it cannot collide with an advisory lock taken anywhere else. Session-scoped
    # (pg_advisory_lock, not _xact) because the migration spans several transactions.
    _MIGRATION_ADVISORY_KEY = 0x4143500001          # 'ACP' + slot 1

    @staticmethod
    def _schema_checksum() -> str:
        """Identity of the DDL this build expects. Changing any statement changes it, which is
        what makes 'the schema is already what I would apply' a decidable question."""
        import hashlib
        h = hashlib.sha256()
        for stmt in (*_SCHEMA, *_PG_VIEWS):
            h.update(" ".join(stmt.split()).encode())
        return h.hexdigest()[:32]

    def init_schema(self) -> None:
        """Verify the schema; migrate only if it differs, and only one process at a time.

        THE PRODUCTION FAILURE THIS FIXES (reproduced 2026-08-31 on PostgreSQL 16, six replicas
        booting against live reads). Store.__init__ calls this unconditionally, so EVERY API and
        worker replica used to replay all 139 statements of _SCHEMA + _PG_VIEWS on every boot, in
        ONE transaction (psycopg2 defaults to autocommit=False) with no lock_timeout — holding
        ACCESS EXCLUSIVE on 40 tables until the final commit.

        The statements are no-ops on an already-migrated database, and that does not help:

            NOTICE:  column "phase" of relation "jobs" already exists, skipping
            AccessExclusiveLock|jobs|t

        ADD COLUMN IF NOT EXISTS takes the exclusive lock BEFORE discovering it has nothing to
        do. So each replica locked 40 tables to change nothing, and the deadlock needs only that
        plus two readers that touch the same tables in opposite orders — both of which exist:

            queue_estimate        jobs -> scan_runs   (the pickup estimate; 500 in production)
            sweep_orphaned_scans  scan_runs -> jobs   (the reconciliation sweep)

        The four-process cycle Postgres reported, verbatim from the server log:

            sweep_orphaned_scans  waits AccessShare     on scan_runs  blocked by ALTER jobs
            ALTER TABLE jobs …    waits AccessExclusive on jobs       blocked by queue_estimate
            queue_estimate        waits AccessShare     on scan_runs  blocked by ALTER scan_runs
            ALTER TABLE scan_runs waits AccessExclusive on scan_runs  blocked by the sweep

        Five of six replica boots failed with DeadlockDetected inside this function; with the
        change, twelve of twelve succeed and exactly one runs DDL.

        NOT A CONNECTION-POOL PROBLEM, and enlarging the pool makes it worse rather than better:
        no PoolError appeared in the reproduction at all, and every extra connection is another
        participant in the cycle. The 503s are downstream — reads queue behind the exclusive
        locks until _getconn's 5s wait expires.

        WHAT THIS DOES NOT FIX. A genuine migration still takes genuine exclusive locks, and
        readers can still deadlock against it: three queue_estimate deadlocks remained against
        the one process that really did apply DDL. Making that safe needs migration to run as a
        controlled deployment step rather than concurrently with live traffic. lock_timeout below
        bounds the damage — a blocked migration fails fast and visibly instead of holding its
        locks while every reader queues — but bounding is not preventing.
        """
        import psycopg2
        want = self._schema_checksum()
        conn = psycopg2.connect(self._url, **self._ssl_kwargs)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                if self._schema_is_current(cur, want):
                    return                      # the overwhelmingly common path: no DDL, no locks
                # Exactly one migrator. Concurrent boots queue on this instead of forming a lock
                # cycle with each other — session-scoped, so it spans the transaction below.
                cur.execute("SELECT pg_advisory_lock(%s)", (self._MIGRATION_ADVISORY_KEY,))
                try:
                    # Re-check: another replica may have migrated while we waited for the lock.
                    if self._schema_is_current(cur, want):
                        return
                    self._apply_schema(conn, want)
                finally:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (self._MIGRATION_ADVISORY_KEY,))
        finally:
            conn.close()

    def _schema_is_current(self, cur, want: str) -> bool:
        """Is the database AT OR AHEAD OF the schema this build needs?

        One catalog read plus one small SELECT, both ACCESS SHARE. Never blocks a reader.

        `>=`, not `==`, and that is the mixed-version fix rather than a loose comparison: during
        a rolling deploy an old replica meets a schema newer than its own, and the right answer
        is to leave it alone. Equality made it migrate BACKWARDS — see _SCHEMA_VERSION.

        Returns False on anything unexpected — a missing table, an unreadable row, a null
        version — so an unrecognised database is migrated rather than assumed good. The
        expensive answer is the safe one here.
        """
        try:
            cur.execute("SELECT to_regclass(%s)", (f"public.{self._SCHEMA_VERSION_TABLE}",))
            row = cur.fetchone()
            if not row or row[0] is None:
                return False
            cur.execute(f"SELECT version FROM {self._SCHEMA_VERSION_TABLE} "
                        "ORDER BY version DESC LIMIT 1")
            got = cur.fetchone()
            if not got or got[0] is None:
                return False
            return int(got[0]) >= self._SCHEMA_VERSION
        except Exception:                       # noqa: BLE001 — unknown state means migrate
            return False

    def _apply_schema(self, conn, want: str) -> None:
        """The DDL itself, under the advisory lock, with a bounded wait.

        lock_timeout rather than an unbounded wait: a migration that cannot get its lock within
        the window is the case that took production down, and failing there is recoverable —
        the deploy reports it and the previous schema is untouched. Blocking instead means every
        reader queues behind a transaction that is itself waiting.
        """
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                for stmt in _SCHEMA:
                    cur.execute(stmt)
                for stmt in _PG_VIEWS:
                    cur.execute(stmt)
                # Table name spelled out rather than interpolated from _SCHEMA_VERSION_TABLE:
                # tests/test_reset_purges_blobs.py parses store.py for `CREATE TABLE [IF NOT
                # EXISTS] <name>` to prove no table escapes the RESET classification, and an
                # f-string placeholder makes that parser read the name as "IF". Pinned by
                # test_the_marker_table_name_is_greppable.
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS acp_schema_version ("
                    "version INTEGER PRIMARY KEY, checksum TEXT, "
                    "applied_at TIMESTAMPTZ DEFAULT now())")
                # A HISTORY, one row per version, not a single row replaced wholesale. Deleting
                # and re-inserting would let a concurrent older replica's write leave the table
                # momentarily empty, which _schema_is_current reads as "unknown, migrate". Rows
                # only ever accumulate, and the check reads MAX(version) — so an older build's
                # insert can never lower what a newer one recorded. checksum is diagnostic: it
                # says which DDL a version corresponded to when it was applied.
                cur.execute(
                    f"INSERT INTO {self._SCHEMA_VERSION_TABLE} (version, checksum) "
                    "VALUES (%s, %s) ON CONFLICT (version) DO UPDATE SET checksum=EXCLUDED.checksum",
                    (self._SCHEMA_VERSION, want))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = True

    def _getconn(self, timeout: float = 5.0):
        """psycopg2's ThreadedConnectionPool.getconn raises PoolError the moment the pool is
        empty — it never waits. A request arriving during a burst should queue for a moment,
        not fail. Beyond the timeout the error still surfaces: a pool that stays empty for
        seconds is a real problem and must not be silently swallowed."""
        import psycopg2.pool
        pool = self._get_pool()
        deadline = time.monotonic() + timeout
        while True:
            try:
                return pool.getconn()
            except psycopg2.pool.PoolError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    @contextlib.contextmanager
    def cursor(self):
        import psycopg2.extras
        pool = self._get_pool()
        conn = self._getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    def execute(self, cur, sql: str, params: tuple = ()) -> None:
        cur.execute(sql, params)

    def executemany(self, cur, sql: str, params_list) -> None:
        import psycopg2.extras
        psycopg2.extras.execute_batch(cur, sql, params_list)

    def fetchall(self, cur) -> list[dict]:
        return [dict(r) for r in (cur.fetchall() or [])]

    def fetchone(self, cur) -> dict | None:
        row = cur.fetchone()
        return dict(row) if row else None

    supports_skip_locked: bool = True


# ── Queue precedence ─────────────────────────────────────────────────────────
# `claim_job` orders by (priority, run_after) and idx_jobs_claim2 indexes exactly that, so
# precedence has always been supported by the schema — it was simply never used. Every job was
# enqueued at the default 100, which made the queue pure FIFO: a Discovery job arriving during
# an Assess fan-out waited behind every scan_file already queued, and on a large estate that is
# thousands of downloads. The wait was invisible in the UI, which showed the scan as "queued"
# with no indication of what it was queued behind.
DEFAULT_JOB_PRIORITY = 100

# LOWER is claimed first. Discovery-stage jobs list and classify metadata — they open no file
# and download nothing (ADR 0020) — so they are short, and letting one overtake content work
# costs that work a few hundred milliseconds. The reverse costs Discovery the length of an
# entire Assess backlog.
DISCOVERY_JOB_PRIORITY = 10

# The three job types that make up the Discovery stage:
#   scan_discover — lists the source, persists the inventory, fans out
#   scan_folder   — one per top-level folder, the per-folder BFS enumeration it fans out TO
#   scan          — the monolithic entry job; under ACP_DEFER_ANALYSIS_TO_ASSESS=1 (the shipped
#                   default, and what deploy/public/deploy.sh sets) it discovers and stops
#
# scan_folder matters most and is the one easiest to miss. #1121's reserved-slot lane claims
# only `scan_discover`, so the entry job starts at once and then its folder jobs — the work that
# actually enumerates the estate — drop back into the general queue behind the backlog. A
# reserved lane without this covers the starting gun and not the race.
_DISCOVERY_JOB_TYPES = frozenset({"scan_discover", "scan_folder", "scan"})


def sharepoint_scope_sites(scope: dict | None) -> tuple[str, ...]:
    """Every SharePoint site a recorded scope covered, as an order-independent key.

    Two scopes describe the same BOUNDARY when they cover the same set of sites, whatever order
    the operator picked them in — so this sorts, and callers compare the tuples rather than the
    raw fields.

    Reads `sites` (the multi-site list, `[{"id", "name"}, ...]`) and falls back to the singular
    `site` for every run recorded before multi-site existed. That fallback is what keeps an
    incremental comparison working across the change: without it every historical SharePoint run
    would key to () and a one-site scan would match a baseline taken on a different site — the
    boundary check silently disabled, which is worse than no check at all.

    Non-SharePoint scopes have neither field and key to (), which is the constant the singular
    comparison already produced for them.
    """
    scope = scope or {}
    sites = scope.get("sites")
    if isinstance(sites, list) and sites:
        ids = [str(s.get("id")) if isinstance(s, dict) else str(s) for s in sites]
        return tuple(sorted(i for i in ids if i and i != "None"))
    one = scope.get("site")
    return (str(one),) if one else ()


def job_priority(job_type: str) -> int:
    """Queue precedence for a job type. Callers may still pass `priority=` explicitly to
    override — this only decides what happens when they say nothing, which is every caller
    in this codebase today."""
    return DISCOVERY_JOB_PRIORITY if job_type in _DISCOVERY_JOB_TYPES else DEFAULT_JOB_PRIORITY


# ── Store ────────────────────────────────────────────────────────────────────

class Store:
    # Serializes the tiny Postgres claim *decision*, not job execution. Without this transaction
    # lock, two workers beginning at the same instant can both observe tenant A at zero active
    # claims and each select one of A's rows via SKIP LOCKED. The jobs still run concurrently;
    # only the few-millisecond selection step is ordered so the fairness promise is real.
    _FAIR_CLAIM_ADVISORY_KEY = 0x4143500002       # 'ACP' + slot 2

    def __init__(self) -> None:
        self._db: _SQLiteAdapter | _PgAdapter = (
            _PgAdapter(_DATABASE_URL) if _DATABASE_URL else _SQLiteAdapter(str(_SQLITE_PATH))
        )
        self._db.init_schema()
        self._scope_cache: dict = {}
        self._scope_rules_cache: dict = {}
        self._inventory_cache: dict = {}

    def _file_produced_no_result(self, f: dict) -> bool:
        """Did this file's analysis fail to produce a result at all?

        Three independent signals, because different writers reach the manifest with different
        shapes and any one of them alone would miss a real case:

          * `status` — what Rubric.assess returned. "error" is an engine that did not succeed;
            "skipped" is a file deliberately not analysed (an ACP-generated shadow of its own
            source, handlers.py). Neither looked at the document.
          * `succeeded is False` — the raw engine flag, present on hand-built records and on
            the storeless paths that never go through the rubric.
          * an error carrying no `rule` — scanner.py:2696/2714 report whole-file failures as
            `{"message": ..., "rule": None}`. Something failed that cannot be attributed to a
            rule, so the rules it did not name cannot be claimed either.

        Conservative on purpose: every one of these means "do not certify this file", and the
        cost of being wrong in that direction is a warning, while the cost of being wrong in the
        other is a compliance claim about a document nobody read.
        """
        if (f.get("status") or "").lower() in ("error", "skipped"):
            return True
        if f.get("succeeded") is False:
            return True
        return any(not (isinstance(e, dict) and e.get("rule")) for e in (f.get("errors") or []))

    def _save_file_manifest(self, cur, sid: str, f: dict, catalog: dict) -> None:
        """Compute and persist the per-rule execution manifest for one file.

        WHAT THIS USED TO RECORD, AND WHY IT WAS WORSE THAN RECORDING NOTHING. Every rule in the
        file's catalog that was not in `issues` and not in `errors` was written PASS. Two things
        made that a certification of work that was never done, and both were measured against a
        real Store rather than read off the source:

          * `errors` IS NOT ON THE FILE DICT ON THE PRODUCTION PATH. Rubric.assess
            (scripts/rubric.py:55) CONSUMES the engine's error list and returns `status` and
            `skipped_rules` in its place; scanner.analyse_and_assess builds the record from
            `**assessed`, so `f["errors"]` was absent on every production write. `error_ids` was
            therefore always empty and the ERROR branch below was unreachable — which made
            `rules_errored_total` structurally 0 and `complete` structurally true for every scan
            this table has ever held.
          * A file the engine could not open reaches here with no issues and no errors, so the
            `else` claimed the whole catalog as PASS. Measured: a .docx that failed to open
            recorded 17 PASS, 0 ERROR, completeness 100%, complete=true.

        So a file that produced no result now records NOT_CHECKED for every applicable rule
        rather than PASS. "We did not look" and "we looked and found nothing" are different
        claims and only one of them may be certified; PASS was asserting the second on evidence
        for neither.

        `errors` is still read, and is now populated (scanner.py threads `raw["errors"]` onto the
        record), because it is the only thing that says WHICH rules errored. Where it is absent
        the count still survives on file_records.skipped_rules, and get_scan_manifest reports the
        difference as unattributed rather than resolving it to PASS.
        """
        ext = Path(f["file"]).suffix.lower().lstrip(".")
        rules = catalog.get(ext, [])
        if not rules:
            return
        # Which rule IDs actually produced findings (FAIL)?
        fail_ids = {i["ruleId"] for i in f.get("issues", [])}
        # Which rule IDs had engine errors (ERROR)?
        error_ids = {e["rule"] for e in f.get("errors", [])
                     if isinstance(e, dict) and e.get("rule")}
        # Finding count per rule
        counts: dict[str, int] = {}
        for i in f.get("issues", []):
            counts[i["ruleId"]] = counts.get(i["ruleId"], 0) + 1
        # The default for a rule nothing said anything about. PASS only when the file was
        # actually analysed; otherwise the honest answer is that it was never checked.
        unchecked = self._file_produced_no_result(f)
        manifest_rows = []
        for rule in rules:
            rid = rule["id"]
            if rid in error_ids:
                status = "ERROR"
            elif rid in fail_ids:
                # A finding is evidence the rule ran, so it stays FAIL even on a file whose
                # analysis failed overall — a partial result is still a result for that rule.
                status = "FAIL"
            elif unchecked:
                status = "NOT_CHECKED"
            else:
                status = "PASS"
            manifest_rows.append((sid, f["file"], rid, status, counts.get(rid, 0)))
        self._db.executemany(cur,
            "INSERT INTO scan_file_manifests(scan_id,file,rule_id,status,finding_count) "
            "VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT(scan_id,file,rule_id) DO UPDATE SET "
            "status=EXCLUDED.status,finding_count=EXCLUDED.finding_count",
            manifest_rows)

    def save_scan(self, report: dict) -> str:
        # Reuse the scan_id generated in run_scan() so the Langfuse trace ID
        # and the DB scan_id are the same — enables join in Langfuse by scan_id.
        sid = report.pop("_scan_id", None) or uuid.uuid4().hex[:12]
        # run_scan()'s hint for populating scan_inventory below (see there) — not part of the
        # report's public shape, and absent on a report built by hand (most tests), in which
        # case that step is simply skipped, same as today.
        _inventory_items = report.pop("_inventory_items", None)
        s = report["summary"]
        # The level this scan was run for. A criterion above it is not assessed (see in_target).
        target = parse_target((report.get("rubric") or {}).get("target") or config_target())
        # Phase 3a — the scan's FROZEN scope, resolved ONCE from the payload this save is about to
        # persist as `scan_runs.scope`. NOT the live global `active_scope(self)`: this same
        # `report["scope"]["scan_scope"]` is exactly what run_scan scored over (scanner threads
        # scope_from_json(scope["scan_scope"]) into _scoped_for_scoring), so the traces gated here
        # and the score cannot diverge — the load-bearing "same frozen scope for score and traces"
        # invariant. Resolved from the in-memory payload rather than get_scan_scope(sid) on purpose:
        # this is the MONOLITHIC path and the scan_runs row does not exist until the INSERT below,
        # and each cursor opens its own connection, so a read here would see nothing yet. Threaded
        # into `_rule_outcome` explicitly — `in_scope`'s storeless fallback cannot see any scope.
        scope = scope_from_json((report.get("scope") or {}).get("scan_scope"))
        import json as _json
        catalog = _CATALOG_JSON
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,started_at,completed_at,source,rubric_name,rubric_hash,"
                "files,certifiable,uncertain,error,avg_score,status,files_done,owner_email,scope) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'done',%s,%s,%s)",
                (sid, report["started_at"], report["completed_at"], report["source"],
                 report["rubric"]["name"], report["rubric"]["hash"],
                 s["files"], s["certifiable"], s["uncertain"], s["error"], s["avg_score"], s["files"],
                 report.get("owner"),
                 _json.dumps(report["scope"]) if report.get("scope") else None))
            for f in report["files"]:
                self._db.execute(cur,
                    "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id,acp_stamped,checksum,size_kb,pages,sheets,source_modified) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (sid, f["file"], f["engine"], f["status"], f["score"],
                     int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id"), f.get("acp_stamped"),
                     f.get("checksum"), f.get("size_kb"), f.get("pages"), f.get("sheets"), f.get("source_modified")))
                if f["issues"]:
                    self._db.executemany(cur,
                        "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity,detail,page,location) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(sid, f["file"], i["ruleId"], i["wcag"], i["severity"], i.get("detail"),
                          i.get("page"), _issue_location(i)) for i in f["issues"]])
                # Per-rule trace: one row per catalog rule per file — PASS/FAIL/REVIEW/NOT_EVALUATED.
                # Counts feed the per-rule trace, so they must reflect the conformance target:
                # an AAA finding picked up as a by-product of an AA check is not this scan's
                # business and must not drive an outcome.
                fail_counts, review_counts = _split_sc_counts(
                    filter_issues_to_target(f["issues"], target))
                fmt = _file_format(f["file"])
                trace_rows = []
                for rule in RULE_CATALOG:
                    rid = rule["id"]
                    fc, rc = fail_counts.get(rid, 0), review_counts.get(rid, 0)
                    outcome = _rule_outcome(rid, fmt, fc, rc, target, scope)
                    count = fc if fc else rc
                    trace_rows.append((sid, f["file"], rid, rule["name"], rule.get("plain"), rule["level"], rule["fix_mode"], outcome, count))
                self._db.executemany(cur,
                    "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(scan_id,file,rule_id) DO UPDATE SET outcome=EXCLUDED.outcome,finding_count=EXCLUDED.finding_count",
                    trace_rows)
                self._save_file_manifest(cur, sid, f, catalog)
                # Sensitive-data (PII) findings — masked samples only (ADR 0006).
                for pf in (f.get("pii") or {}).get("findings", []):
                    self._db.execute(cur,
                        "INSERT INTO pii_findings(scan_id,file,pii_type,label,count,severity,samples) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(scan_id,file,pii_type) DO UPDATE SET "
                        "count=EXCLUDED.count,severity=EXCLUDED.severity,samples=EXCLUDED.samples",
                        (sid, f["file"], pf["type"], pf["label"], pf["count"],
                         pf["severity"], _json.dumps(pf["samples"])))
                self._db.execute(cur, _UPSERT_INV,
                    (f["file"], report["completed_at"], report["completed_at"],
                     f["status"], f["score"]))
        # Document-centric layer (ADR 0003 Phase 1) for the MONOLITHIC path — the
        # fan-out path upserts per file in handlers._analyse_and_persist_one, but a
        # plain (non-queued / non-fanout) scan used to skip the documents table
        # entirely, leaving disposition/triage blind after a monolithic run.
        # Defensively wrapped like its fan-out twin: never fail the scan save.
        try:
            import datetime as _dt

            from documents import compute_triage_score, resolve_doc_id
            now = report["completed_at"]
            for f in report["files"]:
                doc_id = resolve_doc_id(report["source"], f.get("drive_file_id"),
                                        f["file"], f.get("checksum"))
                prior = self.get_document(doc_id)
                created_at = (prior or {}).get("created_at") or now
                age_days = ((_dt.datetime.fromisoformat(now) - _dt.datetime.fromisoformat(created_at)).days
                            if prior and prior.get("created_at") else None)
                tscore, rationale = compute_triage_score(
                    compliance_score=f.get("score"), pii_severity=(f.get("pii") or {}).get("severity"),
                    pii_total=(f.get("pii") or {}).get("total", 0), age_days=age_days,
                    skipped_rules=f.get("skipped_rules", 0))
                # owner AND owner_email from the same value, deliberately and temporarily:
                # report["owner"] is the tenant (it is what scan_runs.owner_email gets), so this
                # preserves today's behaviour exactly while giving the tenant its own column.
                # When `owner` is finally populated as ADR 0003 intends — a business owner —
                # only the first argument changes and isolation keeps working.
                self.upsert_document(doc_id, source=report["source"], path=f["file"],
                                     content_hash=f.get("checksum"), owner=report.get("owner"),
                                     owner_email=report.get("owner"),
                                     created_at=created_at, last_seen=now,
                                     triage_score=tscore, triage_rationale=rationale,
                                     classify=f.get("classify"), size_kb=f.get("size_kb"))
        except Exception:
            swallowed("store.save_scan: upserting the document row while saving the scan failed")
        # PRD Phase 3: this MONOLITHIC path (core._do_scheduled_scan, and routes/scans.py's
        # sync/thread branches when ACP_DEFER_ANALYSIS_TO_ASSESS=0) never wrote scan_inventory
        # before this — only ADR 0020's deferred discovery path did (handlers._scan_discover's
        # own `norm`/`inv` construction, which this mirrors over the same raw `_list()` items).
        # See latest_scan_inventory_items's docstring for what that silently broke: a delta-sync
        # reconstruction baseline read as a real (empty) prior scan rather than a missing one,
        # discarding almost the whole estate. Skipped, not just empty, when run_scan gave us
        # nothing to work with — a report built by hand (most tests) or an empty scan.
        # Defensively wrapped like the documents-table block above: never fail the scan save
        # over a secondary write.
        if _inventory_items:
            try:
                import classify as _cls
                inv_rows = [{"file": it["name"], "drive_file_id": it.get("id"),
                            "mime": it.get("source_mime"), "path": it.get("path"),
                            "checksum": it.get("checksum"),
                            "doc_class": _cls.classify_from_metadata(
                                it["name"], it.get("source_mime"))["doc_class"],
                            "created_at": it.get("created_at"),
                            "source_modified": it.get("source_modified"),
                            "owner": it.get("owner"), "parent_folder": it.get("parent_folder"),
                            "drive_id": it.get("driveId"),
                            "drive_account_id": it.get("drive_account_id"),
                            "size_kb": it.get("size_kb"),
                            "content_type": it.get("content_type")}
                           for it in _inventory_items]
                self.add_inventory(sid, inv_rows)
            except Exception:
                logger.warning("save_scan: failed to persist scan_inventory for %s", sid,
                               exc_info=True)
        return sid

    # ── Fan-out scan pipeline (ADR 0007) ──────────────────────────────────────
    def pre_create_queued_scan(self, scan_id: str, source: str, owner: str) -> None:
        """Create a minimal scan_runs row before the job is enqueued.

        Ensures GET /scans/{id} returns 200 from the moment the scan ID is issued to the
        client, closing the API-contract race where the caller holds an ID the server does
        not yet recognise. The worker's init_scan_run fills in the rubric, file count, real
        start time, and scope once it claims and begins the job."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,source,status,owner_email,started_at) "
                "VALUES(%s,%s,'queued',%s,%s) ON CONFLICT(id) DO NOTHING",
                (scan_id, source, owner, self._now()))

    def enqueue_scan(self, scan_id: str, source: str, owner: str,
                     job_type: str, payload: dict, *,
                     idempotency_key: str | None = None,
                     inputs: dict | None = None,
                     priority: int | None = None, max_attempts: int = 5,
                     run_after: str | None = None,
                     content_workspace_version_id: str | None = None) -> tuple[str, str]:
        """Create a scan_runs stub and its initial job in a single atomic transaction.

        Returns (scan_id, job_id). All rows are committed together; a failure at any point
        rolls back everything, leaving no orphan stubs. If idempotency_key is provided and a
        scan with that key already exists for the same owner, returns the original
        (scan_id, job_id) without inserting new rows.

        `inputs` is the immutable input snapshot (Stage 1 item 3). When provided it is
        inserted into scan_inputs in the same transaction. SECURITY: inputs must not contain
        access tokens, credentials, or secrets — callers are responsible for omitting them.

        `content_workspace_version_id` (ADR 0044): set for a workspace-sourced scan so the
        link is present from the very first (queued) row — never an orphan stub without it,
        the same guarantee this method already gives idempotency_key."""
        import json as _json
        now = self._now()
        job_id = uuid.uuid4().hex[:16]
        if priority is None:
            priority = job_priority(job_type)
        with self._db.cursor() as cur:
            if idempotency_key is not None:
                self._db.execute(cur,
                    "SELECT id FROM scan_runs WHERE owner_email=%s AND idempotency_key=%s",
                    (owner, idempotency_key))
                existing = self._db.fetchone(cur)
                if existing:
                    existing_scan_id = existing["id"]
                    self._db.execute(cur,
                        "SELECT id FROM jobs WHERE scan_id=%s ORDER BY created_at LIMIT 1",
                        (existing_scan_id,))
                    existing_job = self._db.fetchone(cur)
                    return existing_scan_id, (existing_job["id"] if existing_job else job_id)
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,source,status,owner_email,started_at,idempotency_key,"
                "content_workspace_version_id) "
                "VALUES(%s,%s,'queued',%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (scan_id, source, owner, now, idempotency_key, content_workspace_version_id))
            self._db.execute(cur,
                "INSERT INTO jobs(id,type,payload,status,priority,attempts,max_attempts,"
                "run_after,scan_id,created_at,updated_at) "
                "VALUES(%s,%s,%s,'queued',%s,0,%s,%s,%s,%s,%s)",
                (job_id, job_type, _json.dumps(payload or {}), priority, max_attempts,
                 run_after or now, scan_id, now, now))
            if inputs is not None:
                self._db.execute(cur,
                    "INSERT INTO scan_inputs(scan_id,source,folder_ids,exclude_folder_ids,"
                    "scan_options,actor,connection_ref,feature_flags,provider_config,"
                    "lifecycle_rules,app_version,captured_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id) DO NOTHING",
                    (scan_id,
                     inputs.get("source", source),
                     _json.dumps(inputs.get("folder_ids") or []),
                     _json.dumps(inputs.get("exclude_folder_ids") or []),
                     _json.dumps(inputs.get("scan_options") or {}),
                     inputs.get("actor", owner),
                     inputs.get("connection_ref"),
                     _json.dumps(inputs.get("feature_flags") or {}),
                     _json.dumps(inputs.get("provider_config") or []),
                     _json.dumps(inputs.get("lifecycle_rules") or []),
                     inputs.get("app_version"),
                     now))
        return scan_id, job_id

    def get_scan_inputs(self, scan_id: str) -> dict | None:
        """Return the immutable input snapshot for a scan, or None if none was captured."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM scan_inputs WHERE scan_id=%s", (scan_id,))
            row = self._db.fetchone(cur)
        if row is None:
            return None
        for field in ("folder_ids", "exclude_folder_ids", "scan_options",
                      "feature_flags", "provider_config", "lifecycle_rules"):
            if row.get(field) is not None:
                try:
                    row[field] = _json.loads(row[field])
                except (TypeError, ValueError):
                    pass
        return row

    def init_scan_run(self, scan_id: str, source: str, total: int, started_at: str,
                      rubric_name: str, rubric_hash: str, owner: str | None = None,
                      status: str = "running", scope: dict | None = None) -> None:
        """Create or update the scan_runs row at discover time (counter=0). `status` defaults
        to 'running' (analysis in flight); the deferred-analysis Discover phase (ADR 0020)
        passes 'discovered' — inventory listed, awaiting an explicit Assess.

        Uses DO UPDATE rather than DO NOTHING so a pre_create_queued_scan stub (status='queued',
        no rubric/scope) is promoted to a real running row when the worker claims the job.

        `scope` is what discovery covered (scanner._list scope_out). Written HERE, at discover,
        not at finalize: the count is on screen from the moment discovery ends, so its boundary
        has to be too — and a scan that dies before finalize is exactly when "what did this even
        look at?" is the question being asked."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,started_at,source,rubric_name,rubric_hash,files,files_done,status,owner_email,scope) "
                "VALUES(%s,%s,%s,%s,%s,%s,0,%s,%s,%s) "
                "ON CONFLICT(id) DO UPDATE SET "
                "  started_at=EXCLUDED.started_at, rubric_name=EXCLUDED.rubric_name, "
                "  rubric_hash=EXCLUDED.rubric_hash, files=EXCLUDED.files, "
                "  status=EXCLUDED.status, scope=EXCLUDED.scope "
                # Same resurrection guard as finalize_scan_run, at the other end of the run: a
                # worker claiming a job whose scan was superseded or cancelled while it sat in the
                # queue must not promote that scan back to 'running'/'discovered'. The retry case
                # this DO UPDATE exists for (a re-attempt of the SAME job resetting status — see
                # handlers.py's 'between-attempts marker' comment) is unaffected: those rows are
                # 'failed' or 'queued', never one of these two terminal values.
                "WHERE scan_runs.status NOT IN ('superseded','cancelled')",
                (scan_id, started_at, source, rubric_name, rubric_hash, total, status, owner,
                 _json.dumps(scope) if scope else None))

    def set_scan_status(self, scan_id: str, status: str) -> None:
        """Move a scan between phases — e.g. 'discovered' → 'running' when Assess begins.

        When transitioning TO 'discovered', stamps discovered_at atomically so no code path
        can leave the scan in a discovered-without-timestamp state. The stamp is set-once
        (COALESCE guards against overwriting an already-set value), so a re-delivered job
        or a second call from _mark_discovered later is harmless.
        """
        with self._db.cursor() as cur:
            if status == "discovered":
                self._db.execute(cur,
                    "UPDATE scan_runs SET status=%s, discovered_at=COALESCE(discovered_at, %s) "
                    "WHERE id=%s",
                    (status, self._now(), scan_id))
            else:
                self._db.execute(cur, "UPDATE scan_runs SET status=%s WHERE id=%s", (status, scan_id))

    def set_scan_files(self, scan_id: str, files: int) -> None:
        """Re-point a run's `files` total at the population THIS phase actually enqueued.

        `files` is written once at init_scan_run, from the DISCOVERED count, because at discover
        time that is the only population there is. Assess then narrows it — dropping every
        non-assessable inventory row, and by default every row a lifecycle rule flagged for
        archive/deletion — and enqueues only the remainder. Left alone, `files` still describes
        the wider population while `files_done` counts the narrower one, so `files - files_done`
        silently reports deliberately-excluded files as "not started". The frontend reads exactly
        that difference to decide a run is PARTIALLY COMPLETE, which made the most likely cause of
        a "partially completed" screen a lifecycle rule doing its job.

        ASSIGNMENT, NEVER ACCUMULATION. A second assess over the same scan re-enters this path;
        `files` must then describe that run's population, not the sum of both. `SET files=%s` is
        an assignment, so a re-assess that enqueues fewer files reports fewer — which is what
        makes the number mean "selected for THIS assess" rather than "ever selected".

        Deliberately NOT folded into init_scan_run: discover's own count is correct for discover,
        and a run that is discovered but never assessed must keep it.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE scan_runs SET files=%s WHERE id=%s", (files, scan_id))

    def checkpoint_scan_progress(self, scan_id: str, state: dict, at: str) -> None:
        """Durable, sparse snapshot of live Discover progress — see live_checkpoint's schema
        comment for why this exists. Caller (core.update_job) owns the throttling; this is a
        plain UPDATE, cheap enough to call from a worker thread without its own connection-pool
        concerns. Silently no-ops on an unknown scan_id (the row may not exist yet, or may have
        been deleted) rather than raising — a checkpoint write must never fail the scan it is
        merely describing."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET live_checkpoint=%s, live_checkpoint_at=%s WHERE id=%s",
                (_json.dumps(state), at, scan_id))

    def add_inventory(self, scan_id: str, items: list[dict]) -> dict:
        """Persist the Discover-phase inventory (ADR 0020 / lifecycle PRD) — source metadata
        only, no file opened. Idempotent per (scan_id, file) so a re-listed discover doesn't
        duplicate. `lifecycle_status` is deliberately NOT written here: it defaults to 'Active'
        on first insert (column DEFAULT) and is owned by the rule evaluator / manual actions, so
        a re-list must not reset a status already assigned this run.

        Returns {"new": N, "updated": M, "unchanged": 0, "failed": P}.  "new" is the count of
        rows that did not exist before this call; "updated" is the count of rows that already
        existed (ON CONFLICT DO UPDATE ran); "unchanged" is always 0 because the upsert pattern
        cannot distinguish an update that changed values from one that did not without a
        per-column comparison; "failed" counts items where the INSERT raised an exception.

        BATCHED, with a per-item fallback. A real estate is thousands of rows, not the handful in
        a test fixture, and one execute() per row is thousands of separate network round-trips to
        Postgres — the dominant cost of a Discover run in production, found live 2026-08-27 when a
        6,922-file scan sat "still running" for 20+ minutes past the point its listing had already
        completed twice. executemany (execute_batch on Postgres) sends the whole set in one round
        trip in the overwhelmingly common all-succeed case. If the batch itself raises — a
        genuinely malformed row, not the common case — fall back to the original per-item loop so
        one bad row still can't cost the other thousands their fault isolation; this is the same
        fail-quiet contract _mark_discovered documents for the stamp that runs right after this."""
        if not items:
            return {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
        now = self._now()
        sql = ("INSERT INTO scan_inventory(scan_id,file,drive_file_id,mime,size_kb,doc_class,"
               "checksum,path,created_at,source_modified,owner,parent_folder,discovered_at,drive_id,"
               "content_type,drive_account_id,site_id,library_name) "
               "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT(scan_id,file) DO UPDATE SET "
               "drive_file_id=EXCLUDED.drive_file_id, mime=EXCLUDED.mime, size_kb=EXCLUDED.size_kb, "
               "doc_class=EXCLUDED.doc_class, checksum=EXCLUDED.checksum, path=EXCLUDED.path, "
               "created_at=EXCLUDED.created_at, source_modified=EXCLUDED.source_modified, "
               "owner=EXCLUDED.owner, parent_folder=EXCLUDED.parent_folder, drive_id=EXCLUDED.drive_id, "
               # COALESCE, not overwrite: a re-list that got no content type this time (a
               # transient enrichment failure) must not blank out one recorded on a PRIOR
               # list of the same file — that would be a real answer thrown away for a gap.
               "content_type=COALESCE(EXCLUDED.content_type, scan_inventory.content_type), "
               "drive_account_id=EXCLUDED.drive_account_id, "
               # COALESCE for the same reason content_type uses it: a re-list of the same file
               # through a narrower path (a folder scan of one library, a delta reconstruction)
               # may not know the site, and a gap must not erase a site id an earlier list of the
               # same row recorded.
               "site_id=COALESCE(EXCLUDED.site_id, scan_inventory.site_id), "
               "library_name=COALESCE(EXCLUDED.library_name, scan_inventory.library_name)")

        def _params(it: dict) -> tuple:
            return (scan_id, it.get("file"), it.get("drive_file_id"), it.get("mime"),
                    it.get("size_kb"), it.get("doc_class"), it.get("checksum"), it.get("path"),
                    it.get("created_at"), it.get("source_modified"), it.get("owner"),
                    it.get("parent_folder"), it.get("discovered_at") or now, it.get("drive_id"),
                    it.get("content_type"), it.get("drive_account_id"),
                    it.get("site_id"), it.get("library_name"))

        failed = 0
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COUNT(*) AS cnt FROM scan_inventory WHERE scan_id=%s", (scan_id,))
            before = (self._db.fetchone(cur) or {}).get("cnt", 0)
            try:
                self._db.executemany(cur, sql, [_params(it) for it in items])
            except Exception:
                logger.warning("add_inventory: batch insert failed for scan %s (%d items), "
                               "falling back to per-item", scan_id, len(items), exc_info=True)
                for it in items:
                    try:
                        self._db.execute(cur, sql, _params(it))
                    except Exception:
                        failed += 1
            self._db.execute(cur,
                "SELECT COUNT(*) AS cnt FROM scan_inventory WHERE scan_id=%s", (scan_id,))
            after = (self._db.fetchone(cur) or {}).get("cnt", 0)
        new_count = max(0, after - before)
        updated_count = max(0, len(items) - failed - new_count)
        return {"new": new_count, "updated": updated_count, "unchanged": 0, "failed": failed}

    def mark_discovery_complete(self, scan_id: str, at: str | None = None) -> str | None:
        """Stamp WHEN this run's discovery finished — the instant its inventory describes.

        SET ONCE. A re-delivered discover job, or a re-list of the same scan, must not move the
        snapshot instant forward: `add_inventory` deliberately preserves each row's original
        `discovered_at` through its ON CONFLICT, and a run-level stamp that drifted while the
        per-file stamps did not would make the two disagree about the same event. The write is
        therefore guarded on the column still being NULL, in one statement, so two workers racing
        the same scan cannot both win.

        Returns the value now stored (the existing one when it was already set), or None if the
        run does not exist — so a caller can log what it actually recorded rather than what it
        offered.

        This is NOT `completed_at`. That is the whole scan finishing, which under ADR 0020 is the
        end of ASSESS and may be days later or never. Discovery is its own phase and gets its own
        timestamp; see the migration comment for why neither existing column could answer.
        """
        at = at or self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET discovered_at=%s WHERE id=%s AND discovered_at IS NULL",
                (at, scan_id))
            self._db.execute(cur, "SELECT discovered_at FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
        return (row or {}).get("discovered_at")

    def acquire_discovery_guard(self, owner_email: str, source: str, scan_id: str) -> str | None:
        """Claim the active-Discovery slot for (owner_email, source).

        Returns None on success. Returns the scan_id that currently holds the slot when
        another scan is GENUINELY still active — callers must treat that as a conflict and
        stop rather than starting a second Discovery over the same source.

        Written in a single INSERT … ON CONFLICT DO NOTHING, then a SELECT, so the check
        and the claim are one round-trip and two concurrent requests cannot both see "no
        holder" and both succeed. The conflict case reads the existing row and returns its
        scan_id; the caller decides what to do (typically raise a 409-style error).

        STALE-HOLDER RECLAIM. release_discovery_guard is meant to fire in the same
        transaction as the terminal scan-status write, but nothing enforces that pairing —
        a worker that dies before either write runs (OOM kill, hard process termination,
        an exception path that predates this guard and never learned to release it) leaves
        the row claimed forever. Found live: a stale row from one crashed run blocked every
        subsequent scan attempt for that (owner, source) indefinitely, each rejected as
        "Discovery already active" — indistinguishable, on the surface, from a genuinely
        busy source. Two independent staleness signals, either is enough to reclaim:
          1. The holder's OWN scan_runs row already reads a terminal status (release simply
             never ran for it — the crash case above, or any other path with the same gap).
          2. The holder has been claimed for longer than any real Discovery run takes
             (ACP_DISCOVERY_GUARD_STALE_S, default 2h) — covers a crash so abrupt scan_runs
             itself was never updated either.
        Reclaiming deletes the stale row and retries the claim ONCE — a second genuine
        conflict (a fresh, real holder that raced in between) is returned normally rather
        than looped on.
        """
        import os as _os
        at = self._now()

        def _try_claim() -> str | None:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "INSERT INTO active_discovery_guard(owner_email, source, scan_id, acquired_at) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT(owner_email, source) DO NOTHING",
                    (owner_email, source, scan_id, at))
                self._db.execute(cur,
                    "SELECT scan_id, acquired_at FROM active_discovery_guard "
                    "WHERE owner_email=%s AND source=%s", (owner_email, source))
                return self._db.fetchone(cur)

        row = _try_claim()
        holder = (row or {}).get("scan_id")
        if holder is None or holder == scan_id:
            return None

        stale = False
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT status, discovered_at FROM scan_runs WHERE id=%s", (holder,))
            holder_row = self._db.fetchone(cur)
        holder_status = (holder_row or {}).get("status")
        holder_discovered_at = (holder_row or {}).get("discovered_at")
        # 'paused' (ADR 0038) counts as genuinely live here, same as 'queued'/'running' — a
        # paused run has, by design, no active workers, and without this a resume would find its
        # own discovery slot already reclaimed by a second scan that started while it waited.
        # Found by inspection while implementing pause/resume: this staleness check predates the
        # ADR and reads any non-queued/non-running status as abandoned, which is correct for
        # every terminal status but was never updated for the one live status pause introduces.
        # Assess moves this same run row back to status='running'. The stage-specific timestamp
        # is therefore the authoritative signal that Discovery no longer owns this slot.
        if holder_discovered_at:
            stale = True
        elif holder_status and holder_status not in ("queued", "running", "paused"):
            stale = True
        else:
            try:
                from datetime import datetime, timezone
                ceiling_s = int(_os.environ.get("ACP_DISCOVERY_GUARD_STALE_S", "7200") or "7200")
                acquired = datetime.fromisoformat((row or {}).get("acquired_at").replace("Z", "+00:00"))
                if acquired.tzinfo is None:
                    acquired = acquired.replace(tzinfo=timezone.utc)
                age_s = (datetime.now(timezone.utc) - acquired).total_seconds()
                if age_s > ceiling_s:
                    stale = True
            except Exception:
                # an unparseable timestamp must never crash a scan start — treat as live
                swallowed("store.acquire_discovery_guard: reading the discovery guard's acquired_at "
                          "failed", scan_id)

        if not stale:
            return holder

        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM active_discovery_guard WHERE owner_email=%s AND source=%s "
                "AND scan_id=%s", (owner_email, source, holder))
        row = _try_claim()
        holder = (row or {}).get("scan_id")
        return None if holder == scan_id else holder

    def release_discovery_guard(self, scan_id: str) -> bool:
        """Release the active-Discovery slot held by this scan_id.

        Should be called in the same transaction that sets the terminal scan status — so
        a crash between the status write and the release cannot leave the guard permanently
        claimed. Returns True if a row was deleted, False if nothing was held (idempotent).

        Never call from an API handler or the browser — only the durable finalizer
        (scan_finalize job) and the cancellation finalizer should call this.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM active_discovery_guard WHERE scan_id=%s", (scan_id,))
            deleted = cur.rowcount if hasattr(cur, "rowcount") else 1
        return bool(deleted)

    def mark_published(self, scan_id: str, at: str | None = None) -> str | None:
        """Stamp the scan as published — i.e. its inventory passed all completeness checks.

        SET ONCE, same contract as mark_discovery_complete. A scan that is already published
        keeps its original stamp; a re-delivery of the same scan_finalize job cannot move it
        forward. Returns the value now stored, or None if the run does not exist.

        Only call this when:
        - enumeration was complete (not truncated)
        - suspicious-zero check passed (0-file result was not preceded by a non-empty scan)
        A scan without published_at is surfaced to the frontend as "staging" and does not
        replace the previous published snapshot in scan selection.
        """
        at = at or self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET published_at=%s WHERE id=%s AND published_at IS NULL",
                (at, scan_id))
            if cur.rowcount > 0:
                self._bump_scan_revision(cur, scan_id)
            self._db.execute(cur, "SELECT published_at FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
        return (row or {}).get("published_at")

    def get_discovery_completed_at(self, scan_id: str) -> str | None:
        """The instant this run's inventory describes, falling back for runs discovered before
        the column existed.

        The fallback is the NEWEST `scan_inventory.discovered_at`. That is real persisted data —
        written per file by `add_inventory` at the moment the batch landed, and never overwritten
        by a re-list — so its maximum is when the inventory was last added to. Derived, not
        invented: nothing here reads a clock.

        None means nobody recorded it. A caller must render that as unknown; it is not evidence
        that the scan is recent.

        MAX over TEXT is a lexical maximum, which is the instant maximum only while the values
        share a format. They do: every row `add_inventory` writes without an explicit stamp gets
        `_now()`, a UTC `datetime.isoformat()`, and the discover path never supplies one. Said out
        loud because a connector that ever started carrying its own offset-bearing stamp would
        break the ordering quietly — the frontend compares parsed instants for that reason.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT discovered_at FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
            if row and row.get("discovered_at"):
                return row["discovered_at"]
            self._db.execute(cur,
                "SELECT MAX(discovered_at) AS at FROM scan_inventory WHERE scan_id=%s", (scan_id,))
            return (self._db.fetchone(cur) or {}).get("at")

    _INV_COLS = ("scan_id,file,drive_file_id,mime,size_kb,doc_class,checksum,path,"
                 "created_at,source_modified,owner,parent_folder,discovered_at,drive_id,"
                 "lifecycle_status,lifecycle_rule_id,lifecycle_reason,exclusion_reason,"
                 "lifecycle_override_reason,lifecycle_overridden_by,lifecycle_overridden_at,"
                 "content_type")

    def list_inventory(self, scan_id: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT {self._INV_COLS} "
                "FROM scan_inventory WHERE scan_id=%s ORDER BY file", (scan_id,))
            return self._db.fetchall(cur)

    def count_inventory(self, scan_id: str) -> int:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT COUNT(*) AS n FROM scan_inventory WHERE scan_id=%s", (scan_id,))
            row = self._db.fetchone(cur)
            n = (row or {}).get("n", 0) or 0
            if n == 0:
                # Pre-ADR-0020 scans stored files in file_records, not scan_inventory.
                self._db.execute(cur, "SELECT COUNT(*) AS n FROM file_records WHERE scan_id=%s", (scan_id,))
                row = self._db.fetchone(cur)
                n = (row or {}).get("n", 0) or 0
        return n

    def list_inventory_page(self, scan_id: str, *, limit: int, offset: int = 0) -> list[dict]:
        """One page of the per-file discover inventory, ORDER BY file (stable paging). The
        whole-estate list/export API runs off this + count_inventory so a 30k-file estate is paged
        from the DB, never pulled whole into memory."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT {self._INV_COLS} FROM scan_inventory WHERE scan_id=%s "
                "ORDER BY file LIMIT %s OFFSET %s", (scan_id, int(limit), int(offset)))
            return self._db.fetchall(cur)

    def latest_scan_inventory_items(self, owner: str, source: str) -> list[dict] | None:
        """The full scan_inventory of the most recent COMPLETED scan for (owner, source) that
        actually HAS scan_inventory rows — PRD Phase 3's reconstruction seam:
        scanner.apply_drive_delta / apply_sp_delta rebuild 'the current known estate' from these
        rows plus a Changes API / Graph delta, without a fresh listing. None when there is no
        such prior scan to reconstruct from (the first-ever incremental sweep, or every
        candidate scan_run has no usable inventory) — the caller falls back to a full listing in
        that case, same as core._drive_sync_plan already does for a missing cursor.

        The EXISTS clause is load-bearing, not an optimization: a scan_runs row with
        completed_at set does NOT guarantee scan_inventory rows exist for it. The monolithic
        scan path (core._do_scheduled_scan, and routes/scans.py's sync/thread branches when
        ACP_DEFER_ANALYSIS_TO_ASSESS=0) persists to file_records via save_scan, which — before
        this — never wrote scan_inventory at all. Without this clause, the plain 'most recent
        completed scan' query would return such a scan_run's id, and the second query below
        would then return `[]` (a REAL empty list, not None) — which every caller here
        distinguishes from 'no prior scan' and would happily use as a real, if empty, baseline.
        Found live: this silently discarded almost the whole reconstructed estate on the very
        first scheduled sweep to run after a prior one had populated no inventory — a
        near-total, silent undercount, not a crash. Skipping inventory-less scan_runs here means
        an OLDER scan that did leave usable rows is used instead when one exists, rather than
        treating a real prior estate as unusable just because the newest run of it produced no
        inventory. save_scan now also writes scan_inventory (see there), so this should be a
        non-issue going forward; the guard stays as defense against any scan_runs row already in
        a database from before that change, and against paths that reach save_scan without it.

        `drive_id` is the Graph DRIVE a SharePoint/OneDrive row was listed from (see
        scanner._inv_row) — None for Drive (which has no such concept) and for a OneDrive row
        (legitimately no drive to name; scanner._sp_base reads that as /me/drive). Selected
        alongside the rest so scanner._sp_file_from_inventory_row's reconstruction can restamp
        it, matching apply_sp_delta's (drive_id, item_id) identity — a Graph item id is unique
        only within its drive.

        `drive_account_id` is Drive's OWN sibling identity concept — the Google account a Drive
        row's listing ran as (scanner.drive_account_id) — None for non-Drive rows. Selected so
        core._drive_prior_inventory_for_account can verify a Drive baseline was scanned as the
        same account before trusting it, the Drive mirror of drive_id's role above for
        core._sp_prior_inventory_for_drive.

        `content_type` is SharePoint's per-item Content Type (scanner._sp_enrich_content_types).
        Selected because a delta-sync reconstruction otherwise LOSES it on every carried-forward
        file: the column is real and `add_inventory` populates it, but this SELECT never listed
        it, so the reconstruction baseline arrived with the field absent and each unchanged file
        was re-inventoried as having none. Recovering it live is the one thing delta sync exists
        not to do — `_sp_enrich_content_types` is a per-item Graph call, and paying it for every
        carried-forward file would spend exactly the cost this whole feature saves. Carrying the
        stored value forward costs nothing and is correct: an UNCHANGED file's content type is
        still its content type. Files the delta reports as changed are replaced wholly by their
        fresh raw item (apply_sp_delta) and so legitimately have none this scan, exactly as
        before. Tracked as a known gap in docs/TODO.md P1e; this is that fix.

        Rows with no drive_file_id are dropped (a local/non-Drive row, or one from a scan old
        enough to predate that column) — they carry nothing a delta could ever reconcile
        against."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT sr.id FROM scan_runs sr WHERE sr.owner_email=%s AND sr.source=%s "
                "AND sr.completed_at IS NOT NULL AND EXISTS ("
                "  SELECT 1 FROM scan_inventory si "
                "  WHERE si.scan_id = sr.id AND si.drive_file_id IS NOT NULL"
                ") ORDER BY sr.completed_at DESC LIMIT 1",
                (owner, source))
            row = self._db.fetchone(cur)
            if not row:
                return None
            self._db.execute(cur,
                "SELECT file, drive_file_id, mime, size_kb, checksum, created_at, "
                "source_modified, owner, parent_folder, drive_id, drive_account_id, "
                "content_type "
                "FROM scan_inventory WHERE scan_id=%s",
                (row["id"],))
            return [r for r in self._db.fetchall(cur) if r.get("drive_file_id")]

    # ── Lifecycle status (Discover-completeness PRD §4.3 / §4.5) ─────────────────
    # The 7 statuses a discovered file can hold. Active is the default; a rule run or a manual
    # action moves it. Kept here (not an enum type) so the sqlite/postgres split needs no DDL.
    LIFECYCLE_STATUSES = ("Active", "Already archived", "Archive Candidate", "Archived",
                          "Delete Candidate", "Deleted", "Failed", "Exempted", "Reactivated",
                          "Unevaluable", "Conflict — review required")
    # Statuses Assess excludes by default (PRD §4.5): archive/delete-flagged and terminal.
    LIFECYCLE_EXCLUDED_DEFAULT = ("Archive Candidate", "Archived", "Delete Candidate", "Deleted")

    def set_lifecycle_status(self, scan_id: str, file: str, status: str, *,
                             rule_id: str | None = None, reason: str | None = None,
                             exclusion_reason: str | None = None) -> None:
        """Move one inventory row to `status`, recording the rule + reason that produced it
        (PRD §4.3). Unknown statuses raise — the set is closed. Idempotent."""
        if status not in self.LIFECYCLE_STATUSES:
            raise ValueError(f"unknown lifecycle status {status!r} "
                             f"(allowed: {list(self.LIFECYCLE_STATUSES)})")
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_inventory SET lifecycle_status=%s, lifecycle_rule_id=%s, "
                "lifecycle_reason=%s, exclusion_reason=%s WHERE scan_id=%s AND file=%s",
                (status, rule_id, reason, exclusion_reason, scan_id, file))

    def bulk_set_lifecycle_status(self, rows: list) -> None:
        """Bulk-update lifecycle status for rows accumulated by the lifecycle rule evaluator.
        rows: list of (scan_id, file, status, rule_id, reason). Unknown statuses raise."""
        if not rows:
            return
        for _, _, status, _, _ in rows:
            if status not in self.LIFECYCLE_STATUSES:
                raise ValueError(f"unknown lifecycle status {status!r} "
                                 f"(allowed: {list(self.LIFECYCLE_STATUSES)})")
        with self._db.cursor() as cur:
            self._db.executemany(cur,
                "UPDATE scan_inventory SET lifecycle_status=%s, lifecycle_rule_id=%s, "
                "lifecycle_reason=%s, exclusion_reason=%s WHERE scan_id=%s AND file=%s",
                [(status, rule_id, reason, None, scan_id, file)
                 for scan_id, file, status, rule_id, reason in rows])

    def get_lifecycle_status(self, scan_id: str, file: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT lifecycle_status,lifecycle_rule_id,lifecycle_reason,exclusion_reason,"
                "lifecycle_override_reason,lifecycle_overridden_by,lifecycle_overridden_at "
                "FROM scan_inventory WHERE scan_id=%s AND file=%s", (scan_id, file))
            return self._db.fetchone(cur)

    def override_lifecycle(self, scan_id: str, file: str, *, reason: str, actor: str) -> dict | None:
        """Record a human's reasoned disagreement with a rule's Archive/Delete Candidate
        recommendation for one file (lifecycle rules #8). Deliberately does NOT touch
        lifecycle_status/lifecycle_rule_id/lifecycle_reason — those stay the rule's own record;
        an override is itself only a recommendation ("keep this despite the rule"), so the
        reconciliation in DiscoveryResults stays a true partition of what the rule pass produced.

        Returns the row's {lifecycle_status, lifecycle_rule_id} as they stood BEFORE this call
        (the caller needs lifecycle_rule_id to attribute the audit entry to the rule being
        overridden), or None when the row does not exist or does not currently carry a candidate
        status — there is nothing to override on a file no rule flagged."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT lifecycle_status,lifecycle_rule_id FROM scan_inventory "
                "WHERE scan_id=%s AND file=%s", (scan_id, file))
            prior = self._db.fetchone(cur)
            if not prior or (prior.get("lifecycle_status") or "") not in (
                    "Archive Candidate", "Delete Candidate"):
                return None
            self._db.execute(cur,
                "UPDATE scan_inventory SET lifecycle_override_reason=%s, "
                "lifecycle_overridden_by=%s, lifecycle_overridden_at=%s "
                "WHERE scan_id=%s AND file=%s",
                (reason, actor, self._now(), scan_id, file))
        return prior

    def count_lifecycle_by_status(self, scan_id: str) -> dict:
        """{status: count} across the scan's inventory — the reconciliation Reports need
        (PRD §4.3/AC-14: discovered → active/archived/deletion-flagged/deleted/failed/exempted).
        Rows predating the lifecycle columns read NULL; report those as 'Active'."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COALESCE(lifecycle_status,'Active') AS s, COUNT(*) AS n "
                "FROM scan_inventory WHERE scan_id=%s GROUP BY COALESCE(lifecycle_status,'Active')",
                (scan_id,))
            return {r["s"]: r["n"] for r in self._db.fetchall(cur)}

    def bulk_create_lifecycle_evaluations(self, rows: list[tuple]) -> None:
        """Persist immutable rule/file evidence snapshots. A deterministic evaluation id makes
        retries idempotent; an existing snapshot is never rewritten by a later rule edit."""
        if not rows:
            return
        with self._db.cursor() as cur:
            self._db.executemany(cur,
                "INSERT INTO lifecycle_evaluation(evaluation_id,scan_id,document_id,policy_id,"
                "policy_version,result,evidence_json,proposed_action,priority,evaluated_at,owner_email) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(evaluation_id) DO NOTHING", rows)

    def bulk_upsert_effective_dispositions(self, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._db.cursor() as cur:
            self._db.executemany(cur,
                "INSERT INTO effective_disposition(document_id,scan_id,winning_evaluation_id,"
                "lifecycle_status,precedence_reason,approval_status,override_reason,updated_at,owner_email) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,document_id) DO UPDATE SET "
                "winning_evaluation_id=EXCLUDED.winning_evaluation_id,lifecycle_status=EXCLUDED.lifecycle_status,"
                "precedence_reason=EXCLUDED.precedence_reason,approval_status=EXCLUDED.approval_status,"
                "override_reason=EXCLUDED.override_reason,updated_at=EXCLUDED.updated_at,owner_email=EXCLUDED.owner_email",
                rows)

    def lifecycle_summary(self, scan_id: str, owner: str) -> dict:
        counts = self.count_lifecycle_by_status(scan_id)
        total = self.count_inventory(scan_id)
        normalized = {
            "active": counts.get("Active", 0),
            "already_archived": counts.get("Already archived", 0) + counts.get("Archived", 0),
            "archive_candidate": counts.get("Archive Candidate", 0),
            "delete_candidate": counts.get("Delete Candidate", 0),
            "deleted": counts.get("Deleted", 0),
            "exempt": counts.get("Exempted", 0),
            "reactivated": counts.get("Reactivated", 0),
            "unevaluable": counts.get("Unevaluable", 0) + counts.get("Conflict — review required", 0),
            "failed": counts.get("Failed", 0),
        }
        candidate_count = normalized["archive_candidate"] + normalized["delete_candidate"]
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COUNT(*) AS evaluations,COUNT(DISTINCT document_id) AS evaluated_files,"
                "COUNT(DISTINCT policy_id) AS recorded_rules FROM lifecycle_evaluation "
                "WHERE scan_id=%s AND owner_email=%s", (scan_id, owner))
            evidence = self._db.fetchone(cur) or {}
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM scan_inventory si WHERE si.scan_id=%s "
                "AND si.lifecycle_status IN ('Archive Candidate','Delete Candidate') "
                "AND EXISTS (SELECT 1 FROM lifecycle_evaluation le WHERE le.scan_id=si.scan_id "
                "AND le.document_id=si.file AND le.policy_id=si.lifecycle_rule_id "
                "AND le.owner_email=%s AND le.result IN ('matched','conflict'))", (scan_id, owner))
            candidate_evidence = int((self._db.fetchone(cur) or {}).get("n") or 0)
            self._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s AND owner_email=%s",
                             (scan_id, owner))
            run = self._db.fetchone(cur) or {}
        scope = run.get("scope") or {}
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except Exception:
                scope = {}
        expected_rules = int(scope.get("lifecycle_rules_enabled") or 0)
        recorded_rules = int(evidence.get("recorded_rules") or 0)
        evidence_complete = (candidate_count == candidate_evidence and
                             (expected_rules == 0 or recorded_rules >= expected_rules))
        return {"scan_id": scan_id, "total": total, "reconciled_total": sum(normalized.values()),
                "counts": normalized,
                "assessment_excluded": normalized["already_archived"] + normalized["archive_candidate"] + normalized["delete_candidate"] + normalized["deleted"],
                "data_version": self.lifecycle_data_version(scan_id),
                "recommendations_only": True,
                "integrity": {"evidence_complete": evidence_complete,
                              "expected_rules": expected_rules,
                              "recorded_rules": recorded_rules,
                              "evaluations": int(evidence.get("evaluations") or 0),
                              "evaluated_files": int(evidence.get("evaluated_files") or 0),
                              "candidate_count": candidate_count,
                              "candidates_with_evidence": candidate_evidence}}

    def lifecycle_data_version(self, scan_id: str) -> str | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT MAX(evaluated_at) AS v FROM lifecycle_evaluation WHERE scan_id=%s", (scan_id,))
            row = self._db.fetchone(cur)
            return row.get("v") if row else None

    def list_lifecycle_rule_results(self, scan_id: str, owner: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT le.policy_id,le.policy_version,COALESCE(dp.name,le.policy_id) AS name,"
                "le.priority,le.proposed_action,MAX(le.evaluated_at) AS evaluated_at,COUNT(*) AS evaluated,"
                "SUM(CASE WHEN le.result='matched' THEN 1 ELSE 0 END) AS matched,"
                "SUM(CASE WHEN le.result IN ('skipped','exempt') THEN 1 ELSE 0 END) AS skipped,"
                "SUM(CASE WHEN le.result='unevaluable' THEN 1 ELSE 0 END) AS unevaluable,"
                "SUM(CASE WHEN le.result='conflict' THEN 1 ELSE 0 END) AS conflicts "
                "FROM lifecycle_evaluation le LEFT JOIN disposition_policy dp ON dp.policy_id=le.policy_id "
                "WHERE le.scan_id=%s AND le.owner_email=%s GROUP BY le.policy_id,le.policy_version,dp.name,le.priority,le.proposed_action "
                "ORDER BY le.priority, name", (scan_id, owner))
            return self._db.fetchall(cur)

    def list_lifecycle_files(self, scan_id: str, owner: str, *, status: str | None = None,
                             policy_id: str | None = None, candidate_only: bool = False,
                             limit: int = 200, offset: int = 0) -> list[dict]:
        where, args = ["si.scan_id=%s", "EXISTS (SELECT 1 FROM scan_runs sr WHERE sr.id=si.scan_id AND sr.owner_email=%s)"], [scan_id, owner]
        if status == "already_archived":
            where.append("COALESCE(si.lifecycle_status,'Active') IN ('Already archived','Archived')")
        elif status == "unevaluable":
            where.append("COALESCE(si.lifecycle_status,'Active') IN ('Unevaluable','Conflict — review required')")
        elif status:
            where.append("COALESCE(si.lifecycle_status,'Active')=%s"); args.append(status)
        if candidate_only:
            where.append("si.lifecycle_status IN ('Archive Candidate','Delete Candidate')")
        if policy_id:
            where.append("si.lifecycle_rule_id=%s"); args.append(policy_id)
        args.extend([limit, offset])
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT {self._INV_COLS} FROM scan_inventory si WHERE {' AND '.join(where)} ORDER BY si.file LIMIT %s OFFSET %s",
                tuple(args))
            return self._db.fetchall(cur)

    def lifecycle_history(self, file: str, owner: str, limit: int = 300) -> list[dict]:
        """Everything recorded about one document's lifecycle, across EVERY scan (PRD §7.4).

        The right-hand review panel is specified to show "prior scans, recommendations,
        overrides, approvals, and source actions", and each of those lives in a different table:
        lifecycle_evaluation holds what a rule decided and why, scan_inventory holds a reviewer's
        override, disposition_audit holds the approval and its execution, and decision_log holds
        everything either of those chose to narrate. This is four queries and stays four however
        long the history is - the count is bounded by the number of SOURCES, not by events.

        Keyed on `file` rather than on a doc id ON PURPOSE. The whole value of a timeline here is
        that it crosses scans - "this was recommended in August, kept, then recommended again" -
        and the lifecycle doc id embeds the scan (`scan:{scan_id}:{file}`), so keying on one
        would return a single scan's worth of events and quietly look like the whole history.
        Every source is owner-scoped independently; none of them infers ownership from another.
        """
        events: list[dict] = []
        suffix = ":" + file
        with self._db.cursor() as cur:
            # 1. What each rule decided, in each scan.
            self._db.execute(cur,
                "SELECT scan_id,policy_id,policy_version,result,proposed_action,evaluated_at "
                "FROM lifecycle_evaluation WHERE document_id=%s AND owner_email=%s "
                "ORDER BY evaluated_at", (file, owner))
            for row in self._db.fetchall(cur):
                events.append({
                    "ts": row.get("evaluated_at"), "kind": "evaluated",
                    "scan_id": row.get("scan_id"), "policy_id": row.get("policy_id"),
                    "policy_version": row.get("policy_version"), "result": row.get("result"),
                    "action": row.get("proposed_action"), "actor": None,
                    "detail": f"{row.get('policy_id')} v{row.get('policy_version')} "
                              f"{row.get('result')}",
                })

            # 2. A reviewer's recorded disagreement, per scan.
            self._db.execute(cur,
                "SELECT scan_id,lifecycle_override_reason,lifecycle_overridden_by,"
                "lifecycle_overridden_at FROM scan_inventory si WHERE file=%s "
                "AND lifecycle_overridden_at IS NOT NULL AND EXISTS "
                "(SELECT 1 FROM scan_runs sr WHERE sr.id=si.scan_id AND sr.owner_email=%s)",
                (file, owner))
            for row in self._db.fetchall(cur):
                events.append({
                    "ts": row.get("lifecycle_overridden_at"), "kind": "override",
                    "scan_id": row.get("scan_id"), "policy_id": None, "policy_version": None,
                    "result": "kept", "action": None,
                    "actor": row.get("lifecycle_overridden_by"),
                    "detail": row.get("lifecycle_override_reason") or "kept by a reviewer",
                })

            # 3. Approvals, rejections, and whatever execution then did.
            # LIKE's wildcards are not escaped here because a filename containing % or _ can
            # only ever OVER-match; the exact-suffix check below is what decides membership.
            self._db.execute(cur,
                "SELECT id,doc_id,ts,policy_id,policy_version,action,result,detail "
                "FROM disposition_audit WHERE doc_id LIKE %s AND owner_email=%s ORDER BY ts",
                ("scan:%" + suffix, owner))
            for row in self._db.fetchall(cur):
                doc_id = str(row.get("doc_id") or "")
                if not (doc_id.startswith("scan:") and doc_id.endswith(suffix)):
                    continue
                events.append({
                    "ts": row.get("ts"), "kind": "approval",
                    "scan_id": doc_id[len("scan:"):-len(suffix)],
                    "policy_id": row.get("policy_id"),
                    "policy_version": row.get("policy_version"),
                    "result": row.get("result"), "action": row.get("action"), "actor": None,
                    "detail": row.get("detail") or "",
                })

            # 4. Anything either path chose to narrate.
            self._db.execute(cur,
                "SELECT dl.ts,dl.actor,dl.action,dl.scan_id,dl.rule_id,dl.detail "
                "FROM decision_log dl WHERE dl.file=%s AND EXISTS "
                "(SELECT 1 FROM scan_runs sr WHERE sr.id=dl.scan_id AND sr.owner_email=%s) "
                "ORDER BY dl.ts", (file, owner))
            for row in self._db.fetchall(cur):
                events.append({
                    "ts": row.get("ts"), "kind": "decision", "scan_id": row.get("scan_id"),
                    "policy_id": row.get("rule_id"), "policy_version": None,
                    "result": row.get("action"), "action": None, "actor": row.get("actor"),
                    "detail": row.get("detail") or "",
                })

        # Oldest first: a timeline is read forwards. Undated rows sort last rather than being
        # dropped - an event that happened is still evidence even when nothing recorded when.
        events.sort(key=lambda e: (e.get("ts") is None, e.get("ts") or ""))
        return events[:limit]

    def drive_targets_for_files(self, scan_id: str, files: list[str], owner: str) -> dict[str, str]:
        """{file: drive_file_id} for the files in one scan that have one, in ONE query.

        This is the bridge between the two identifier spaces. The lifecycle evaluator stamps
        `scan:{scan_id}:{file}` while the governance layer keys on `drive:{id}`, and the value
        that connects them has been sitting on the inventory row the whole time. Reading it here
        lets a plan say what WOULD happen to a lifecycle candidate without changing either id
        scheme, and without a migration.

        A file with no drive_file_id is simply absent, which the caller reports as a blocker —
        it is not Drive-backed, so nothing could act on it."""
        if not files:
            return {}
        placeholders = ",".join(["%s"] * len(files))
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT file,drive_file_id FROM scan_inventory si WHERE si.scan_id=%s "
                f"AND si.file IN ({placeholders}) AND si.drive_file_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM scan_runs sr WHERE sr.id=si.scan_id "
                "AND sr.owner_email=%s)",
                (scan_id, *files, owner))
            return {r["file"]: r["drive_file_id"] for r in self._db.fetchall(cur)
                    if r.get("drive_file_id")}

    def pending_approvals_by_file(self, scan_id: str, owner: str) -> dict[str, dict]:
        """The pending disposition decision for each file in one scan, keyed by file, ONE query.

        Deliberately NOT a join onto list_lifecycle_files. Two tables that look joinable here are
        not safely so: lifecycle_evaluation holds a row per (scan, file, policy, VERSION), so a
        re-evaluated policy multiplies the inventory row and silently inflates the queue's own
        counts — the one number a reviewer has to be able to trust. disposition_audit is safe on
        its own because only the CHOSEN action is queued for approval (tag rows land 'applied',
        never 'pending_approval'), so there is exactly one pending row per file.

        Carries what a grouped approval needs and nothing else: PRD §8 lets a batch cover only
        rows sharing a policy, its version and its action, and the queue cannot bound a selection
        by facts it was never given."""
        out: dict[str, dict] = {}
        prefix = f"scan:{scan_id}:"
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,doc_id,policy_id,policy_version,action FROM disposition_audit "
                "WHERE doc_id LIKE %s AND owner_email=%s AND result='pending_approval'",
                (prefix + "%", owner))
            for row in self._db.fetchall(cur):
                doc_id = str(row.get("doc_id") or "")
                if not doc_id.startswith(prefix):        # LIKE is not anchored on '_' wildcards
                    continue
                out[doc_id[len(prefix):]] = {
                    "audit_id": row.get("id"), "policy_id": row.get("policy_id"),
                    "policy_version": row.get("policy_version"), "action": row.get("action"),
                }
        return out

    def count_lifecycle_files(self, scan_id: str, owner: str, *, status: str | None = None,
                              policy_id: str | None = None, candidate_only: bool = False) -> int:
        where, args = ["si.scan_id=%s", "EXISTS (SELECT 1 FROM scan_runs sr WHERE sr.id=si.scan_id AND sr.owner_email=%s)"], [scan_id, owner]
        if status == "already_archived":
            where.append("COALESCE(si.lifecycle_status,'Active') IN ('Already archived','Archived')")
        elif status == "unevaluable":
            where.append("COALESCE(si.lifecycle_status,'Active') IN ('Unevaluable','Conflict — review required')")
        elif status:
            where.append("COALESCE(si.lifecycle_status,'Active')=%s"); args.append(status)
        if candidate_only:
            where.append("si.lifecycle_status IN ('Archive Candidate','Delete Candidate')")
        if policy_id:
            where.append("si.lifecycle_rule_id=%s"); args.append(policy_id)
        with self._db.cursor() as cur:
            self._db.execute(cur, f"SELECT COUNT(*) AS n FROM scan_inventory si WHERE {' AND '.join(where)}", tuple(args))
            return int((self._db.fetchone(cur) or {}).get("n") or 0)

    def lifecycle_evaluations_by_document(self, scan_id: str, owner: str) -> dict[str, list[dict]]:
        """Every lifecycle evaluation in one scan, grouped by document_id, in ONE query.

        The per-file sibling below is right for a detail view and wrong for an export.
        scan_inventory_csv called it once per inventory row over an endpoint whose own docstring
        says "Not paginated: it IS the export" — and lifecycle_file_detail costs TWO queries
        (the inventory row, then its evaluations), so a 6,000-file estate paid ~12,000 extra
        round trips to decorate a single CSV. The rows were never the problem: with no
        evaluations recorded the read amplification is zero and the query amplification is
        still 2N, which is why tests/test_inventory_read_amplification.py's row counter did not
        catch it and this one is guarded by a QUERY count instead.

        Served by idx_lifecycle_evaluation_scan(scan_id, owner_email), which already existed."""
        out: dict[str, list[dict]] = {}
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT document_id,evaluation_id,policy_id,policy_version,result,evidence_json,"
                "proposed_action,priority,evaluated_at FROM lifecycle_evaluation "
                "WHERE scan_id=%s AND owner_email=%s ORDER BY document_id,priority,policy_id",
                (scan_id, owner))
            for row in self._db.fetchall(cur):
                # Same decode as lifecycle_file_detail, including its fail-soft: a row whose
                # evidence will not parse still reports its policy and result rather than
                # taking the whole export down.
                try:
                    row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
                except Exception:
                    row["evidence"] = {}
                out.setdefault(row.get("document_id"), []).append(row)
        return out

    def lifecycle_file_detail(self, scan_id: str, document_id: str, owner: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, f"SELECT {self._INV_COLS} FROM scan_inventory WHERE scan_id=%s AND file=%s "
                             "AND EXISTS (SELECT 1 FROM scan_runs sr WHERE sr.id=scan_inventory.scan_id AND sr.owner_email=%s)",
                             (scan_id, document_id, owner))
            row = self._db.fetchone(cur)
            if not row:
                return None
            self._db.execute(cur,
                "SELECT evaluation_id,policy_id,policy_version,result,evidence_json,proposed_action,priority,evaluated_at "
                "FROM lifecycle_evaluation WHERE scan_id=%s AND document_id=%s AND owner_email=%s ORDER BY priority,policy_id",
                (scan_id, document_id, owner))
            evaluations = self._db.fetchall(cur)
            for evaluation in evaluations:
                try: evaluation["evidence"] = json.loads(evaluation.pop("evidence_json") or "{}")
                except Exception: evaluation["evidence"] = {}
            return {**row, "evaluations": evaluations}

    # ── Per-file tags (PRD §4.2 Tag action / §3 auto-tagging) ───────────────────
    def add_file_tags(self, scan_id: str, file: str, tags: list[str], *,
                      kind: str = "system", rule_id: str | None = None) -> None:
        """Attach tags to one file. kind: 'system' (rule-applied) or 'user' (manual).
        Idempotent per (scan_id, file, tag) — re-running a tagging rule adds nothing new."""
        if not tags:
            return
        now = self._now()
        with self._db.cursor() as cur:
            for tag in tags:
                if not tag:
                    continue
                self._db.execute(cur,
                    "INSERT INTO file_tags(scan_id,file,tag,kind,rule_id,created_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file,tag) DO UPDATE SET "
                    "kind=EXCLUDED.kind, rule_id=EXCLUDED.rule_id",
                    (scan_id, file, tag, kind, rule_id, now))

    def bulk_add_file_tags(self, rows: list) -> None:
        """Bulk-insert file tags accumulated by the lifecycle rule evaluator.
        rows: list of (scan_id, file, tag, kind, rule_id). Idempotent — ON CONFLICT upserts."""
        if not rows:
            return
        now = self._now()
        with self._db.cursor() as cur:
            self._db.executemany(cur,
                "INSERT INTO file_tags(scan_id,file,tag,kind,rule_id,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file,tag) DO UPDATE SET "
                "kind=EXCLUDED.kind, rule_id=EXCLUDED.rule_id",
                [(scan_id, file, tag, kind, rule_id, now)
                 for scan_id, file, tag, kind, rule_id in rows])

    def list_file_tags(self, scan_id: str, file: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT tag,kind,rule_id,created_at FROM file_tags "
                "WHERE scan_id=%s AND file=%s ORDER BY tag", (scan_id, file))
            return self._db.fetchall(cur)

    def list_tags_for_scan(self, scan_id: str) -> dict:
        """{file: [tag,...]} for the whole scan — one query so the Discover grid can render
        tags without N calls."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,tag FROM file_tags WHERE scan_id=%s ORDER BY file,tag", (scan_id,))
            out: dict = {}
            for r in self._db.fetchall(cur):
                out.setdefault(r["file"], []).append(r["tag"])
            return out

    def remove_file_tag(self, scan_id: str, file: str, tag: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM file_tags WHERE scan_id=%s AND file=%s AND tag=%s",
                             (scan_id, file, tag))

    def save_file_result(self, scan_id: str, f: dict, completed_at: str,
                         *, job: dict | None = None) -> bool:
        """Persist one assessed file (same shape save_scan writes). Idempotent so a
        retried scan_file job doesn't double-insert.

        Returns True if the result was written, False if it was REFUSED as stale.

        THE FENCE, and why the queue's existing one does not cover this. #1075/#1080 made every
        queue OUTCOME write require the current claim, so a superseded worker cannot mark a job
        done or dead. That was reported — by me — as "a superseded worker cannot publish". True
        of the job row; false of the result. This method took no claim at all, and it does more
        than set a score: it replaces the file's issue_records, rule traces, manifest, PII
        findings and inventory row. A stale write substitutes the finding set a reviewer is
        reading, and feeds count_files_done, which gates scan_finalize.

        WHICH WRITER IS ACTUALLY DANGEROUS. Not the crashed one — a dead process writes nothing.
        It is a worker that is alive but no longer owns the job:

          - slow, not dead: its lease expires, reclaim_stuck_jobs requeues, another worker takes
            attempt 2, and the original handler runs to completion and writes. Its complete_job
            is correctly refused; the row it already wrote was not.
          - the timeout orphan: _analyse_and_persist_one runs the work on a DAEMON thread and
            joins it for ACP_SCAN_FILE_TIMEOUT_S, then records an error and moves on WITHOUT
            cancelling it. That thread keeps running and writes later.

        WHY MONOTONIC BY ATTEMPT rather than "is this claim still current". The orphan thread DID
        hold the claim when it started, so a liveness check would let it through; and by the time
        it lands the claim may legitimately have moved on. Comparing attempts answers the
        question that actually matters — is this result older than what is already stored — and
        it needs no round trip to the jobs table.

        THE COMPARISON IS SCOPED TO ONE JOB, which is the part an attempt number alone gets
        wrong. Attempt counters are per-job and mean nothing across jobs: rescore_file walks the
        same (scan_id, file) row under its OWN counter, so a first-attempt re-score landing on a
        row written by a scan_file job's second attempt would be refused — a deliberate user
        action silently dropped, by a guard meant to stop an abandoned thread. Only a lower
        attempt of the SAME job id is refused; every other writer passes as before.

        EQUAL ATTEMPTS STILL WIN, deliberately. Within one attempt the late orphan replacing its
        own timeout error row is the documented, useful behaviour, and a retried job re-saving
        the same file must still update it. Only a STRICTLY LOWER attempt is refused.

        A refused write touches NOTHING. The dependent rows are written only after the upsert is
        known to have applied — otherwise a refusal would still delete the finding set it was not
        allowed to replace, which is most of the harm with none of the benefit.
        """
        # The write's identity, or (None, None) for a caller that has no job in hand — a test
        # double, a fixture, an import path. Those keep the pre-fence behaviour exactly.
        _job_id = (job or {}).get("id")
        _attempt = (job or {}).get("attempts")
        target = config_target()
        # Phase 3a — the scan's FROZEN scope (recorded by init_scan_run at discover), NOT the live
        # global. This is the FAN-OUT path: the scan_runs row already exists, so get_scan_scope(sid)
        # reads the committed value — the SAME value analyse_and_assess / rescore_reused thread into
        # the score for this scan, so the traces written here and that score read one frozen scope.
        scope = self.get_scan_scope(scan_id)
        # PRD §4.4 / C4 — narrow to THIS file's per-file WCAG scope rules (folder/owner) if any
        # frozen rule targets it; unchanged otherwise. The score path (scanner.analyse_and_assess /
        # rescore_reused) applies the SAME resolution, so this file's traces and its score agree.
        scope = self.scope_for_file(scan_id, f["file"], scope)
        import json as _json
        catalog = _CATALOG_JSON
        with self._db.cursor() as cur:
            # The WHERE on DO UPDATE is the fence. Supported by both SQLite and Postgres, and
            # confirmed by experiment rather than by reading: a failed WHERE leaves rowcount 0,
            # which is what the refusal below reads.
            #
            # Every clause but the last says ALLOW. The single refusal is the fall-through: same
            # job, strictly lower attempt. A row with no stamp, a writer with no stamp, or a
            # DIFFERENT job all pass, because this must narrow who can CLOBBER and never widen
            # who is blocked.
            #
            # COALESCE, not a plain EXCLUDED assignment, so an unstamped write does not ERASE the
            # stamp a fenced one left. Assignment would let any passer-by reset the columns to
            # NULL and reopen the row to every stale writer — a guard anyone can switch off is
            # not a guard.
            self._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id,acp_stamped,checksum,size_kb,pages,sheets,source_modified,written_job,written_attempt) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file) DO UPDATE SET "
                "engine=EXCLUDED.engine,status=EXCLUDED.status,score=EXCLUDED.score,"
                "compliant=EXCLUDED.compliant,skipped_rules=EXCLUDED.skipped_rules,"
                "drive_file_id=EXCLUDED.drive_file_id,acp_stamped=EXCLUDED.acp_stamped,checksum=EXCLUDED.checksum,"
                "size_kb=EXCLUDED.size_kb,pages=EXCLUDED.pages,sheets=EXCLUDED.sheets,source_modified=EXCLUDED.source_modified,"
                "written_job=COALESCE(EXCLUDED.written_job,file_records.written_job),"
                "written_attempt=COALESCE(EXCLUDED.written_attempt,file_records.written_attempt) "
                "WHERE file_records.written_attempt IS NULL "
                "   OR EXCLUDED.written_attempt IS NULL "
                "   OR file_records.written_job IS NULL "
                "   OR EXCLUDED.written_job IS NULL "
                "   OR file_records.written_job <> EXCLUDED.written_job "
                "   OR EXCLUDED.written_attempt >= file_records.written_attempt",
                (scan_id, f["file"], f["engine"], f["status"], f["score"],
                 int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id"), f.get("acp_stamped"),
                 f.get("checksum"), f.get("size_kb"), f.get("pages"), f.get("sheets"), f.get("source_modified"),
                 _job_id, _attempt))
            if (getattr(cur, "rowcount", 1) or 0) == 0:
                # Refused. Return BEFORE the dependent writes below — a refusal that still deleted
                # issue_records would do the damage it was refusing to do.
                print(f"[acp] save_file_result: refused a stale result for {scan_id}/{f['file']} "
                      f"from job {_job_id} attempt {_attempt} — a later attempt of that same job "
                      f"has already written it", flush=True)
                return False
            self._db.execute(cur, "DELETE FROM issue_records WHERE scan_id=%s AND file=%s", (scan_id, f["file"]))
            issues = f.get("issues", [])
            if issues:
                self._db.executemany(cur,
                    "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity,detail,page,location) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(scan_id, f["file"], i["ruleId"], i["wcag"], i["severity"], i.get("detail"),
                      i.get("page"), _issue_location(i)) for i in issues])
            fail_counts, review_counts = _split_sc_counts(
                filter_issues_to_target(f.get("issues", []), target))
            fmt = _file_format(f["file"])
            trace_rows = []
            for rule in RULE_CATALOG:
                rid = rule["id"]
                fc, rc = fail_counts.get(rid, 0), review_counts.get(rid, 0)
                outcome = _rule_outcome(rid, fmt, fc, rc, target, scope)
                count = fc if fc else rc
                trace_rows.append((scan_id, f["file"], rid, rule["name"], rule.get("plain"), rule["level"],
                                   rule["fix_mode"], outcome, count))
            self._db.executemany(cur,
                "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file,rule_id) DO UPDATE SET "
                "outcome=EXCLUDED.outcome,finding_count=EXCLUDED.finding_count",
                trace_rows)
            self._save_file_manifest(cur, scan_id, f, catalog)
            for pf in (f.get("pii") or {}).get("findings", []):
                self._db.execute(cur,
                    "INSERT INTO pii_findings(scan_id,file,pii_type,label,count,severity,samples) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file,pii_type) DO UPDATE SET "
                    "count=EXCLUDED.count,severity=EXCLUDED.severity,samples=EXCLUDED.samples",
                    (scan_id, f["file"], pf["type"], pf["label"], pf["count"], pf["severity"],
                     _json.dumps(pf["samples"])))
            self._db.execute(cur, _UPSERT_INV,
                (f["file"], completed_at, completed_at, f["status"], f["score"]))
            # GET /scans/{id} uses scan_runs.revision as its freshness key.  A file result is
            # exactly the write the Assess progress screen is polling for, so leaving revision
            # unchanged lets an intermediary/browser reuse the Discover-only payload while
            # workers are successfully adding file_records.  Advance it in this same transaction
            # after the complete result (record + findings + traces) is durable.
            self._bump_scan_revision(cur, scan_id)
        return True

    def find_by_checksum(self, scan_id: str, checksum: str) -> dict | None:
        """Look up an already-analysed file in THIS scan with the same Drive md5Checksum —
        i.e. a byte-identical duplicate uploaded under a different name/folder. Returns a
        dict shaped for save_file_result (ruleId-keyed issues, pii in detect_file's shape)
        so the caller can copy it forward under the new file's name instead of re-running
        the engine + PII extraction. None if no match (first occurrence, or checksum-less
        source like SharePoint/local)."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,engine,status,score,compliant,skipped_rules,acp_stamped "
                "FROM file_records WHERE scan_id=%s AND checksum=%s LIMIT 1",
                (scan_id, checksum))
            row = self._db.fetchone(cur)
            if not row:
                return None
            self._db.execute(cur,
                "SELECT rule_id,wcag,severity,detail,page,location FROM issue_records WHERE scan_id=%s AND file=%s",
                (scan_id, row["file"]))
            issues = [{"ruleId": r["rule_id"], "wcag": r["wcag"], "severity": r["severity"],
                       "detail": r["detail"], "page": r["page"], "location": r["location"]}
                      for r in self._db.fetchall(cur)]
            self._db.execute(cur,
                "SELECT pii_type,label,count,severity,samples FROM pii_findings "
                "WHERE scan_id=%s AND file=%s", (scan_id, row["file"]))
            pii_rows = self._db.fetchall(cur)
        pii = None
        if pii_rows:
            findings = [{"type": p["pii_type"], "label": p["label"], "count": p["count"],
                        "severity": p["severity"],
                        "samples": _json.loads(p["samples"]) if p.get("samples") else []}
                       for p in pii_rows]
            total = sum(p["count"] for p in findings)
            sev = None
            for p in findings:
                if sev is None or _PII_SEV_RANK.get(p["severity"], 0) > _PII_SEV_RANK.get(sev, 0):
                    sev = p["severity"]
            pii = {"types": {p["type"]: p["count"] for p in findings}, "total": total,
                  "severity": sev, "findings": findings}
        return {"engine": row["engine"], "status": row["status"], "score": row["score"],
               "compliant": row["compliant"], "skipped_rules": row["skipped_rules"],
               "acp_stamped": row["acp_stamped"], "issues": issues, "pii": pii,
               "dedup_of": row["file"]}

    def find_prior_analysis(self, owner: str | None, drive_file_id: str | None,
                            checksum: str | None, rubric_hash: str | None) -> dict | None:
        """ADR 0011: reuse a file's analysis from an EARLIER scan (not just this one --
        see find_by_checksum above for the narrower within-scan version). Gated on the
        SAME owner + SAME drive_file_id (stable Drive identity, survives rename) + SAME
        checksum (byte-identical) + SAME rubric_hash -- the last one is the correctness-
        critical piece: a stale analysis under an old rubric is not valid evidence once
        the rule set has changed, so a rubric_hash mismatch always falls through to a
        real re-analysis. Returns the most recently completed match, same shape as
        find_by_checksum (ruleId-keyed issues, pii in detect_file's shape)."""
        if not (owner and drive_file_id and checksum and rubric_hash):
            return None
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT fr.scan_id, fr.file, fr.engine, fr.status, fr.score, fr.compliant, "
                "fr.skipped_rules, fr.acp_stamped FROM file_records fr "
                "JOIN scan_runs sr ON sr.id = fr.scan_id "
                "WHERE sr.owner_email=%s AND fr.drive_file_id=%s AND fr.checksum=%s "
                "AND sr.rubric_hash=%s AND sr.completed_at IS NOT NULL "
                "ORDER BY sr.completed_at DESC LIMIT 1",
                (owner, drive_file_id, checksum, rubric_hash))
            row = self._db.fetchone(cur)
            if not row:
                return None
            prior_scan_id = row["scan_id"]
            self._db.execute(cur,
                "SELECT rule_id,wcag,severity,detail,page,location FROM issue_records WHERE scan_id=%s AND file=%s",
                (prior_scan_id, row["file"]))
            issues = [{"ruleId": r["rule_id"], "wcag": r["wcag"], "severity": r["severity"],
                       "detail": r["detail"], "page": r["page"], "location": r["location"]}
                      for r in self._db.fetchall(cur)]
            self._db.execute(cur,
                "SELECT pii_type,label,count,severity,samples FROM pii_findings "
                "WHERE scan_id=%s AND file=%s", (prior_scan_id, row["file"]))
            pii_rows = self._db.fetchall(cur)
        pii = None
        if pii_rows:
            findings = [{"type": p["pii_type"], "label": p["label"], "count": p["count"],
                        "severity": p["severity"],
                        "samples": _json.loads(p["samples"]) if p.get("samples") else []}
                       for p in pii_rows]
            total = sum(p["count"] for p in findings)
            sev = None
            for p in findings:
                if sev is None or _PII_SEV_RANK.get(p["severity"], 0) > _PII_SEV_RANK.get(sev, 0):
                    sev = p["severity"]
            pii = {"types": {p["type"]: p["count"] for p in findings}, "total": total,
                  "severity": sev, "findings": findings}
        return {"engine": row["engine"], "status": row["status"], "score": row["score"],
               "compliant": row["compliant"], "skipped_rules": row["skipped_rules"],
               "acp_stamped": row["acp_stamped"], "issues": issues, "pii": pii,
               "reused_from_scan": prior_scan_id}

    def bump_files_done(self, scan_id: str, n: int = 1) -> tuple[int, int]:
        """Atomically increment the done counter by n (default 1; a scan_batch bumps by
        its chunk size — ADR 0008); returns (done, total enqueued)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET files_done=COALESCE(files_done,0)+%s WHERE id=%s "
                "RETURNING files_done, files", (n, scan_id))
            row = self._db.fetchone(cur)
        return (row["files_done"], row["files"]) if row else (0, 0)

    def count_files_done(self, scan_id: str) -> tuple[int, int]:
        """(distinct files persisted, total enqueued) — the idempotent finalize trigger
        (ADR 0013). save_file_result upserts, so a retried scan_file re-saving the same row
        can't inflate the count; unlike the running counter (bump_files_done) this never
        overshoots or finalizes a scan early after a crash/retry."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT (SELECT COUNT(*) FROM file_records WHERE scan_id=%s) AS done, files "
                "FROM scan_runs WHERE id=%s", (scan_id, scan_id))
            row = self._db.fetchone(cur)
        return (row["done"], row["files"]) if row else (0, 0)

    def mark_finalized(self, scan_id: str) -> bool:
        """Claim the finalize exactly once: set finalized_at iff still unset. Returns True for
        the single caller that won (it emits HITL routing + audit); False for duplicate/
        concurrent scan_finalize runs, which then no-op (ADR 0013). The summary recompute
        (finalize_scan_run) stays idempotent and runs regardless."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET finalized_at=%s WHERE id=%s AND finalized_at IS NULL",
                (now, scan_id))
            return getattr(cur, "rowcount", 1) == 1

    def finalize_scan_run(self, scan_id: str, completed_at: str) -> dict:
        """Aggregate per-file results into the scan_runs summary — matches
        Rubric.aggregate (certifiable=Σcompliant, uncertain/error by status,
        avg=mean of scored). 'files' becomes the count actually analysed.

        REFUSES to finalize a run already ended as 'superseded' or 'cancelled'. Without that
        guard an ended run resurrects itself: supersede_scan marks the scan 'superseded' and its
        jobs 'dead', but it does NOT set cancel_requested_at — the only field check_cancel()
        reads — so a worker already executing that job never stops. It runs to completion and
        arrives here, and this UPDATE had no status test, so it wrote status='done' with
        completed_at=NOW().

        list_scans() excludes 'superseded' but orders by completed_at DESC, so the resurrected
        run came back with the FRESHEST timestamp in the estate and displaced the run that
        replaced it. That is precisely the collapse supersede_scan's own docstring records from
        2026-08-26 ("newest has 0 documents but a recent scan had 999"), reachable again through
        finalize rather than through cancel_scan's completed_at.

        The window is not small. It is the whole remaining duration of the superseded run, because
        nothing interrupts it. Making supersession actually stop the worker — setting
        cancel_requested_at so check_cancel() fires — is the follow-up that would also stop it
        burning Drive quota and DB connections; this guard is the correctness half, and it holds
        whether or not the worker ever learns to stop."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET status='done', completed_at=%s, "
                "files=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s), "
                "certifiable=(SELECT COALESCE(SUM(compliant),0) FROM file_records WHERE scan_id=%s), "
                "uncertain=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s AND status='uncertain'), "
                "error=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s AND status='error'), "
                "avg_score=(SELECT ROUND(AVG(score)) FROM file_records WHERE scan_id=%s AND score IS NOT NULL) "
                "WHERE id=%s AND status NOT IN ('superseded','cancelled')",
                (completed_at, scan_id, scan_id, scan_id, scan_id, scan_id, scan_id))
            self._bump_scan_revision(cur, scan_id)
            self._db.execute(cur,
                "SELECT files,certifiable,uncertain,error,avg_score FROM scan_runs WHERE id=%s", (scan_id,))
            return self._db.fetchone(cur) or {}

    def record_file_timing(self, scan_id: str, file: str, rollup: dict) -> None:
        """Persist one file's per-stage timing (ADR 0037 Step 0). A SIDE-CHANNEL — the caller wraps this
        best-effort so a timing write can never fail the scan. Idempotent (upsert on scan_id,file), the
        same retry discipline as file_records, so a re-run re-writes rather than doubling."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO file_stage_timings(scan_id,file,timings) VALUES(%s,%s,%s) "
                "ON CONFLICT(scan_id,file) DO UPDATE SET timings=EXCLUDED.timings",
                (scan_id, file, _json.dumps(rollup or {})))

    def scan_timings(self, scan_id: str) -> dict:
        """The per-scan stage-timing rollup (ADR 0037 Step 0): merge every file's timing and summarize —
        totals, counts, per-stage average seconds, and the bottleneck stage. A scan that ran before this
        shipped (or one still early) reports zeros and bottleneck=None, never a fabricated number."""
        import json as _json
        from stage_timing import merge_rollups, summarize
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT timings FROM file_stage_timings WHERE scan_id=%s", (scan_id,))
            rows = self._db.fetchall(cur)
        rollups = []
        for r in rows or []:
            try:
                rollups.append(_json.loads(r["timings"]) if r.get("timings") else {})
            except Exception:                     # a corrupt row must not sink the whole rollup
                continue
        out = summarize(merge_rollups(rollups))
        out["files_timed"] = len(rollups)
        return out

    def pii_summary(self, sid: str | None = None) -> dict:
        """Sensitive-data rollup: docs affected, total items, and per-type counts.
        Scoped to one scan when sid is given, else across all scans."""
        where, params = ("WHERE scan_id=%s", (sid,)) if sid else ("", ())
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT COUNT(DISTINCT file) AS docs, COALESCE(SUM(count),0) AS items "
                f"FROM pii_findings {where}", params)
            roll = self._db.fetchone(cur) or {"docs": 0, "items": 0}
            self._db.execute(cur,
                f"SELECT pii_type, label, COALESCE(SUM(count),0) AS count, "
                f"COUNT(DISTINCT file) AS docs FROM pii_findings {where} "
                f"GROUP BY pii_type, label ORDER BY count DESC", params)
            by_type = self._db.fetchall(cur)
        return {"documents": roll["docs"], "items": roll["items"], "by_type": by_type}

    def list_pii(self, sid: str) -> list[dict]:
        """Per-document sensitive-data findings for one scan (masked samples)."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, pii_type, label, count, severity, samples "
                "FROM pii_findings WHERE scan_id=%s ORDER BY file, count DESC", (sid,))
            rows = self._db.fetchall(cur)
        for r in rows:
            try:
                r["samples"] = _json.loads(r["samples"]) if r.get("samples") else []
            except Exception:
                r["samples"] = []
        return rows

    # Tables holding scan results / activity (what the dashboards chart). Cleared by
    # reset_analytics for a TRUE clean slate. Deliberately EXCLUDES configuration
    # (app_settings, schedule_config, disposition_policy) and user-authored programs
    # (campaign, campaign_batch) so a reset wipes DATA but keeps settings + programs —
    # matching the panel's "Your settings are preserved" promise. Everything here is
    # scan-derived and re-populates on the next scan.
    # Tables holding scan / review DATA (what the dashboards chart, plus per-file decisions,
    # scan inventory, disposition audit, and the org review memory). Cleared by reset_analytics
    # for a TRUE clean slate — everything here is customer/scan-derived and must not survive a
    # reset when the app is handed to a new customer. Deliberately EXCLUDES only genuine
    # configuration (app_settings, schedule_config, disposition_policy, ai_provider_config) and
    # user-authored programs (campaign, campaign_batch), matching the panel's "Your settings are
    # preserved" promise. If you add a table that stores scan/review output, ADD IT HERE — the
    # reset-completeness test (test_reset_leaves_no_customer_data) fails closed if a data table
    # is left out.
    _ANALYTICS_TABLES = ["scan_runs", "file_records", "issue_records", "scan_rule_traces",
                         "file_stage_timings", "scan_file_manifests", "scan_inventory", "file_tags",
                         "scan_decisions", "pii_findings", "hitl_queue", "hitl_events",
                         "disposition_audit", "decision_log", "inventory", "jobs", "documents",
                         "tenant_queue_state",
                         "lifecycle_evaluation", "effective_disposition",
                         "org_memory", "remediation_state", "remediation_diff", "applied_fixes",
                         "ai_calls", "finding_comments",
                         "scan_inputs",  # Stage 1 item 3: per-scan enqueue snapshots are customer data
                         "scan_folder_completions",  # which folders of a scan were counted done
                         "active_discovery_guard",  # transient lock state — cleared on reset
                         "sync_cursors",  # connector sync position is customer-derived, not config
                         "overview_snapshots",  # derived from scan results — customer data, not config
                         "scan_events",  # ADR 0042 lifecycle log — a record OF customer scans
                         "content_workspaces",  # ADR 0044 — a customer's own workspace, not config
                         "content_workspace_documents", "content_workspace_document_versions",
                         "orchestration_events",  # operational log — carries owner_email, customer data
                         "worker_instances",  # not customer data, but not genuine config either (no
                         # owner_email, nothing a customer authors) — a fresh worker re-registers
                         # itself on the next heartbeat, same reasoning as active_discovery_guard's
                         # "transient lock state — cleared on reset" above.
                         # ── ACR workspace (ADR 0047). All seven are DATA, on this file's existing
                         # rule that RULES survive a reset and RECORDS do not: disposition_policy
                         # survives while disposition_audit is wiped, and decision_log — the
                         # append-only audit record — is wiped too. A conformance report is a
                         # record about a product version, authored by a customer; none of it is
                         # config.
                         "acr_report", "acr_criterion", "acr_evidence", "acr_manual_test",
                         # acr_manual_step is what a tester OBSERVED during a run — a record about
                         # a product version, on exactly the same footing as the run it belongs to.
                         "acr_manual_step",
                         "acr_decision_log",
                         # Published snapshots included, and the tension is worth naming: they are
                         # immutable, which means never MODIFIED — not exempt from an explicit,
                         # owner-authorised wipe of the whole account. overview_snapshots is
                         # already classified this way for the same reason.
                         "acr_snapshot",
                         # Role grants go too, which is the one genuinely arguable call here.
                         # Report-scoped grants dangle the instant their report is wiped, and a
                         # surviving approver grant is exactly the kind of residue "completely
                         # fresh" promises there will not be. Safe to wipe because it cannot lock
                         # anyone out: acr_authz gives the protected ACP_OWNER_EMAIL every role
                         # unconditionally, so the owner can always grant the first role again —
                         # the same anti-lockout property core.is_owner exists to provide.
                         "acr_role"]

    def reset_analytics(self) -> list[str]:
        """Clear all scan results / activity so the Grafana + in-app charts start
        fresh. Keeps settings + schedule. Returns the cleared table names."""
        with self._db.cursor() as cur:
            for t in self._ANALYTICS_TABLES:
                self._db.execute(cur, f"DELETE FROM {t}")
        return list(self._ANALYTICS_TABLES)

    # Tables in _ANALYTICS_TABLES that key on scan_id, scoped via a scan_runs.owner_email join.
    # orchestration_events is here too (delete_scan's scan_id=%s pass picks up its scan-anchored
    # rows for free), but UNLIKE every other table in this list it also carries owner_email
    # directly and many of its rows have scan_id=NULL (a worker becoming ready, a capacity event
    # — nothing to do with any scan). The scan_id-IN-subquery reset_user_data runs against this
    # list cannot reach those NULL-scan_id rows, so reset_user_data ALSO deletes
    # orchestration_events by owner_email directly, after this loop — see its body.
    _RESET_USER_SCAN_TABLES = ["file_records", "issue_records", "scan_rule_traces",
                               "file_stage_timings", "scan_file_manifests", "scan_inventory",
                               "file_tags", "pii_findings", "hitl_queue", "hitl_events",
                               "remediation_diff", "applied_fixes", "ai_calls", "finding_comments",
                               "jobs", "overview_snapshots", "scan_events", "orchestration_events",
                               "scan_folder_completions"]
    # Tables that key on doc_id (not scan_id), scoped via a documents.owner_email join.
    _RESET_USER_DOC_TABLES = ["disposition_audit", "remediation_state"]

    def reset_user_data(self, owner_email: str) -> dict:
        """Delete ONE user's scans and everything tied to them — the self-service sibling of
        reset_analytics(), scoped so two people testing concurrently never clear each other's work.

        Three shapes of table:
          - scan_id-keyed (_RESET_USER_SCAN_TABLES): scan_id IN (SELECT id FROM scan_runs WHERE
            owner_email=%s).
          - doc_id-keyed (_RESET_USER_DOC_TABLES): doc_id IN (SELECT doc_id FROM documents WHERE
            owner_email=%s) — disposition_audit/remediation_state key on doc_id, not scan_id.
          - owns owner_email directly: scan_decisions, documents, scan_runs, content_workspaces,
            content_workspace_documents (ADR 0044 — WHERE owner_email=%s); org_memory
            (WHERE org=%s — every call site sets `org` to the signed-in user's own email, so it
            is already per-user despite the name).
          - content_workspace_document_versions carries no owner_email of its own (see its
            migration comment) — scoped via document_id IN (SELECT id FROM
            content_workspace_documents WHERE owner_email=%s), deleted BEFORE its parent
            documents for the same "no real FK, but tidy child-before-parent order" reason
            _RESET_USER_DOC_TABLES's rows are deleted before `documents` below.

        orchestration_events is a FIFTH shape, unique to it in this method: it's in
        _RESET_USER_SCAN_TABLES (so the scan_id-IN-subquery pass above catches every event
        anchored to one of this owner's scans), but it ALSO carries owner_email directly, and
        many of its rows have scan_id=NULL — a worker becoming ready or a capacity event isn't
        about any scan, so the subquery can never reach them. An explicit second pass, scoped by
        owner_email directly, runs right after the loop to catch those too. worker_instances is
        NOT touched here at all: it has no owner_email and no scan_id — a worker isn't scoped to
        a tenant, so per-user reset has nothing to key a deletion on (it IS cleared by the global
        reset_analytics(), see _ANALYTICS_TABLES).

        Deliberately excluded, unlike reset_analytics():
          - `inventory` — a global path-dedup index with no owner concept; nothing to scope it by.
          - `decision_log` — documented as an immutable append-only audit record (reset_analytics
            wiping it is an existing inconsistency, not repeated here). One row IS appended by the
            caller after this returns, recording that the reset happened.

        Cross-attribution: finding_comments/hitl_events/ai_calls etc. are scoped by the SCAN's
        owner, not by who authored/reviewed each row — resetting your scan removes a teammate's
        comment on it too, because the scan it was about no longer exists. That is "delete my scan
        and everything about it," not "delete only what I personally wrote."

        DB rows only — does not purge Blob-stored remediated copies or Drive mirrors (unlike the
        admin reset's blob purge, which is a GLOBAL purge unsafe to run per-user without first
        tracking which blob URLs belong to this owner's files — not built here). A reset user may
        see stale bytes take extra storage until a real per-owner blob accounting exists; nothing
        product-visible references them once the DB rows are gone.
        """
        cleared: list[str] = []
        with self._db.cursor() as cur:
            for t in self._RESET_USER_SCAN_TABLES:
                self._db.execute(cur,
                    f"DELETE FROM {t} WHERE scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)",
                    (owner_email,))
                cleared.append(t)
            # orchestration_events' scan_id-less rows (worker/capacity/dependency events with no
            # scan involved) are invisible to the scan_id-IN-subquery pass above — this second
            # pass, scoped by the column the table carries directly, is what actually makes this
            # owner's log fully gone. Safe to re-run over rows the loop above already deleted.
            self._db.execute(cur, "DELETE FROM orchestration_events WHERE owner_email=%s", (owner_email,))
            for t in self._RESET_USER_DOC_TABLES:
                self._db.execute(cur,
                    f"DELETE FROM {t} WHERE doc_id IN (SELECT doc_id FROM documents WHERE owner_email=%s)",
                    (owner_email,))
                cleared.append(t)
            self._db.execute(cur, "DELETE FROM scan_decisions WHERE owner_email=%s", (owner_email,))
            cleared.append("scan_decisions")
            self._db.execute(cur, "DELETE FROM tenant_queue_state WHERE tenant_key=%s", (owner_email,))
            cleared.append("tenant_queue_state")
            self._db.execute(cur, "DELETE FROM documents WHERE owner_email=%s", (owner_email,))
            cleared.append("documents")
            self._db.execute(cur, "DELETE FROM org_memory WHERE org=%s", (owner_email,))
            cleared.append("org_memory")
            self._db.execute(cur,
                "DELETE FROM content_workspace_document_versions WHERE document_id IN "
                "(SELECT id FROM content_workspace_documents WHERE owner_email=%s)", (owner_email,))
            cleared.append("content_workspace_document_versions")
            self._db.execute(cur,
                "DELETE FROM content_workspace_documents WHERE owner_email=%s", (owner_email,))
            cleared.append("content_workspace_documents")
            self._db.execute(cur, "DELETE FROM content_workspaces WHERE owner_email=%s", (owner_email,))
            cleared.append("content_workspaces")
            # scan_runs last — every scan_id-scoped subquery above depends on these rows existing.
            self._db.execute(cur, "DELETE FROM scan_runs WHERE owner_email=%s", (owner_email,))
            cleared.append("scan_runs")
        return {"owner": owner_email, "cleared_tables": cleared}

    def scan_checksums(self, scan_id: str, owner_email: str) -> list[str]:
        """Distinct non-null content-hash checksums this scan actually downloaded
        (file_records.checksum — Drive's md5Checksum; None for SharePoint/local, which never
        carry one). This is the set of `{owner}/{checksum}` keys the ADR 0020 sources blob
        cache may hold this scan's bytes under (upload_source keys by checksum, not scan_id,
        whenever one was known pre-download) — call BEFORE delete_scan, since that removes
        the file_records rows this reads, and pass the result to blob.purge_scan so the
        HIPAA erasure route reaches those blobs too. Owner-scoped like delete_scan: returns
        [] for a scan_id that doesn't belong to owner_email, never another owner's checksums.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT DISTINCT fr.checksum FROM file_records fr "
                "JOIN scan_runs sr ON sr.id = fr.scan_id "
                "WHERE fr.scan_id=%s AND sr.owner_email=%s AND fr.checksum IS NOT NULL",
                (scan_id, owner_email))
            return [r["checksum"] for r in self._db.fetchall(cur)]

    def delete_scan(self, scan_id: str, owner_email: str) -> dict | None:
        """Delete ONE scan and every row tied to it — the per-scan erasure path required for
        a HIPAA Business Associate Agreement.

        Returns None if the scan does not exist or does not belong to owner_email (prevents
        one user deleting another's scan).  Returns a summary dict on success.

        What is deleted:
          - All rows in _RESET_USER_SCAN_TABLES keyed on scan_id.
          - The scan_runs row itself.

        What is deliberately NOT deleted:
          - decision_log — immutable append-only audit trail; the deletion event is ADDED to
            it by the caller, not the other way round.
          - inventory — global path-dedup index with no scan_id link.
          - Blob storage bytes — call blob.purge_scan(owner, scan_id, checksums) separately
            (the route does this; checksums comes from scan_checksums(), called BEFORE this
            method since it reads the file_records rows this method deletes). Kept separate
            so a DB-only operation never blocks on a slow storage call and the two failure
            modes surface independently.
        """
        # Verify ownership before touching anything.
        with self._db.cursor() as cur:
            self._db.execute(
                cur,
                "SELECT id FROM scan_runs WHERE id=%s AND owner_email=%s",
                (scan_id, owner_email),
            )
            if not self._db.fetchall(cur):
                return None

        with self._db.cursor() as cur:
            for t in self._RESET_USER_SCAN_TABLES:
                self._db.execute(cur, f"DELETE FROM {t} WHERE scan_id=%s", (scan_id,))
            self._db.execute(cur, "DELETE FROM scan_runs WHERE id=%s", (scan_id,))
        return {"scan_id": scan_id, "owner": owner_email}

    def list_scans(self, owner: str | None = None) -> list[dict]:
        # Completed scans only — in-flight (status='running', no completed_at) scans
        # are excluded so they don't appear as bogus entries in the scan picker.
        # 'superseded' (a scan the single-flight guard killed to start a newer one, see
        # supersede_scan) is excluded too: it has completed_at set but is not a real result — it
        # would otherwise outrank the actual scan it was replaced by, since it stamps
        # completed_at=now() at the moment the NEW scan starts. An explicit user Stop
        # ('cancelled') is NOT excluded — that one is meant to stay visible in scan history.
        # Scoped to the signed-in user (per-user isolation): a user sees only their scans.
        where, params = "completed_at IS NOT NULL AND status != 'superseded'", ()
        if owner:
            where += " AND owner_email=%s"; params = (owner,)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score,assessed_at,scope,published_at "
                f"FROM scan_runs WHERE {where} ORDER BY completed_at DESC", params)
            rows = self._db.fetchall(cur)
            # A cancelled/interrupted scan reaches this list (it has completed_at) with its
            # counters still NULL — see _fill_run_aggregate. The picker renders
            # "certifiable / files" per row, so fill them here too rather than showing a gap.
            return [self._fill_run_aggregate(cur, r) for r in rows]

    def list_scans_admin(self) -> list[dict]:
        """All completed scans across all users, including owner_email — admin analytics only.

        Identical to list_scans(owner=None) but adds owner_email to each row so the analytics
        dashboard can break down the estate by user. Not exposed through list_scans to keep the
        per-user isolation contract narrow and explicit: callers that want cross-user data must
        ask for it by name.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,"
                "avg_score,assessed_at,scope,status,owner_email "
                "FROM scan_runs WHERE completed_at IS NOT NULL AND status != 'superseded' "
                "ORDER BY completed_at DESC", ())
            rows = self._db.fetchall(cur)
            return [self._fill_run_aggregate(cur, r) for r in rows]

    def list_scans_including_discovered(self, owner: str | None = None) -> list[dict]:
        """Every scan, newest-first, INCLUDING an ADR 0020 Discover-only run that has never been
        assessed — the one case `list_scans` exists specifically to hide.

        Built for api/routes/assess.py's eligibility preview, which needs to answer "how many
        documents would Assess score" from the LATEST discovery, not the latest ASSESSED scan.
        `list_scans()` cannot serve this: it filters to `completed_at IS NOT NULL` to keep
        in-flight runs out of the scan picker, but a Discover-only run reaches
        status='discovered' with `completed_at` staying NULL forever until Assess runs — the
        exact case this method exists to surface. Found live 2026-08-21: a real, fully-discovered
        170-file estate reported "0 documents will be opened and scored" because the eligibility
        check could not see its own scan.

        Ordered by COALESCE(completed_at, discovered_at, started_at) — completed_at when
        assessed, discovered_at (the instant discovery itself finished, ADR 0020) when not yet
        assessed, started_at only for scans predating the discovered_at column. Mirrors
        previous_run_for_source's identical fallback chain for the identical problem.

        NOT a drop-in replacement for list_scans, and not meant to be used as one — at least
        three other call sites (App.jsx's Time-travel detection, /schedule's "last successful
        scan", and two "previous scan by array position" lookups in scans.py/report.py) depend on
        list_scans' current, narrower "every row has a real completed_at" contract, and widening
        it under them would corrupt array-position lookups the moment a NULL completed_at sorts
        ahead of a real one (Postgres and SQLite disagree on default NULL ordering in
        `ORDER BY ... DESC`, so this could pass tests and misbehave in production). Use this
        method only where the caller genuinely wants "the latest scan, assessed or not."

        Excludes status='superseded' (see supersede_scan) for the same reason list_scans does:
        an auto-cancelled attempt is not a real discovery and must not outrank the real one it
        replaced — "how many documents would Assess score" must not read 0 because a newer scan
        pre-empted a still-running one seconds ago.
        """
        with self._db.cursor() as cur:
            where, params = "status != 'superseded'", ()
            if owner:
                where += " AND owner_email=%s"; params = (owner,)
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score,assessed_at,scope "
                f"FROM scan_runs WHERE {where} "
                "ORDER BY COALESCE(completed_at, discovered_at, started_at) DESC", params)
            rows = self._db.fetchall(cur)
            return [self._fill_run_aggregate(cur, r) for r in rows]

    def list_finished_scans(self, owner: str | None = None) -> list[dict]:
        """Every scan that actually reached a real, trustworthy terminal state — completed_at
        (assessed) OR discovered_at (ADR 0020 Discover-only, never assessed) — newest first.

        Neither list_scans() nor list_scans_including_discovered() is right for a caller that
        wants "the latest FINISHED snapshot" specifically:

          - list_scans() filters to completed_at IS NOT NULL alone, which a Discover-only run
            never sets — the exact 2026-08-21 blind spot (a real, fully-discovered 170-file
            estate read as "0 documents" to a caller using this filter). A production monitor
            hitting the identical gap found live 2026-08-28: /monitor/estate's "did the newest
            scan collapse" check used list_scans() and could never see a Discover-only run at
            all, so its "newest scan" was whatever full-analysis scan happened to predate
            ADR 0020 becoming the default — stale by definition, on every deployment where
            Discover-only scans are now the common case.
          - list_scans_including_discovered() fixes that blind spot but deliberately widens too
            far for THIS purpose: it includes 'running'/'queued' scans too (ordered by
            started_at when neither timestamp is set), so a scan that started 2 seconds ago and
            has not listed a single file yet would outrank a real, finished 5,000-document scan
            as "the newest" — the identical shape of dishonest-zero bug DiscoverRunProgress.jsx
            fights on the frontend, reintroduced server-side. A 'failed' scan is excluded too
            (discovered_at is only ever set on _scan_discover's success path, right before the
            final status flip — see #900) — a failed attempt has no real data to compare.

        'cancelled'/'interrupted' scans DO have completed_at set and are NOT excluded here,
        matching list_scans' own convention: a user-visible stop with partial data is real
        history, not a blind spot. 'superseded' is excluded for the reason both other methods
        exclude it — an auto-cancelled attempt is not a real result.
        """
        with self._db.cursor() as cur:
            where, params = ("(completed_at IS NOT NULL OR discovered_at IS NOT NULL) "
                             "AND status != 'superseded'", ())
            if owner:
                where += " AND owner_email=%s"; params = (owner,)
            self._db.execute(cur,
                "SELECT id,completed_at,discovered_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score,assessed_at,scope "
                f"FROM scan_runs WHERE {where} "
                "ORDER BY COALESCE(completed_at, discovered_at) DESC", params)
            rows = self._db.fetchall(cur)
            return [self._fill_run_aggregate(cur, r) for r in rows]

    def mark_assessed(self, scan_id: str, when: str) -> None:
        """Stamp the scan as assessed (the user ran Assess). Results views gate on this."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE scan_runs SET assessed_at=%s WHERE id=%s AND assessed_at IS NULL",
                             (when, scan_id))
            if cur.rowcount > 0:
                self._bump_scan_revision(cur, scan_id)

    # ── Overview snapshot cache (workspace-bootstrap redesign, Phase 1) ──
    #
    # The last completed scan is an excellent cache candidate: it is effectively immutable
    # until remediation, publishing, or a review decision changes it. `revision` on scan_runs
    # counts those changes; every write path below that can alter what the Overview tab would
    # show bumps it, which is what lets get_overview_snapshot() cache the (expensive, aggregate)
    # snapshot forever instead of on a timer — scan history is immutable evidence unless a
    # recorded mutation changes it.
    def _bump_scan_revision(self, cur, scan_id: str) -> None:
        """Advance scan_runs.revision, invalidating any cached overview_snapshots row for this
        scan (the old (owner,scan,revision,rubric_hash) key simply stops being looked up —
        nothing to delete). MUST be called on the same cursor/transaction as the write that
        earns it, and only when that write actually changed a row (callers check
        cur.rowcount first) — an invalidation for a write that changed nothing would cache-bust
        every reader for no reason."""
        self._db.execute(cur, "UPDATE scan_runs SET revision=COALESCE(revision,0)+1 WHERE id=%s",
                         (scan_id,))

    def get_overview_snapshot(self, scan_id: str, owner: str) -> dict | None:
        """The compact Overview summary for one scan, cached and tenant-isolated.

        Cache key is (owner, scan_id, scan_revision, rubric_hash) — owner is part of the KEY,
        not just a post-hoc filter, so a lookup for the wrong owner is a cache miss, never a
        cross-tenant read. Returns None only when the scan does not exist or does not belong to
        `owner` (matches get_scan's contract).

        A finished scan's snapshot is generated once and persisted; a scan still in progress
        gets a freshly computed (unpersisted) snapshot every call, since there is no terminal
        revision yet to cache it against — cheap relative to the full scan payload either way,
        because it never reads file contents or issue detail, only aggregate counts.

        "Finished" here matches list_finished_scans' own definition, not just completed_at:
        an ADR 0020 Discover-only run reaches its OWN terminal state at discovered_at with
        completed_at left NULL forever (it is never assessed unless a later Assess run
        finalizes it), and per several comments elsewhere in this file that is now the common
        case, not the exception. Caching only on completed_at silently never cached those scans
        at all — always correct, just never getting the benefit the cache exists for, for most
        scans. Both are equally safe to persist under: the existing invalidation hooks
        (mark_assessed et al.) bump revision the moment anything about a Discover-only scan
        actually changes, same as they do for an assessed one.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,owner_email,revision,rubric_hash,completed_at,discovered_at "
                "FROM scan_runs WHERE id=%s",
                (scan_id,))
            run = self._db.fetchone(cur)
        if not run or run.get("owner_email") != owner:
            return None
        revision = int(run.get("revision") or 0)
        rubric_hash = run.get("rubric_hash") or ""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT snapshot,generated_at FROM overview_snapshots "
                "WHERE owner_email=%s AND scan_id=%s AND scan_revision=%s AND rubric_hash=%s",
                (owner, scan_id, revision, rubric_hash))
            cached = self._db.fetchone(cur)
        if cached:
            import json as _json
            snap = _json.loads(cached["snapshot"])
            snap["cached"] = True
            return snap
        snap = self._build_overview_snapshot(scan_id, owner, revision, rubric_hash)
        if run.get("completed_at") or run.get("discovered_at"):
            import json as _json
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "INSERT INTO overview_snapshots"
                    "(owner_email,scan_id,scan_revision,rubric_hash,snapshot,generated_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(owner_email,scan_id,scan_revision,rubric_hash) DO NOTHING",
                    (owner, scan_id, revision, rubric_hash, _json.dumps(snap), snap["generated_at"]))
        snap["cached"] = False
        return snap

    def _build_overview_snapshot(self, scan_id: str, owner: str, revision: int,
                                 rubric_hash: str) -> dict:
        """Compute the Overview snapshot from first principles — the expensive path
        get_overview_snapshot only takes on a cache miss."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,source,started_at,completed_at,discovered_at,assessed_at,published_at,"
                "files,certifiable,uncertain,error,avg_score,status,scope "
                "FROM scan_runs WHERE id=%s", (scan_id,))
            run = self._db.fetchone(cur) or {}

            self._db.execute(cur, "SELECT COUNT(*) AS n FROM scan_inventory WHERE scan_id=%s",
                             (scan_id,))
            estate_count = (self._db.fetchone(cur) or {}).get("n") or 0

            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM scan_inventory WHERE scan_id=%s "
                "AND exclusion_reason IS NOT NULL", (scan_id,))
            excluded_count = (self._db.fetchone(cur) or {}).get("n") or 0

            self._db.execute(cur,
                "SELECT status, COUNT(*) AS n FROM file_records WHERE scan_id=%s GROUP BY status",
                (scan_id,))
            by_status = {r["status"]: r["n"] for r in self._db.fetchall(cur)}
            assessed_count = sum(by_status.values())

            self._db.execute(cur,
                "SELECT engine, COUNT(*) AS n FROM file_records WHERE scan_id=%s GROUP BY engine",
                (scan_id,))
            file_type_distribution = {(r["engine"] or "unknown"): r["n"] for r in self._db.fetchall(cur)}

            self._db.execute(cur,
                "SELECT severity, COUNT(*) AS n FROM issue_records WHERE scan_id=%s GROUP BY severity",
                (scan_id,))
            severity_distribution = {(r["severity"] or "unknown"): r["n"] for r in self._db.fetchall(cur)}

            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM file_records WHERE scan_id=%s AND remediated_at IS NOT NULL",
                (scan_id,))
            remediated_count = (self._db.fetchone(cur) or {}).get("n") or 0

            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM file_records WHERE scan_id=%s AND published_at IS NOT NULL",
                (scan_id,))
            file_published_count = (self._db.fetchone(cur) or {}).get("n") or 0

            self._db.execute(cur,
                "SELECT kind, COUNT(*) AS n FROM scan_decisions WHERE scan_id=%s GROUP BY kind",
                (scan_id,))
            review_counts = {r["kind"]: r["n"] for r in self._db.fetchall(cur)}

        assessable_count = estate_count - excluded_count if estate_count else assessed_count
        unassessable_count = max(assessable_count - assessed_count, 0) if estate_count else 0
        import json as _json
        scope = run.get("scope")
        if isinstance(scope, str):
            try:
                scope = _json.loads(scope)
            except Exception:
                scope = None
        return {
            "scan_id": scan_id,
            "owner": owner,
            "scan_revision": revision,
            "rubric_hash": rubric_hash,
            "generated_at": self._now(),
            "estate": {
                "discovered": estate_count,
                "assessable": assessable_count,
            },
            "documents": {
                "assessed": assessed_count,
                "certifiable": run.get("certifiable") or 0,
                "excluded": excluded_count,
                "unassessable": unassessable_count,
            },
            "score": {
                "avg": run.get("avg_score"),
                "status_distribution": by_status,
            },
            "severity_distribution": severity_distribution,
            "file_type_distribution": file_type_distribution,
            "remediation": {
                "remediated": remediated_count,
                "published": file_published_count,
                "review": review_counts,
            },
            "freshness": {
                "started_at": run.get("started_at"),
                "discovered_at": run.get("discovered_at"),
                "assessed_at": run.get("assessed_at"),
                "completed_at": run.get("completed_at"),
                "published_at": run.get("published_at"),
            },
            "source": run.get("source"),
            "scope_summary": scope,
        }

    # ── Per-scan decision snapshots (PRD: time-travel) ──
    def get_decisions(self, scan_id: str, owner: str | None = None) -> dict:
        """All decisions for a scan as {file: {kind: value}} (kind = 'triage' | 'action').
        Owner-scoped to match the scan's per-user isolation."""
        where, params = "scan_id=%s", [scan_id]
        if owner:
            where += " AND owner_email=%s"; params.append(owner)
        with self._db.cursor() as cur:
            self._db.execute(cur, f"SELECT file,kind,value FROM scan_decisions WHERE {where}", tuple(params))
            rows = self._db.fetchall(cur)
        out: dict = {}
        for r in rows:
            out.setdefault(r["file"], {})[r["kind"]] = r["value"]
        return out

    def save_decision(self, scan_id: str, file: str, kind: str, value: str,
                      owner: str | None, when: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_decisions(scan_id,file,kind,value,owner_email,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(scan_id,file,kind) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
                (scan_id, file, kind, value, owner, when))
            self._bump_scan_revision(cur, scan_id)

    def delete_decision(self, scan_id: str, file: str, kind: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM scan_decisions WHERE scan_id=%s AND file=%s AND kind=%s",
                             (scan_id, file, kind))
            if cur.rowcount > 0:
                self._bump_scan_revision(cur, scan_id)

    # Self-heal grace: a running scan younger than this is never auto-interrupted — its
    # discover job may not have enqueued the per-file jobs yet.
    _ACTIVE_SCAN_GRACE_S = 600

    def active_scan(self, owner: str | None = None) -> dict | None:
        """The most recent in-flight scan (for reconnecting after a page reload), or None.
        Scoped to the signed-in user so reconnect never picks up someone else's scan.

        SELF-HEALS a dead scan (found live 2026-07-11): a deploy/restart can kill the
        workers after a fan-out scan's jobs finished or died but before finalize ran —
        the row stays 'running' forever, and the UI reconnects to it eternally
        ("scanning…", no way to start another). A running fan-out scan with ZERO
        outstanding jobs is dead by definition (init_scan_run rows always have job rows),
        so past a grace period it is marked 'interrupted' and no longer reported active.
        Jobs merely orphaned (still queued/running rows) are NOT touched — the stuck-job
        sweeper reclaims those and the scan genuinely resumes."""
        where, params = "status='running'", ()
        if owner:
            where += " AND owner_email=%s"; params = (owner,)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,started_at,source,files,files_done FROM scan_runs "
                f"WHERE {where} ORDER BY started_at DESC LIMIT 1", params)
            row = self._db.fetchone(cur)
            if not row:
                return None
            # job_id piggybacks on the same outstanding-jobs lookup (one round trip, not two) so
            # a page-reload reconnect can poll GET /scans/jobs/{id} for the live phase/progress
            # ticks (files_evaluated, rules_enabled, ...) the same way a fresh scan start already
            # does — without it, reconnect fell back to the coarser scan_runs-derived phase, which
            # cannot distinguish listing/metadata/classifying/lifecycle from each other.
            self._db.execute(cur,
                "SELECT COUNT(*) AS n, "
                "(SELECT id FROM jobs WHERE scan_id=%s AND status IN ('queued','running') "
                " ORDER BY created_at DESC LIMIT 1) AS job_id "
                "FROM jobs WHERE scan_id=%s AND status IN ('queued','running')",
                (row["id"], row["id"]))
            job_row = self._db.fetchone(cur) or {}
            outstanding = job_row.get("n", 0)
            row["job_id"] = job_row.get("job_id")
        if outstanding == 0:
            from datetime import datetime, timezone
            try:
                started = datetime.fromisoformat(str(row["started_at"]))
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - started).total_seconds()
            except Exception:
                age = 0
            if age > self._ACTIVE_SCAN_GRACE_S:
                with self._db.cursor() as cur:
                    self._db.execute(cur,
                        "UPDATE scan_runs SET status='interrupted', completed_at=%s "
                        "WHERE id=%s AND status='running'", (self._now(), row["id"]))
                    # Same as cancel_scan: an interrupted assess fan-out that got some documents
                    # done keeps those results reachable. A discover-only interruption has no
                    # file_records and stays unassessed.
                    self._stamp_assessed_if_ran(cur, row["id"])
                print(f"[scan] {row['id']}: marked interrupted — 'running' with no outstanding "
                      f"jobs for {int(age)}s (worker lost it, e.g. a deploy mid-scan)", flush=True)
                return None
        return row

    def set_total_folders(self, scan_id: str, count: int) -> None:
        """Record how many scan_folder jobs were emitted for this scan (ADR 0004 item 6).

        Clears the per-folder claims along with the counter they explain. The two are one fact
        and resetting only half of it is worse than resetting neither: a second fan-out over the
        same scan_id would find every folder already claimed, so `increment_completed_folders`
        would no-op for all of them and `completed_folders` would sit at 0 forever — a wedge,
        which is precisely the failure mode the claims exist to avoid causing.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET total_folders=%s, completed_folders=0 WHERE id=%s",
                (count, scan_id))
            self._db.execute(cur,
                "DELETE FROM scan_folder_completions WHERE scan_id=%s", (scan_id,))

    def increment_completed_folders(self, scan_id: str, folder_id: str | None = None) -> tuple:
        """Count one folder as done and return (completed, total) so the caller can trigger
        finalization when all folders are done (ADR 0004 item 6).

        IDEMPOTENT PER FOLDER when `folder_id` is given: calling it twice for the same folder
        advances the counter once. That is the contract callers actually need, and the plain
        `+1` this used to be could not provide it. `_scan_folder` increments near the end of its
        body, and there are at least two ordinary ways for that to happen twice for one folder:

          * the worker dies (or its lease expires) AFTER the increment and BEFORE the job row
            reaches 'done'. reclaim_stuck_jobs requeues it, a worker re-lists the same folder,
            and the increment runs a second time.
          * the `enqueue_job("scan_finalize", …)` immediately after the increment raises. The
            job fails, retries, and increments again on the next attempt.

        Neither is exotic and neither leaves a trace. The consequence is not a cosmetic overshoot
        past total_folders: with two folders and one counted twice, `done >= total` is true while
        the second folder is still being scanned, so this method's own caller enqueues
        scan_finalize — and rescue_unfinalized_scans agrees — and the run finalizes over an
        estate it has not finished reading, reporting it as complete.

        HOW. The claim is an INSERT … ON CONFLICT DO NOTHING against scan_folder_completions,
        and the counter moves only for the caller that won it. One statement decides it, so two
        workers racing on the same folder cannot both see "not yet counted"; `rowcount` after a
        DO NOTHING is 1 for the insert that happened and 0 for the one that did not, on both
        engines (asserted for SQLite in tests/test_folder_counted_once.py and for PostgreSQL in
        tests/test_pg_job_queue.py, rather than assumed from one of them).

        WITHOUT `folder_id` it is the old unguarded `+1`, because a caller that cannot name the
        folder has nothing to deduplicate ON — silently counting such a call as some arbitrary
        folder would be worse than counting it twice. Every production caller can name one and
        does; test_every_folder_counter_caller_names_its_folder holds that line, so a new caller
        that omits it fails rather than quietly reintroducing the overshoot above.

        Still returns a live (completed, total) read in the same cursor as the write, so the
        count a caller decides on is never stale. scan_finalize remains idempotent
        (mark_finalized), so a duplicate enqueue from two folders genuinely finishing at once is
        still fine — that was always true and is not what this guards.
        """
        with self._db.cursor() as cur:
            if folder_id is not None:
                self._db.execute(cur,
                    "INSERT INTO scan_folder_completions(scan_id, folder_id, counted_at) "
                    "VALUES (%s,%s,%s) ON CONFLICT(scan_id, folder_id) DO NOTHING",
                    (scan_id, folder_id, self._now()))
                if (getattr(cur, "rowcount", 0) or 0) < 1:
                    # Already counted. Report the current numbers rather than a fabricated
                    # advance — a caller re-running after a reclaim still gets a truthful
                    # (completed, total) and can still act on a genuine done >= total.
                    self._db.execute(cur,
                        "SELECT completed_folders, total_folders FROM scan_runs WHERE id=%s",
                        (scan_id,))
                    row = self._db.fetchone(cur)
                    if not row:
                        return (0, 0)
                    return (row.get("completed_folders") or 0, row.get("total_folders") or 0)
            self._db.execute(cur,
                "UPDATE scan_runs SET completed_folders=COALESCE(completed_folders,0)+1 "
                "WHERE id=%s", (scan_id,))
            self._db.execute(cur,
                "SELECT completed_folders, total_folders FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
        if not row:
            return (0, 0)
        return (row.get("completed_folders") or 0, row.get("total_folders") or 0)

    def rescue_unfinalized_scans(self) -> int:
        """Deploy-safety net (found live 2026-07-11): a revision swap can kill the worker
        AFTER the last scan_file persisted its row but BEFORE the count trigger enqueued
        scan_finalize — the scan stays 'running' forever with nothing left to do. For any
        such scan (running, zero outstanding jobs, every enqueued file persisted), enqueue
        the finalize job. Safe by construction: scan_finalize is idempotent and
        mark_finalized claims exactly-once, so a duplicate enqueue no-ops. Called from the
        stuck-job sweeper each tick. Returns how many scans were rescued.

        Also rescues per-folder scans (ADR 0004 item 6): if total_folders > 0 and
        completed_folders >= total_folders with no outstanding jobs, the scan_finalize
        job was lost and needs re-enqueueing."""
        rescued = 0
        # Original file-based rescue path (scan_file/scan_batch fan-out).
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT sr.id, sr.source FROM scan_runs sr WHERE sr.status='running' "
                "AND sr.files > 0 "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.scan_id=sr.id "
                "                AND j.status IN ('queued','running')) "
                "AND (SELECT COUNT(*) FROM file_records fr WHERE fr.scan_id=sr.id) >= sr.files")
            rows = self._db.fetchall(cur)
        for r in rows:
            self.enqueue_job("scan_finalize",
                             {"scan_id": r["id"], "source": r.get("source") or "drive"},
                             scan_id=r["id"])
        rescued += len(rows)
        # Per-folder rescue path (ADR 0004 item 6): all scan_folder jobs finished but the
        # finalize job was not enqueued (e.g. worker lost the last scan_folder before it
        # could enqueue finalize, then was reclaimed — but completed_folders was already
        # incremented). total_folders > 0 distinguishes per-folder scans from file-based ones.
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT sr.id, sr.source FROM scan_runs sr WHERE sr.status='running' "
                "AND sr.total_folders > 0 "
                "AND sr.completed_folders >= sr.total_folders "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.scan_id=sr.id "
                "                AND j.status IN ('queued','running'))")
            folder_rows = self._db.fetchall(cur)
        for r in folder_rows:
            self.enqueue_job("scan_finalize",
                             {"scan_id": r["id"], "source": r.get("source") or "drive"},
                             scan_id=r["id"])
        rescued += len(folder_rows)
        return rescued

    def cancel_scan(self, sid: str, owner: str | None = None) -> bool:
        """Stop an in-flight fan-out scan: kill its outstanding jobs and close the run as
        'cancelled'. Owner-scoped like get_scan. Files already analysed keep their records —
        history stays honest about what ran before the stop. False when the scan doesn't
        exist, belongs to someone else, or is neither 'running' nor has an outstanding job
        (nothing to cancel).

        Eligibility is `scan_runs.status == 'running'` OR an outstanding `jobs` row — the job
        check is additive, not a replacement, so every caller/fixture that creates a scan at
        status='running' with no jobs row keeps working exactly as before. It closes a real gap
        found live 2026-08-27: a fan-out discover run's `scan_runs.status` can read 'discovered'
        (the ADR 0020 terminal value for that run type) while its job is still genuinely
        executing add_inventory's save phase, because that status is written once at listing
        time, not gated on the save actually finishing. A scan stuck in exactly that gap matched
        neither the old status='running' check here nor cancel_queued_job's status='queued'
        check, so a job wedged mid-save had NO path to being cancelled short of the 2-hour
        stale-guard reclaim (see acquire_discovery_guard) — it held active_discovery_guard the
        whole time, rejecting every subsequent scan attempt for that source. The `jobs` table's
        own status is the one place that distinguishes genuinely-still-running from
        genuinely-done regardless of what scan_runs says."""
        return self._end_running_scan(sid, owner=owner, terminal_status="cancelled")

    def supersede_scan(self, sid: str, owner: str | None = None) -> bool:
        """Stop an in-flight scan because a NEW scan for the same owner is taking its place
        (the single-flight guard in routes/scans.py) — same effect as cancel_scan (jobs killed,
        partial file_records kept), but a DIFFERENT terminal status.

        Found live 2026-08-26: reusing cancel_scan's 'cancelled' status here made the superseded
        run stamp completed_at=now() and sort as the NEWEST row in list_scans() (ORDER BY
        completed_at DESC) — ahead of the real, complete scan it replaced. Since a scan barely
        underway has files=NULL (filled to 0 for display), the estate's "latest scan" silently
        read as a 0-document collapse — exactly the fingerprint scripts/monitor.py's collapse
        check exists to catch, and it did: production's monitor failed with "newest has 0
        documents but a recent scan had 999" within minutes of a real supersede.

        'superseded' is a status list_scans()/list_scans_admin()/list_scans_including_discovered()/
        previous_run_for_source() all now exclude, so an auto-superseded attempt never displaces a
        real result — unlike an explicit user Stop ('cancelled'), which is meant to stay visible
        in scan history exactly as it does today."""
        return self._end_running_scan(sid, owner=owner, terminal_status="superseded")

    def _end_running_scan(self, sid: str, *, owner: str | None, terminal_status: str) -> bool:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT owner_email, status FROM scan_runs WHERE id=%s", (sid,))
            row = self._db.fetchone(cur)
            if not row or (owner is not None and row.get("owner_email") != owner):
                return False
            # Eligibility is status=='running' OR an outstanding job — purely additive over the
            # old status-only check, never narrower: a scan created directly at status='running'
            # with no jobs row (every existing caller and test fixture) must keep working exactly
            # as before. The job check is what closes the actual gap — see cancel_scan's docstring.
            self._db.execute(cur,
                "SELECT COUNT(*) AS cnt FROM jobs WHERE scan_id=%s AND status IN ('queued','running')",
                (sid,))
            has_active_job = (self._db.fetchone(cur) or {}).get("cnt", 0) > 0
            if row.get("status") != "running" and not has_active_job:
                return False
            # cancel_requested_at, not just status='dead'. Marking the row terminal stops the
            # queue handing this job out again; it does NOT stop a worker that has already
            # CLAIMED it, because worker.check_cancel() reads exactly one field and this was not
            # setting it. finalize_scan_run's docstring names the cost: "The window is not small.
            # It is the whole remaining duration of the superseded run, because nothing interrupts
            # it" — a superseded discovery kept listing Drive, kept holding pool connections, and
            # kept competing with the run that replaced it.
            #
            # Safe to set both. The worker's cancellation path calls mark_job_cancelled(), whose
            # UPDATE is guarded `status NOT IN ('done','dead','cancelled')`, so against a job this
            # already marked 'dead' that write no-ops and the job KEEPS its 'dead' status —
            # dead-letter accounting is unchanged. COALESCE preserves an EARLIER explicit
            # cancellation stamp: when a user pressed Stop first, that timestamp is evidence of
            # when they asked, and superseding afterwards must not rewrite it.
            self._db.execute(cur,
                "UPDATE jobs SET status='dead', updated_at=%s, "
                "cancel_requested_at=COALESCE(cancel_requested_at, %s) "
                "WHERE scan_id=%s AND status IN ('queued','running')",
                (self._now(), self._now(), sid))
            # No status guard on this UPDATE: the jobs check above already established there was
            # genuinely something to stop, and gating on scan_runs.status=='running' here would
            # silently no-op the transition for the exact drifted-status case this fix exists for.
            # That drift is also why this can reach a scan whose status was NOT 'running' (a
            # stray active job left over on an already-terminal, possibly already-cached run) —
            # so completed_at can change here even when _stamp_assessed_if_ran below is a no-op
            # (assessed_at already set). Bump unconditionally rather than piggyback on that call:
            # a cached overview_snapshots row's freshness.completed_at must never silently
            # disagree with the value this UPDATE just wrote.
            self._db.execute(cur,
                "UPDATE scan_runs SET status=%s, completed_at=%s WHERE id=%s",
                (terminal_status, self._now(), sid))
            self._bump_scan_revision(cur, sid)
            # A cancelled/superseded ASSESS fan-out has already assessed some documents (their
            # file_records exist); stamp assessed_at so the run's PARTIAL results are reachable —
            # the results views gate on assessed_at, and without this a stopped run showed nothing
            # at all. Only when something ran: a discover-only stop has no file_records and stays
            # unassessed, which is correct — it is not a partial assessment. COALESCE so a run that
            # had already finalized keeps its original stamp rather than being back-dated to the stop.
            self._stamp_assessed_if_ran(cur, sid)
        return True

    def pause_scan(self, sid: str, owner: str | None = None) -> bool:
        """ADR 0038 step 1 of 2 (step 2 is handlers.set_scan_paused_marker) — CAS
        status: running -> paused. Owner-scoped like cancel_scan. False when the scan doesn't
        exist, belongs to someone else, or isn't currently 'running' (a finished, cancelled, or
        already-paused run cannot be paused again).

        Deliberately NOT _end_running_scan: that helper kills outstanding jobs and stamps
        completed_at, which is exactly cancel's terminal behaviour and exactly what pause must
        NOT do. A paused run's jobs are left alone — one already claimed by a worker runs to
        completion and persists its row (cooperative, never a mid-file kill); it is the pause
        marker checked inside _scan_batch/_scan_file, not a killed job, that stops anything NEW
        from being dispatched. completed_at stays unset so the run reads as legitimately open.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT owner_email, status FROM scan_runs WHERE id=%s", (sid,))
            row = self._db.fetchone(cur)
            if not row or (owner is not None and row.get("owner_email") != owner):
                return False
            if row.get("status") != "running":
                return False
            self._db.execute(cur, "UPDATE scan_runs SET status='paused' WHERE id=%s AND status='running'",
                             (sid,))
            return (getattr(cur, "rowcount", 0) or 0) > 0

    def resume_scan(self, sid: str, owner: str | None = None) -> bool:
        """ADR 0038 step 1 of 2 (step 2 is handlers.clear_scan_paused_marker, and the caller
        re-dispatching undone_scan_items through _enqueue_analysis — the actual re-work is the
        route layer's job, not this CAS). False when the scan doesn't exist, belongs to someone
        else, or isn't currently 'paused'."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT owner_email, status FROM scan_runs WHERE id=%s", (sid,))
            row = self._db.fetchone(cur)
            if not row or (owner is not None and row.get("owner_email") != owner):
                return False
            if row.get("status") != "paused":
                return False
            self._db.execute(cur, "UPDATE scan_runs SET status='running' WHERE id=%s AND status='paused'",
                             (sid,))
            return (getattr(cur, "rowcount", 0) or 0) > 0

    def undone_scan_items(self, scan_id: str) -> list[dict]:
        """The run's in-scope files with no current file_records row (ADR 0038 §3) — what
        resume re-dispatches through _enqueue_analysis. Shaped like list_inventory's rows so a
        caller can pass them straight through unchanged; idempotent upsert on the receiving end
        means this query may be (and is) conservative rather than exact under concurrent writes.

        Same "done" definition as count_files_done: a row's mere EXISTENCE in file_records for
        this scan_id, not any freshness check on it — resume never re-analyses a file that
        already has a persisted result, current or not, matching what finalize already trusts.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT {self._INV_COLS} FROM scan_inventory si WHERE si.scan_id=%s "
                "AND NOT EXISTS (SELECT 1 FROM file_records fr "
                "                WHERE fr.scan_id=si.scan_id AND fr.file=si.file) "
                "ORDER BY si.file", (scan_id,))
            return self._db.fetchall(cur)

    def acknowledge_scan(self, scan_id: str, actor: str | None, owner: str | None = None) -> bool:
        """Record that the operator has reviewed lifecycle recommendations and approved this
        discovery snapshot for handoff to Assess (PRD §EX-10). Idempotent — re-acknowledging
        overwrites the prior stamp, allowing corrections. Returns False when scan is not found
        or owner mismatch."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT owner_email FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
            if not row:
                return False
            if owner is not None and row.get("owner_email") != owner:
                return False
            self._db.execute(cur,
                "UPDATE scan_runs SET acknowledged=TRUE, acknowledged_at=%s, acknowledged_by=%s "
                "WHERE id=%s",
                (self._now(), actor, scan_id))
        return True

    def unacknowledge_scan(self, scan_id: str, owner: str | None = None) -> bool:
        """Withdraw a prior acknowledgement (e.g. if lifecycle rules changed after approval)."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT owner_email FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
            if not row:
                return False
            if owner is not None and row.get("owner_email") != owner:
                return False
            self._db.execute(cur,
                "UPDATE scan_runs SET acknowledged=FALSE, acknowledged_at=NULL, acknowledged_by=NULL "
                "WHERE id=%s", (scan_id,))
        return True

    def cancel_queued_job(self, sid: str) -> bool:
        """Cancel a scan that is still `queued` and has not yet been claimed by a worker — the
        gap `cancel_scan` cannot cover, because the worker only advances `scan_runs.status`
        once it claims the job. Marks the `jobs` row `status='dead'` directly, and stamps the
        pre-created `scan_runs` row 'cancelled' so GET /scans/{id} reflects the terminal state.

        No owner check: `sid` is an unguessable token used as the credential for this operation,
        consistent with how the non-durable job-poll path authenticates today.

        Returns False once a worker HAS claimed it (status moved to 'running' or beyond) — at
        that point `cancel_scan` is the right call, and the route tries both in order."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='dead', updated_at=%s WHERE scan_id=%s AND status='queued'",
                (self._now(), sid))
            cancelled = cur.rowcount > 0
        if cancelled:
            # The pre-created scan_runs row (status='queued') now has no job to run it.
            # Mark it cancelled so callers see a terminal state rather than stale 'queued'.
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "UPDATE scan_runs SET status='cancelled', completed_at=%s "
                    "WHERE id=%s AND status='queued'",
                    (self._now(), sid))
        return cancelled

    def _stamp_assessed_if_ran(self, cur, sid: str) -> None:
        """Stamp assessed_at on a non-finalized run that nonetheless assessed ≥1 document, so its
        partial results reach the results views. No-op when nothing ran or a stamp already exists."""
        self._db.execute(cur,
            "UPDATE scan_runs SET assessed_at=COALESCE(assessed_at, %s) "
            "WHERE id=%s AND assessed_at IS NULL "
            "AND EXISTS (SELECT 1 FROM file_records WHERE scan_id=%s)",
            (self._now(), sid, sid))
        if cur.rowcount > 0:
            self._bump_scan_revision(cur, sid)

    # The counters finalize_scan_run writes, as a single SELECT so a derived-at-read value and
    # a stored one are computed from one definition and cannot drift apart.
    _AGG_SELECT = (
        "SELECT COALESCE(SUM(compliant),0) AS certifiable, "
        "COUNT(CASE WHEN status='uncertain' THEN 1 END) AS uncertain, "
        "COUNT(CASE WHEN status='error' THEN 1 END) AS error, "
        "ROUND(AVG(score)) AS avg_score "
        "FROM file_records WHERE scan_id=%s"
    )

    def _reconcile_shadowed(self, cur, run: dict) -> bool:
        """Re-count the run's summary over the documents get_scan actually hands out.

        get_scan drops ACP's OWN output when it shadows the source document it was made from
        (shadowed_acp_outputs) — an artifact is not a document in the estate. The scan_runs
        counters were written by finalize_scan_run straight over file_records, which still holds
        that artifact, so the summary and the file list described two different populations.

        On 2026-07-30 that put both numbers on the Overview at once. A whole-Drive scan listed 8
        raw files, kept 4, and one of the 4 was a remediated .docx ACP had written back to Drive
        under the source's own name. The screen then read:

            documents 4 · certifiable 3 · audit-ready 75%
            [status donut] 3 documents — 2 certifiable, 1 issues
            Scope: 3 of 4 documents have been analysed — the rest were discovered but not yet
                   assessed. Findings, certifiable and audit-ready describe the analysed
                   documents only.

        Three ways wrong. The tile and the donut disagree about how many documents there are and
        how many are certifiable; the scope line explains the gap with a reason that is false (the
        4th was analysed — score 92 — it is simply not a source document); and its promise that
        certifiable describes the analysed documents only is false too, because 3 counts the
        artifact and the donut's 2 does not. Discover, reading the same file list, said 3.

        The artifact is compliant=1 and scored 92 — remediated output usually is — so every one of
        those numbers erred in the flattering direction.

        Returns True when it re-counted (so the NULL-fill below can be skipped: these counters are
        now derived and complete). Returns False for the ordinary scan with nothing shadowed,
        which is every scan that has never had a fix written back into its own estate.
        """
        # Cheap gate first. list_scans calls this per row and the SPA polls it, so a 258-file
        # estate must not pay a full file_records read per scan per poll to be told nothing is
        # shadowed. Nothing can shadow without a stamp, and most scans have none.
        self._db.execute(cur,
            "SELECT 1 FROM file_records WHERE scan_id=%s AND acp_stamped IS NOT NULL LIMIT 1",
            (run["id"],))
        if self._db.fetchone(cur) is None:
            return False
        self._db.execute(cur,
            "SELECT file,status,score,compliant,acp_stamped FROM file_records WHERE scan_id=%s",
            (run["id"],))
        rows = self._db.fetchall(cur)
        shadowed = shadowed_acp_outputs(rows)
        if not shadowed:
            return False
        visible = [r for r in rows if r["file"] not in shadowed]
        scored = [r["score"] for r in visible if r.get("score") is not None]
        run["files"] = len(visible)
        run["certifiable"] = sum(1 for r in visible if r.get("compliant"))
        run["uncertain"] = sum(1 for r in visible if r.get("status") == "uncertain")
        run["error"] = sum(1 for r in visible if r.get("status") == "error")
        # Unscored stays NULL rather than 0 — the UI renders '—' for "nobody measured this",
        # and a 0 here would be a failing grade nobody awarded.
        run["avg_score"] = round(sum(scored) / len(scored)) if scored else None
        if run.get("files_done") is not None:
            run["files_done"] = min(run["files_done"], len(visible))
        return True

    def _fill_run_aggregate(self, cur, run: dict) -> dict:
        """Never hand out a NULL counter — derive it the way finalize would have.

        init_scan_run creates the scan_runs row with certifiable/uncertain/error/avg_score
        unset; only finalize_scan_run fills them. Three paths close a scan WITHOUT finalizing —
        cancel_scan ('cancelled'), supersede_scan ('superseded' — killed by the single-flight
        guard to make way for a newer scan) and the lost-worker sweeper ('interrupted') — and all
        three stamp completed_at. A 'cancelled'/'interrupted' scan then passes list_scans'
        `completed_at IS NOT NULL` filter and loads into the dashboard with those counters still
        NULL; 'superseded' is additionally excluded from list_scans (see supersede_scan) so it
        never ranks as the estate's latest scan, but is filled the same way here for the rarer
        direct-lookup case (get_scan by its own id).

        NULL is not zero, but every consumer downstream treats it as zero silently: JSON `null`
        reaches JavaScript, `null / files` is 0 and `files - null - null - null` is `files`. On
        2026-07-29 that rendered a 258-document scan as a BLANK certifiable tile, a confident
        "0% audit-ready", and a status donut reading "issues 258" — beside a severity panel
        correctly reporting "No open findings." Not one of those numbers came from a finding.

        So compute the counters from the file_records that DO exist. A cancelled scan then
        reports what actually ran rather than an artefact of arithmetic on null. avg_score is
        left NULL when nothing was scored: that one is genuinely unknown, and the UI already
        renders '—' for it instead of inventing a 0.

        Also the one place `scope` is decoded from its stored JSON, so every reader of a scan
        (get_scan and list_scans both funnel through here) gets an object rather than a string —
        and so a row written before the column existed reads as None, never as a fabricated
        default. It runs BEFORE the early return below, which the counters get to skip.

        And the one place the counters are reconciled with the file list the SAME scan hands out
        — see _reconcile_shadowed below.
        """
        raw_scope = run.get("scope")
        if isinstance(raw_scope, str):
            import json as _json
            try:
                run["scope"] = _json.loads(raw_scope)
            except Exception:
                run["scope"] = None      # unreadable is unknown, not "whole Drive"
        raw_checkpoint = run.get("live_checkpoint")
        if isinstance(raw_checkpoint, str):
            import json as _json
            try:
                run["live_checkpoint"] = _json.loads(raw_checkpoint)
            except Exception:
                run["live_checkpoint"] = None
        if self._reconcile_shadowed(cur, run):
            return run
        if all(run.get(k) is not None for k in ("certifiable", "uncertain", "error")):
            return run
        self._db.execute(cur, self._AGG_SELECT, (run["id"],))
        agg = self._db.fetchone(cur) or {}
        for k in ("certifiable", "uncertain", "error", "avg_score"):
            if run.get(k) is None:
                run[k] = agg.get(k)
        # SUM/COUNT over zero rows still yields 0 here, so these three are always numbers now.
        for k in ("certifiable", "uncertain", "error"):
            run[k] = int(run[k] or 0)
        return run

    def get_scan_head(self, sid: str, owner: str | None = None) -> dict | None:
        """Just {id, status, revision} for one scan — the cheap identity+status lookup
        GET /workspace/bootstrap needs alongside the (separately cached) Overview
        snapshot, without paying get_scan's file_records/issue_records join. Owner-scoped
        like every other per-scan read; None for a missing or foreign scan."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT id,status,revision,owner_email FROM scan_runs WHERE id=%s",
                             (sid,))
            run = self._db.fetchone(cur)
        if not run or (owner is not None and run.get("owner_email") != owner):
            return None
        return {"id": run["id"], "status": run.get("status"), "revision": int(run.get("revision") or 0)}

    def get_scan(self, sid: str, owner: str | None = None) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM scan_runs WHERE id=%s", (sid,))
            run = self._db.fetchone(cur)
            if not run:
                return None
            # Per-user isolation: a user can only read their own scan (legacy/None owner
            # scans are not shown to anyone once isolation is on).
            if owner is not None and run.get("owner_email") != owner:
                return None
            run = self._fill_run_aggregate(cur, run)
            self._db.execute(cur,
                "SELECT fr.file,fr.engine,fr.status,fr.score,fr.compliant,fr.skipped_rules,"
                "fr.remediated_at,fr.drive_write_url,fr.acp_stamped,fr.published_at,"
                "fr.size_kb,fr.pages,fr.sheets,fr.drive_file_id,fr.source_modified,"
                "si.owner,si.parent_folder "
                "FROM file_records fr "
                "LEFT JOIN scan_inventory si ON si.scan_id=fr.scan_id AND si.file=fr.file "
                "WHERE fr.scan_id=%s ORDER BY fr.file", (sid,))
            files = self._db.fetchall(cur)
            # ADR 0020 — a Discover-only scan (analysis deferred to Assess) has an inventory but no
            # assessed file_records yet. Surface the inventory as 'discovered' rows so Discover shows
            # the estate; every score/finding field is null/empty (nothing was opened). Once Assess
            # writes real file_records, those win and this fallback goes quiet.
            if not files:
                self._db.execute(cur,
                    "SELECT file,doc_class,size_kb,drive_file_id,owner,parent_folder "
                    "FROM scan_inventory WHERE scan_id=%s ORDER BY file", (sid,))
                inv = self._db.fetchall(cur)
                files = [{"file": r["file"], "engine": r.get("doc_class") or "inventory",
                          "status": "discovered", "score": None, "compliant": 0,
                          "skipped_rules": 0, "remediated_at": None, "drive_write_url": None,
                          "acp_stamped": None, "published_at": None, "size_kb": r.get("size_kb"),
                          "pages": None, "sheets": None, "drive_file_id": r.get("drive_file_id"),
                          "source_modified": None, "owner": r.get("owner"),
                          "parent_folder": r.get("parent_folder")}
                         for r in inv]
            # Drop ACP's own remediated copies when they shadow the source document they were
            # made from. They are artifacts, not documents in the estate: counting them
            # inflated "total scanned", invented a "duplicate", and made a scan that
            # remediated nothing report "remediated ✓ 1". Rows are kept in the table — this
            # filters the read, it does not delete evidence.
            shadowed = shadowed_acp_outputs(files)
            if shadowed:
                if sid not in _shadow_logged:      # once per scan, not once per poll
                    _shadow_logged.add(sid)
                    print(f"[scan] get_scan({sid}): hiding {len(shadowed)} ACP-generated file(s) "
                          f"shadowing their source: {sorted(shadowed)}", flush=True)
                files = [f for f in files if f["file"] not in shadowed]
            # file_records has no per-file source column (every file in one scan shares the
            # scan's single source) — derive the friendly sourceName here, at the single read
            # path, so every consumer (Overview/Dashboard/FileDrawer/Monitor/Publish/...) gets
            # it without a schema change. Was previously unset on real scans (SIM-only field),
            # which silently blanked any "by source" chart.
            src_label = _SOURCE_LABEL.get(run.get("source"), run.get("source"))
            # ONE query for every file's issues, not one per file — this loop used to issue a
            # separate SELECT per row, which is thousands of sequential round trips on a real
            # estate (exactly the add_inventory bug #880 already fixed on the write side, still
            # live here on the read side: found live 2026-08-30, a ~6,916-file scan's Discover
            # tab stuck on "Loading your inventory…" indefinitely — getScan() has no client-side
            # timeout, so a slow response here just hangs the tab forever rather than erroring).
            # Grouped in Python instead, from one round trip.
            self._db.execute(cur,
                "SELECT file,rule_id,wcag,severity,detail,page,location FROM issue_records WHERE scan_id=%s",
                (sid,))
            issues_by_file: dict[str, list] = {}
            for row in self._db.fetchall(cur):
                issues_by_file.setdefault(row["file"], []).append(
                    {"rule_id": row["rule_id"], "wcag": row["wcag"], "severity": row["severity"],
                     "detail": row["detail"], "page": row["page"], "location": row["location"]})
            for f in files:
                f["sourceName"] = src_label
                f["issues"] = issues_by_file.get(f["file"], [])
            # Phase 3a — project the scan's FROZEN criterion×format scope onto the run payload so
            # the SPA can render a scope chip (3b) from `run.scan_scope` without re-reading and
            # re-decoding the scope JSON itself. Additive and non-breaking: None when the scan
            # predates the field or was genuinely unrestricted. `run["scope"]` is already decoded
            # to a dict (or None) by _fill_run_aggregate above.
            _scope = run.get("scope")
            run["scan_scope"] = _scope.get("scan_scope") if isinstance(_scope, dict) else None
            # State 4 (partial run): the documents the scope SELECTED but the run never assessed.
            # They are not in the files array above — get_scan returns only what ran — so the results
            # screen cannot name "the 13 not started" without this. The per-file jobs are the
            # authoritative selected set (one 'scan_file' per document, 'scan_batch' bundles several);
            # a not-started job was marked 'dead' by cancel_scan and its payload survives (only 'done'
            # jobs are ever purged), so subtracting the analysed files from the enqueued files gives
            # exactly what was left. Additive field, so no other reader of the files array is touched,
            # and computed ONLY for a non-finalized run — a completed run has nothing outstanding.
            if run.get("status") in ("cancelled", "interrupted", "superseded"):
                import json as _json
                analysed = {f["file"] for f in files}
                enqueued = []
                self._db.execute(cur,
                    "SELECT payload FROM jobs WHERE scan_id=%s AND type IN ('scan_file','scan_batch')", (sid,))
                for jr in self._db.fetchall(cur):
                    try:
                        p = _json.loads(jr.get("payload") or "{}")
                    except Exception:
                        continue
                    if p.get("file"):
                        enqueued.append(p["file"])
                    for it in (p.get("items") or []):
                        if isinstance(it, dict) and it.get("file"):
                            enqueued.append(it["file"])
                # de-dup preserving order; drop what actually ran. dict.fromkeys is the ordered set.
                not_started = [f for f in dict.fromkeys(enqueued) if f not in analysed]
                run["not_assessed"] = {
                    "count": len(not_started),
                    # Capped so a huge stopped run cannot bloat the payload; the count is exact.
                    "documents": [{"file": f, "name": f} for f in not_started[:500]],
                    # assessed + not_started, robust even if some 'done' jobs were already purged.
                    "selected": len(analysed) + len(not_started),
                }
            # WHEN this run's inventory was taken. The column is stamped at discovery for every
            # run from here on; for a run discovered BEFORE it existed it is NULL, and the newest
            # per-file `scan_inventory.discovered_at` is the honest derivation — real persisted
            # data, not a clock read at request time. Filled here so the Discover header can date
            # its counts from `GET /scans/{id}` alone, without first paging the whole inventory.
            # Still None when neither exists, which the caller must render as "not recorded"
            # rather than as a fresh scan.
            if not run.get("discovered_at"):
                self._db.execute(cur,
                    "SELECT MAX(discovered_at) AS at FROM scan_inventory WHERE scan_id=%s", (sid,))
                run["discovered_at"] = (self._db.fetchone(cur) or {}).get("at")
            return {"run": run, "files": files}

    def get_scan_scope(self, scan_id: str) -> dict[str, frozenset[str]] | None:
        """The criterion→formats scope this scan was FROZEN to at scan-start, rehydrated to
        {sc: frozenset(fmts)}, or None for NO RESTRICTION.

        Phase 3a. `scan_runs.scope["scan_scope"]` is recorded once — at discover (init_scan_run)
        or save (save_scan) — from the operator's scope in force THEN, and never mutated after.
        Remediation and the numeric score read THIS instead of the live global
        `active_scope(store)`, so changing the operator's scope later can no longer alter what an
        old scan remediates or scores while its Assess counts stay frozen (the Remediate/Assess
        contradiction). Assess/coverage were already frozen — they count stored rule traces.

        None means NO RESTRICTION, EVERYWHERE (the remediation predicate reads None as "all
        in-scope", the score and traces as "unrestricted"). A legacy scan predating the field
        has nothing recorded and so reads as None — never as the live global, which would
        re-introduce the very drift 3a removes.

        Mirrors get_scan_diff's `_scan_scope` for the decode shape, but deliberately NOT wrapped
        in a blanket except that returns "everything": a genuine read/parse error must surface,
        not silently widen a scoped scan to the whole criteria set (the fail-loud discipline of
        _scope_for_listing / _scoped_for_scoring). None is returned ONLY when the row or the
        `scan_scope` key is genuinely absent or empty.
        """
        cached = self._scope_cache.get(scan_id, _SCOPE_ABSENT)
        if cached is not _SCOPE_ABSENT:
            return cached
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
        if not row:
            self._scope_cache[scan_id] = None
            return None
        raw = row.get("scope")
        if not raw:
            self._scope_cache[scan_id] = None
            return None
        # NOT guarded: a stored-but-corrupt scope raises here rather than reading as unrestricted.
        data = _json.loads(raw) if isinstance(raw, str) else raw
        result = scope_from_json((data or {}).get("scan_scope"))
        self._scope_cache[scan_id] = result
        return result

    def get_scan_scope_rules(self, scan_id: str) -> list[dict]:
        """The per-file WCAG scope rules FROZEN into this scan at discover (PRD §4.4 / C4), or []
        for a scan with none (including legacy scans predating the field). Read by the score and
        trace paths so both resolve every file against the same rule set — the frozen-scope
        discipline get_scan_scope follows, applied to C4's rule layer."""
        cached = self._scope_rules_cache.get(scan_id, _SCOPE_ABSENT)
        if cached is not _SCOPE_ABSENT:
            return cached
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
        if not row:
            self._scope_rules_cache[scan_id] = []
            return []
        raw = row.get("scope")
        if not raw:
            self._scope_rules_cache[scan_id] = []
            return []
        data = _json.loads(raw) if isinstance(raw, str) else raw
        rules = (data or {}).get("scope_rules") or []
        result = rules if isinstance(rules, list) else []
        self._scope_rules_cache[scan_id] = result
        return result

    def _inventory_attrs(self, scan_id: str, file: str) -> dict:
        """The file's path / owner / parent_folder from its scan_inventory row — the attributes a
        per-file scope rule matches on (department is not on scan_inventory today, so
        department-selector rules do not resolve at this layer; folder/owner do).

        Lazy bulk-load: first call for a given scan_id fetches ALL inventory rows for the
        scan at once and caches them by filename, so subsequent calls (other files in the same
        scan batch) return from memory rather than issuing another point-SELECT."""
        if scan_id not in self._inventory_cache:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "SELECT file, path, owner, parent_folder FROM scan_inventory WHERE scan_id=%s",
                    (scan_id,))
                rows = self._db.fetchall(cur)
            self._inventory_cache[scan_id] = {r["file"]: r for r in rows}
        return self._inventory_cache[scan_id].get(file, {})

    def scope_for_file(self, scan_id: str, file: str, global_scope):
        """This file's effective criterion×format scope: `global_scope` narrowed to the WCAG
        code-set resolved from the scan's FROZEN per-file scope rules (PRD §4.4 / C4), or
        `global_scope` unchanged when no rule targets the file (byte-for-byte pre-C4 behaviour).
        Both the score and trace paths call this so a file's score and traces read one scope."""
        rules = self.get_scan_scope_rules(scan_id)
        if not rules:
            return global_scope
        from assessment_policy import resolve_file_scope
        return resolve_file_scope(self._inventory_attrs(scan_id, file), global_scope, rules)

    def get_scan_diff(self, cur_id: str, prev_id: str, owner: str | None = None) -> dict | None:
        """Diff two scans (ADR 0009) → per-file score regressions / improvements + the WCAG
        criteria that flipped pass→fail. Owner-scoped: both scans must belong to the caller.

        SCOPE-AWARE, BECAUSE A SCORE IS ONLY MEANINGFUL AGAINST THE CRITERIA IT WAS COMPUTED
        OVER. `scan_scope` decides which findings reach `Rubric.assess`, so the same unchanged
        document scores 60 under a wide scope and 75 with one criterion in scope. Diffing those
        two scans reported every document as IMPROVED — an operator who narrowed the scope was
        congratulated on progress that did not happen, which is worse than a missing feature
        because it is believed.

        The same change also emptied the estate: files whose format the new scope excludes were
        never read, so they are absent from `file_records` and landed in `removed`, reading as
        "45 documents disappeared".

        Both are handled by comparing what each scan actually measured:

          - per file, the criteria in scope FOR ITS FORMAT. Compared per format, not globally,
            so a scope change that only touched PDF criteria leaves every .docx delta valid —
            treating any scope change as poisoning the whole diff would throw away the
            comparison an operator most often wants.
          - files missing because their format was out of scope are reported as `not_read`,
            never as `removed`. "We did not look" and "it is gone" are different facts and only
            one of them is about the estate.

        Scans predating the `scan_scope` field have None recorded, which is treated as "no
        restriction" — the same reading `formats_in_scope` gives, and the only one available.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT id, owner_email, completed_at, scope FROM scan_runs WHERE id IN (%s,%s)", (cur_id, prev_id))
            runs = {r["id"]: r for r in self._db.fetchall(cur)}
            if cur_id not in runs or prev_id not in runs:
                return None
            if owner is not None and (runs[cur_id].get("owner_email") != owner or runs[prev_id].get("owner_email") != owner):
                return None

            def _files(sid):
                self._db.execute(cur, "SELECT file, score FROM file_records WHERE scan_id=%s", (sid,))
                return {r["file"]: r.get("score") for r in self._db.fetchall(cur)}

            def _traces(sid):
                self._db.execute(cur, "SELECT file, rule_id, plain_name, outcome FROM scan_rule_traces WHERE scan_id=%s", (sid,))
                out: dict = {}
                for r in self._db.fetchall(cur):
                    out.setdefault(r["file"], {})[r["rule_id"]] = (str(r["outcome"]).upper(), r["plain_name"])
                return out

            def _severities(sid):
                # scan_rule_traces has no severity column (it's an SC-level rollup); the
                # real per-finding severity lives on issue_records, keyed by the raw
                # ruleId. Roll up to (file, SC) → worst severity, since a "broke" entry
                # is reported at the SC level and a SC can carry findings of mixed
                # severity (rare, but the regression card should show the worst case).
                self._db.execute(cur, "SELECT file, wcag, severity FROM issue_records WHERE scan_id=%s", (sid,))
                out: dict = {}
                for r in self._db.fetchall(cur):
                    sc = _extract_sc(r.get("wcag", ""))
                    if not sc:
                        continue
                    cell = out.setdefault(r["file"], {})
                    sev = r.get("severity")
                    if sev and _ISSUE_SEV_RANK.get(sev, 0) > _ISSUE_SEV_RANK.get(cell.get(sc), 0):
                        cell[sc] = sev
                return out

            fp, fc = _files(prev_id), _files(cur_id)
            tp, tc = _traces(prev_id), _traces(cur_id)
            sevs = _severities(cur_id)

        def _scan_scope(sid):
            import json as _json
            raw = runs[sid].get("scope")
            if not raw:
                return None
            try:
                return (_json.loads(raw) if isinstance(raw, str) else raw).get("scan_scope")
            except (ValueError, AttributeError):
                return None

        prev_scope, cur_scope = _scan_scope(prev_id), _scan_scope(cur_id)
        scope_changed = prev_scope != cur_scope

        def _comparable(filename: str) -> bool:
            """Were this file's two scores computed over the same criteria?

            Per FORMAT, deliberately. A global "did the scope change" test would discard every
            .docx delta because somebody stopped scanning PDFs, and those deltas are real.
            """
            if not scope_changed:
                return True
            fmt = _file_format(filename)
            return (criteria_for_format(prev_scope, fmt)
                    == criteria_for_format(cur_scope, fmt))

        regressed, improved, new, removed, incomparable = [], [], [], [], []
        for f, cs in fc.items():
            if f not in fp:
                new.append({"file": f, "score": cs}); continue
            ps = fp[f]
            if ps is None or cs is None:
                continue
            if not _comparable(f):
                # Reported, not dropped. A file that silently vanishes from a diff is the same
                # failure as a count without its boundary: the reader concludes nothing changed.
                incomparable.append({"file": f, "prev": ps, "cur": cs,
                                     "reason": "assessed against a different set of criteria"})
                continue
            delta = cs - ps
            if delta < 0:
                broke = [{"sc": rid, "name": name, "severity": sevs.get(f, {}).get(rid)}
                         for rid, (outcome, name) in tc.get(f, {}).items()
                         if outcome == "FAIL" and tp.get(f, {}).get(rid, ("",))[0] == "PASS"]
                broke.sort(key=lambda b: -_ISSUE_SEV_RANK.get(b["severity"], 0))
                regressed.append({"file": f, "prev": ps, "cur": cs, "delta": delta, "broke": broke[:6]})
            elif delta > 0:
                improved.append({"file": f, "prev": ps, "cur": cs, "delta": delta})
        # A file absent from the current scan is either GONE from the estate or simply NOT READ
        # because the current scope excludes its format. Those are different facts and only the
        # first is about the estate; conflating them turns "we assess only Word documents" into
        # "45 documents disappeared", which is a support ticket rather than a diff.
        not_read = []
        removed = []
        for f in fp:
            if f in fc:
                continue
            row = {"file": f, "score": fp[f]}
            if cur_scope is not None and not file_in_scope(f, {k: frozenset(v) for k, v in cur_scope.items()}):
                not_read.append(row)
            else:
                removed.append(row)
        regressed.sort(key=lambda x: x["delta"])          # worst (most negative) first
        improved.sort(key=lambda x: -x["delta"])
        return {
            "cur_id": cur_id, "prev_id": prev_id,
            "cur_at": runs[cur_id].get("completed_at"), "prev_at": runs[prev_id].get("completed_at"),
            # Carried so the UI can SAY the scope changed rather than leaving a reader to infer
            # it from a diff that is quieter than they expected.
            "scope_changed": scope_changed,
            "prev_scope": prev_scope, "cur_scope": cur_scope,
            "summary": {"regressed": len(regressed), "improved": len(improved),
                        "new": len(new), "removed": len(removed),
                        "not_read": len(not_read), "incomparable": len(incomparable)},
            "regressed": regressed[:50], "improved": improved[:50], "new": new[:50],
            "removed": removed[:50], "not_read": not_read[:50], "incomparable": incomparable[:50],
        }

    def previous_run_for_source(self, scan_id: str, owner: str | None = None) -> str | None:
        """The run of the SAME SOURCE immediately before this one, or None.

        The baseline for a discovery diff, and deliberately not `list_scans()[i+1]`:

          - `list_scans` filters to `completed_at IS NOT NULL`, to keep in-flight runs out of the
            scan picker. An ADR 0020 Discover-only run sits at status='discovered' with no
            completed_at until somebody runs Assess — so the picker's filter would hide exactly
            the runs this diff is for, and the drawer would report "no baseline" for a source with
            a week of daily discoveries behind it.
          - it spans every source. With two connectors alternating, the immediately-prior scan is
            routinely the OTHER one, and diffing across them reports its whole estate as removed
            and this one's as new — two large numbers that look like news and are an artefact.

        Ordered by COALESCE(completed_at, started_at): `started_at` is written at init_scan_run
        for every run, so a run that never finished still orders correctly rather than sorting to
        the end as NULL.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT source, COALESCE(completed_at, started_at) AS at FROM scan_runs WHERE id=%s",
                (scan_id,))
            me = self._db.fetchone(cur)
            if not me or not me.get("at"):
                return None
            # Excludes status='superseded' (see supersede_scan) — a diff baseline must be a real
            # prior discovery, not an auto-cancelled attempt that barely started before this run
            # replaced it.
            where, params = ("source=%s AND COALESCE(completed_at, started_at) < %s "
                              "AND status != 'superseded'", (me["source"], me["at"]))
            if owner:
                where += " AND owner_email=%s"; params = params + (owner,)
            self._db.execute(cur,
                "SELECT id FROM scan_runs WHERE " + where
                + " ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 1", params)
            row = self._db.fetchone(cur)
            return row["id"] if row else None

    def last_nonempty_run_for_source(self, scan_id: str, owner: str | None = None) -> str | None:
        """The most recent prior run of the SAME SOURCE that actually inventoried something.

        NOT `previous_run_for_source`, and the difference is what stops the suspicious-zero guard
        (handlers._scan_discover) from disarming itself on the retry it invites.

        That guard asks "did this source have files last time?" to decide whether a zero is a
        transient API failure or a genuinely empty estate. Asked of the IMMEDIATELY prior run, the
        answer degrades after one failure:

            scan A → 100 files
            scan B → 0, guard fires, B is marked failed and keeps 0 inventory rows
            scan C → 0, baseline is now B, count_inventory(B) == 0, guard stays silent,
                     and C publishes the zero over A's real inventory

        `previous_run_for_source` excludes only status='superseded', so a failed zero-file run is
        a perfectly good diff baseline (it IS the immediately prior run — correct for a diff) and
        a useless guard baseline. The guard needs the last run that PROVED the estate was
        non-empty, however many failures sit between, so skipping straight to it makes the check
        idempotent across retries: attempt 2 and attempt 20 compare against the same 100.

        EXISTS over a JOIN/COUNT: this only asks whether any inventory row exists, and the caller
        counts separately for its message. On a source with a long history the index probe stops
        at the first hit rather than aggregating every prior run's rows.

        Pre-ADR-0020 scans stored discovered files in file_records rather than scan_inventory.
        The EXISTS clause covers both tables so that older baselines still disarm the guard.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT source, COALESCE(completed_at, started_at) AS at FROM scan_runs WHERE id=%s",
                (scan_id,))
            me = self._db.fetchone(cur)
            if not me or not me.get("at"):
                return None
            where, params = ("r.source=%s AND COALESCE(r.completed_at, r.started_at) < %s "
                             "AND r.status != 'superseded'", (me["source"], me["at"]))
            if owner:
                where += " AND r.owner_email=%s"; params = params + (owner,)
            self._db.execute(cur,
                "SELECT r.id FROM scan_runs r WHERE " + where
                + " AND (EXISTS (SELECT 1 FROM scan_inventory i WHERE i.scan_id = r.id)"
                + "      OR EXISTS (SELECT 1 FROM file_records f WHERE f.scan_id = r.id))"
                + " ORDER BY COALESCE(r.completed_at, r.started_at) DESC LIMIT 1", params)
            row = self._db.fetchone(cur)
            return row["id"] if row else None

    def last_published_whole_source_baseline(self, scan_id: str, *, owner: str,
                                             current_scope: dict,
                                             drive_account_id: str | None = None) -> dict | None:
        """Return the newest trustworthy whole-source baseline before ``scan_id``.

        Published is the durable proof that enumeration completed. Matching the scope kind
        keeps folder runs out of a whole-estate comparison. For Google Drive, a known account
        identity must also match; switching connectors is a new source boundary, not collapse.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT source, started_at FROM scan_runs WHERE id=%s AND owner_email=%s",
                (scan_id, owner))
            me = self._db.fetchone(cur)
            if not me:
                return None
            self._db.execute(cur,
                "SELECT id,scope FROM scan_runs "
                "WHERE owner_email=%s AND source=%s AND started_at < %s "
                "AND published_at IS NOT NULL AND status != 'superseded' "
                "ORDER BY published_at DESC",
                (owner, me["source"], me["started_at"]))
            for candidate in self._db.fetchall(cur):
                raw_scope = candidate.get("scope")
                if isinstance(raw_scope, str):
                    try:
                        raw_scope = json.loads(raw_scope)
                    except Exception:
                        continue
                prior_scope = raw_scope if isinstance(raw_scope, dict) else {}
                scope_kind = current_scope.get("kind")
                if prior_scope.get("kind") != scope_kind:
                    continue
                # The SITE SET, not one site id: a multi-site run has no singular `site`, so
                # comparing that field alone made every multi-site scan look like every other
                # one ("None == None") and would have matched a baseline covering a completely
                # different set of sites. See store.sharepoint_scope_sites.
                if scope_kind == "sharepoint" and (
                        sharepoint_scope_sites(prior_scope)
                        != sharepoint_scope_sites(current_scope)):
                    continue
                if not (prior_scope.get("enumeration") or {}).get("complete"):
                    continue
                baseline_id = candidate["id"]
                if scope_kind == "drive" and drive_account_id:
                    self._db.execute(cur,
                        "SELECT DISTINCT drive_account_id FROM scan_inventory "
                        "WHERE scan_id=%s AND drive_account_id IS NOT NULL",
                        (baseline_id,))
                    accounts = {r.get("drive_account_id") for r in self._db.fetchall(cur)}
                    if accounts and accounts != {drive_account_id}:
                        continue
                self._db.execute(cur,
                    "SELECT COUNT(*) AS n FROM scan_inventory WHERE scan_id=%s",
                    (baseline_id,))
                count = int((self._db.fetchone(cur) or {}).get("n") or 0)
                if count:
                    return {"scan_id": baseline_id, "count": count, "scope": prior_scope}
        return None

    def get_inventory_diff(self, cur_id: str, prev_id: str, owner: str | None = None) -> dict | None:
        """Diff two runs' DISCOVERY inventories → what the estate gained, lost and changed.

        NOT `get_scan_diff`, and the difference is the whole point. That method reads
        `file_records`, which is the ASSESSED grain: under ADR 0020 a Discover-only run persists
        `scan_inventory` and leaves `file_records` empty until Assess runs (handlers._scan_discover,
        "file_records stay empty until then"). Pointing a discovery question at it would answer
        `0 new · 0 changed · 0 removed` for exactly the runs a source panel is about, and would
        do it confidently. `scan_inventory` is the discover grain: every listed file, with the
        source metadata Discover recorded and no file opened.

        THREE PAIRS THAT MUST NOT COLLAPSE INTO ONE ANOTHER:

        1. `removed` vs `not_listed`. A file in the previous run and absent from this one is gone
           from the estate ONLY IF this run looked in the same place. `get_scan_diff` learned this
           the expensive way — a narrowed scope reported "45 documents disappeared" — and an
           inventory diff has the same exposure through the LISTING boundary rather than the format
           axis. When the boundary moved (folder → whole drive, a different site) or either listing
           hit its cap, every prev-only file is `not_listed`: we did not look, which is not a fact
           about the estate.

        2. `changed` vs `indeterminate`. `md5Checksum` is ABSENT for native Google Workspace files
           — Docs/Sheets/Slides have no fixed byte representation (scanner.py) — so a checksum
           comparison covers binary uploads and nothing else. `source_modified` is the fallback.
           Where neither side is comparable the answer is `indeterminate`, never `unchanged`:
           "we cannot tell" reported as "nothing happened" is the shape of every defect this
           module's comments are about.

        3. A missing baseline vs a quiet estate. `no_baseline` is returned when there is nothing
           to compare against, so the caller can OMIT the line rather than render three zeros that
           read as "we checked, nothing moved".

        Owner-scoped: both runs must belong to the caller, matching `get_scan_diff`.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, owner_email, started_at, completed_at, source, scope "
                "FROM scan_runs WHERE id IN (%s,%s)", (cur_id, prev_id))
            runs = {r["id"]: r for r in self._db.fetchall(cur)}
            if cur_id not in runs or prev_id not in runs:
                return None
            if owner is not None and (runs[cur_id].get("owner_email") != owner
                                      or runs[prev_id].get("owner_email") != owner):
                return None

            def _inv(sid):
                self._db.execute(cur,
                    "SELECT file, checksum, source_modified, size_kb FROM scan_inventory WHERE scan_id=%s",
                    (sid,))
                return {r["file"]: r for r in self._db.fetchall(cur)}

            ip, ic = _inv(prev_id), _inv(cur_id)

        def _scope(sid):
            import json as _json
            raw = runs[sid].get("scope")
            if not raw:
                return {}
            try:
                val = _json.loads(raw) if isinstance(raw, str) else raw
                return val if isinstance(val, dict) else {}
            except ValueError:
                return {}

        ps, cs = _scope(prev_id), _scope(cur_id)
        # The LISTING boundary, not the assessment format axis: `scan_inventory` records every
        # discovered file whatever its type, so a format scope does not remove rows from it. What
        # does is where we looked — kind/folder/site — and whether the listing completed.
        def _boundary(s):
            return (s.get("kind"), s.get("folder"), sharepoint_scope_sites(s))
        boundary_changed = _boundary(ps) != _boundary(cs)
        truncated = bool(ps.get("truncated") or cs.get("truncated"))
        # Either condition makes "absent" unreadable as "gone", so both route prev-only files to
        # not_listed. Reported separately because they need different words on screen: one is a
        # scope the operator changed, the other a cap ACP hit.
        cannot_claim_removal = boundary_changed or truncated

        new, changed, unchanged, indeterminate = [], [], [], []
        for f, row in ic.items():
            if f not in ip:
                new.append({"file": f, "size_kb": row.get("size_kb")})
                continue
            was = ip[f]
            a, b = was.get("checksum"), row.get("checksum")
            if a and b:
                (changed if a != b else unchanged).append(
                    {"file": f, "basis": "checksum"})
                continue
            am, bm = was.get("source_modified"), row.get("source_modified")
            if am and bm:
                (changed if am != bm else unchanged).append(
                    {"file": f, "basis": "modified", "prev": am, "cur": bm})
                continue
            # No checksum on either side (Google-native), no modified time recorded: the file is
            # present in both runs and that is genuinely all we know about it.
            indeterminate.append({"file": f, "reason": "no checksum or modified time to compare"})

        removed, not_listed = [], []
        for f, row in ip.items():
            if f in ic:
                continue
            entry = {"file": f, "size_kb": row.get("size_kb")}
            (not_listed if cannot_claim_removal else removed).append(entry)

        return {
            "cur_id": cur_id, "prev_id": prev_id,
            "cur_at": runs[cur_id].get("completed_at"), "prev_at": runs[prev_id].get("completed_at"),
            "source": runs[cur_id].get("source"),
            # Carried so the UI can SAY why a removal count is absent, rather than leaving a
            # reader to notice it is missing.
            "boundary_changed": boundary_changed, "truncated": truncated,
            "summary": {
                "new": len(new), "changed": len(changed), "removed": len(removed),
                "unchanged": len(unchanged), "not_listed": len(not_listed),
                "indeterminate": len(indeterminate),
            },
            "new": new[:50], "changed": changed[:50], "removed": removed[:50],
            "not_listed": not_listed[:50], "indeterminate": indeterminate[:50],
        }

    def inventory(self) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,first_seen,last_seen,last_status,last_score FROM inventory ORDER BY file")
            return self._db.fetchall(cur)

    def get_schedule(self) -> dict:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT key, value FROM schedule_config")
            rows = {r["key"]: r["value"] for r in self._db.fetchall(cur)}
        return {
            "enabled": rows.get("enabled", "false") == "true",
            "interval_minutes": int(rows.get("interval_minutes", "60")),
            "owner_email": rows.get("owner_email") or None,   # who scheduled it (scans attributed here)
            "source": rows.get("source") or "drive",          # background sweeps default to Drive (ADC)
        }

    def save_schedule(self, enabled: bool, interval_minutes: int,
                      owner: str | None = None, source: str | None = None) -> None:
        pairs = [("enabled", str(enabled).lower()), ("interval_minutes", str(interval_minutes))]
        if owner:
            pairs.append(("owner_email", owner))
        if source:
            pairs.append(("source", source))
        with self._db.cursor() as cur:
            for k, v in pairs:
                self._db.execute(cur,
                    "INSERT INTO schedule_config(key,value) VALUES(%s,%s) "
                    "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (k, v))

    def get_sync_cursor(self, source: str) -> dict | None:
        """The connector-native cursor (e.g. Drive's changes.list page token) the scheduled
        sweep last advanced to for `source`, or None if this source has never been synced
        incrementally (first-ever sweep, or a previous seed attempt never succeeded)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT source, owner_email, page_token, updated_at FROM sync_cursors WHERE source=%s",
                (source,))
            rows = self._db.fetchall(cur)
            return rows[0] if rows else None

    def save_sync_cursor(self, source: str, owner_email: str | None, page_token: str) -> None:
        import datetime as _dt
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO sync_cursors(source,owner_email,page_token,updated_at) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(source) DO UPDATE SET owner_email=EXCLUDED.owner_email, "
                "page_token=EXCLUDED.page_token, updated_at=EXCLUDED.updated_at",
                (source, owner_email, page_token, _dt.datetime.now(_dt.timezone.utc).isoformat()))

    def get_scan_traces(self, scan_id: str, file: str | None = None) -> list[dict]:
        with self._db.cursor() as cur:
            if file:
                self._db.execute(cur,
                    "SELECT rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count "
                    "FROM scan_rule_traces WHERE scan_id=%s AND file=%s ORDER BY rule_id",
                    (scan_id, file))
            else:
                self._db.execute(cur,
                    "SELECT file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count "
                    "FROM scan_rule_traces WHERE scan_id=%s ORDER BY file,rule_id",
                    (scan_id,))
            return self._db.fetchall(cur)

    def live_findings_count(self, scan_id: str) -> int:
        """Findings confirmed so far — SUM(finding_count) over FAIL traces, the SAME rows the
        certification report sums into its finding total (get_certification_facts: `f["findings"] +=
        finding_count` when outcome=='FAIL'). A single aggregate query, so the running screen's
        "findings so far" (Live Assessment PRD §4.3) is cheap to poll AND reconciles with the final
        cert. Never raises: an unknown scan is 0."""
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "SELECT COALESCE(SUM(finding_count),0) AS n FROM scan_rule_traces "
                    "WHERE scan_id=%s AND outcome='FAIL'", (scan_id,))
                row = self._db.fetchone(cur)
                return int((row or {}).get("n") or 0)
        except Exception:
            return 0

    def record_applied_fix(self, scan_id: str, file: str, rule_id: str, value: str,
                           *, source: str | None = None, thumb: str | None = None,
                           seq: int = 0) -> None:
        """Persist the concrete value an AI fix wrote (+ optional image thumbnail) so the
        UI can show the real applied text. Best-effort: callers wrap in try/except so a
        telemetry failure never fails the remediation job."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO applied_fixes(scan_id,file,rule_id,seq,value,source,thumb,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(scan_id,file,rule_id,seq) DO UPDATE SET "
                "value=EXCLUDED.value,source=EXCLUDED.source,thumb=EXCLUDED.thumb,created_at=EXCLUDED.created_at",
                (scan_id, file, rule_id, seq, value, source, thumb, now))

    def record_ai_call(self, *, surface: str, provider: str, model: str, zone: str,
                       latency_ms: int, ok: bool, scan_id: str | None = None,
                       file: str | None = None, cost_usd: float = 0.0,
                       reason: str | None = None, temperature: float | None = None,
                       prompt_version: str | None = None) -> None:
        """Append one AI-call provenance row (ADR 0019): which provider/model ran, WHERE
        (local/cloud zone), how long, at what cost, and — for a call that did not succeed —
        `reason`, WHICH way it failed (providers.REASON_*). Best-effort — a telemetry write
        must never fail the AI work it records."""
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO ai_calls(id,ts,scan_id,file,surface,provider,model,zone,"
                "latency_ms,ok,cost_usd,reason,temperature,prompt_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (uuid.uuid4().hex, now, scan_id, file, surface, provider, model, zone,
                 int(latency_ms), 1 if ok else 0, float(cost_usd), reason,
                 temperature, prompt_version))

    def list_ai_calls(self, scan_id: str | None = None, limit: int = 500) -> list[dict]:
        """Provenance rows for governance/cost views — newest first, optionally per scan."""
        with self._db.cursor() as cur:
            if scan_id:
                self._db.execute(cur, "SELECT * FROM ai_calls WHERE scan_id=%s ORDER BY ts DESC LIMIT %s",
                                 (scan_id, limit))
            else:
                self._db.execute(cur, "SELECT * FROM ai_calls ORDER BY ts DESC LIMIT %s", (limit,))
            return self._db.fetchall(cur)

    # -- R18 · Comments on a finding -----------------------------------------------------------
    def add_finding_comment(self, scan_id: str, finding_key: str, author: str, body: str,
                            file: str = "", rule_id: str = "") -> dict:
        """Append one comment to a finding's thread and return the stored row. Append-only:
        a comment is a record of what someone said, so there is no update or delete path here.
        `finding_key` is the finding's stable identity within the scan (computed client-side as
        file||rule||location); `file`/`rule_id` are denormalised for display. Empty `body`
        is rejected by the route, not silently stored."""
        import uuid
        from datetime import datetime, timezone
        row = {
            "id": uuid.uuid4().hex, "ts": datetime.now(timezone.utc).isoformat(),
            "scan_id": scan_id, "finding_key": finding_key,
            "file": file or "", "rule_id": rule_id or "", "author": author, "body": body,
        }
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO finding_comments(id,ts,scan_id,finding_key,file,rule_id,author,body) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (row["id"], row["ts"], row["scan_id"], row["finding_key"],
                 row["file"], row["rule_id"], row["author"], row["body"]))
        return row

    def list_finding_comments(self, scan_id: str, finding_key: str, limit: int = 500) -> list[dict]:
        """One finding's thread, OLDEST first — a conversation reads top-to-bottom. Scoped to
        (scan_id, finding_key); an empty list means no comments, never an error."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM finding_comments WHERE scan_id=%s AND finding_key=%s "
                "ORDER BY ts ASC LIMIT %s", (scan_id, finding_key, limit))
            return self._db.fetchall(cur)

    def count_finding_comments(self, scan_id: str) -> dict[str, int]:
        """How many comments each finding in a scan has, keyed by finding_key — lets the inbox
        show a '💬 n' marker without fetching every thread. Empty dict if none."""
        out: dict[str, int] = {}
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT finding_key, COUNT(*) AS n FROM finding_comments WHERE scan_id=%s "
                "GROUP BY finding_key", (scan_id,))
            for r in self._db.fetchall(cur):
                out[r.get("finding_key")] = int(r.get("n") or 0)
        return out

    def ai_cost_rollup(self, since_days: int | None = None, scan_id: str | None = None) -> dict:
        """AI usage + cost governance rollup (ADR 0019 Phase 1). Every number is a real
        aggregate of recorded ai_calls rows — calls, success, latency, and the summed
        cost_usd (a genuine $0 for the keyless local-Ollama build: no per-token billing, no
        bytes leaving the network). NOT a fabricated estimate (ADR 0016) — when a cloud
        adapter runs it records its real per-call cost and this reflects it. `since_days`
        bounds the window (1 = today-ish, 30 = month); None = all time. `scan_id` scopes the
        rollup to one scan — the per-scan provenance the certification report embeds (§4)."""
        from datetime import datetime, timedelta, timezone
        clauses, params_l = [], []
        if since_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
            clauses.append("ts >= %s")
            params_l.append(cutoff)
        if scan_id is not None:
            clauses.append("scan_id = %s")
            params_l.append(scan_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params = tuple(params_l)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COUNT(*) AS calls, COALESCE(SUM(ok),0) AS ok, "
                "COALESCE(SUM(cost_usd),0) AS cost, COALESCE(ROUND(AVG(latency_ms)),0) AS avg_ms, "
                "COUNT(DISTINCT scan_id) AS scans "
                f"FROM ai_calls{where}", params)
            tot = self._db.fetchone(cur) or {}

            def _group(col):
                self._db.execute(cur,
                    f"SELECT {col} AS k, COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS cost "
                    f"FROM ai_calls{where} GROUP BY {col} ORDER BY calls DESC", params)
                return [{"key": r["k"], "calls": r["calls"], "cost_usd": round(r["cost"] or 0, 4)}
                        for r in self._db.fetchall(cur)]

            # `failed` is a count with no diagnosis attached — the number that says something is
            # wrong and nothing about what. Break it down by the recorded reason so the rollup
            # distinguishes an unreachable endpoint from a model answering 200 with nothing.
            # Rows written before the column existed report `unrecorded` rather than a guess.
            self._db.execute(cur,
                "SELECT COALESCE(reason,'unrecorded') AS k, COUNT(*) AS calls "
                f"FROM ai_calls{where}{' AND' if where else ' WHERE'} ok=0 "
                "GROUP BY COALESCE(reason,'unrecorded') ORDER BY calls DESC", params)
            failure_reasons = [{"key": r["k"], "calls": r["calls"]} for r in self._db.fetchall(cur)]

            calls = tot.get("calls", 0) or 0
            return {
                "window_days": since_days,
                "calls": calls,
                "ok": tot.get("ok", 0) or 0,
                "failed": calls - (tot.get("ok", 0) or 0),
                "cost_usd": round(tot.get("cost", 0) or 0, 4),
                "avg_latency_ms": int(tot.get("avg_ms", 0) or 0),
                "scans": tot.get("scans", 0) or 0,
                "by_provider": _group("provider"),
                "by_zone": _group("zone"),
                "by_surface": _group("surface"),
                "failure_reasons": failure_reasons,
            }

    def list_applied_fixes(self, scan_id: str, limit: int = 200) -> list[dict]:
        """The AI fixes that wrote a concrete value in this scan, newest first — real
        applied text + thumbnail for the 'Recent AI fixes' surface."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,rule_id,seq,value,source,thumb,created_at FROM applied_fixes "
                "WHERE scan_id=%s ORDER BY created_at DESC, file, seq LIMIT %s",
                (scan_id, limit))
            return self._db.fetchall(cur)

    def record_remediation_diffs(self, scan_id: str, file: str, diffs: list[dict]) -> None:
        """Replace the stored before→after records for one (scan, file). Called once per
        remediate_file run with only the verified-cleared fixes, so a re-run overwrites
        rather than accumulating stale diffs. No-op for an empty list after clearing."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM remediation_diff WHERE scan_id=%s AND file=%s", (scan_id, file))
            seq_by_rule: dict[str, int] = {}
            for d in diffs:
                rid = str(d.get("rule_id") or "")
                seq = seq_by_rule.get(rid, 0)
                seq_by_rule[rid] = seq + 1
                self._db.execute(cur,
                    "INSERT INTO remediation_diff(scan_id,file,rule_id,seq,before,after,note) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (scan_id, file, rid, seq,
                     str(d.get("before") or "")[:2000], str(d.get("after") or "")[:2000],
                     str(d.get("note") or "")[:500]))

    def record_hitl_event(self, scan_id: str, file: str, rule_id: str, item_id: str,
                          action: str, *, edited: bool = False, review_ms: int | None = None,
                          ai_value: str | None = None, final_value: str | None = None,
                          reviewer: str | None = None, reject_reason: str | None = None) -> None:
        """One immutable row per human review decision — the telemetry the review workspace
        reports on (reviewer time saved) and calibrates from (edit rate on High-confidence
        proposals). `reject_reason` (Reviewer Feedback Intelligence) records WHY a rejection
        happened, so 'which rules/doc types are weakest' is answered by real reviewer behaviour
        rather than intuition. Best-effort: callers wrap so it never blocks a review."""
        from datetime import datetime, timezone
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO hitl_events(id,scan_id,file,rule_id,item_id,action,edited,"
                "review_ms,ai_value,final_value,reviewer,created_at,reject_reason) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (uuid.uuid4().hex, scan_id, file, rule_id, item_id, action,
                 1 if edited else 0, review_ms, ai_value or None, final_value or None,
                 reviewer, datetime.now(timezone.utc).isoformat(), reject_reason or None))

    def hitl_analytics(self, scan_id: str | None = None) -> dict:
        """Aggregate HITL review telemetry — headline metric is reviewer time eliminated,
        not % automated. Scoped to one scan when scan_id is given (owner-checked at the
        route), else across all recorded decisions.

        Reviewer Feedback Intelligence: also rolls up per-RULE and per-FORMAT quality (which
        criteria/doc types the AI is weakest on) and the reject-reason histogram — every figure
        a count of real reviewer decisions, never a fabricated score (ADR 0016)."""
        with self._db.cursor() as cur:
            cols = "action,edited,review_ms,rule_id,file,reject_reason"
            if scan_id:
                self._db.execute(cur,
                    f"SELECT {cols} FROM hitl_events WHERE scan_id=%s", (scan_id,))
            else:
                self._db.execute(cur, f"SELECT {cols} FROM hitl_events")
            rows = self._db.fetchall(cur)
        by: dict = {}
        for r in rows:
            by[r["action"]] = by.get(r["action"], 0) + 1
        approvals = by.get("approve", 0) + by.get("edit", 0)
        decided = len(rows) - by.get("skip", 0)
        edited_n = sum(1 for r in rows if r.get("edited"))
        ms = [r["review_ms"] for r in rows if r.get("review_ms") is not None]

        def _bucket(rows_iter, keyfn):
            out: dict[str, dict] = {}
            for r in rows_iter:
                k = keyfn(r)
                if not k:
                    continue
                b = out.setdefault(k, {"reviewed": 0, "approved": 0, "rejected": 0, "edited": 0,
                                       "reject_reasons": {}, "_ms": []})
                a = r.get("action")
                if a in ("approve", "edit", "reject"):
                    b["reviewed"] += 1
                if a in ("approve", "edit"):
                    b["approved"] += 1
                if a == "reject":
                    b["rejected"] += 1
                    rr = r.get("reject_reason")
                    if rr:
                        b["reject_reasons"][rr] = b["reject_reasons"].get(rr, 0) + 1
                if r.get("edited"):
                    b["edited"] += 1
                if r.get("review_ms") is not None:
                    b["_ms"].append(r["review_ms"])
            result = []
            for k, b in out.items():
                result.append({"key": k, "reviewed": b["reviewed"], "approved": b["approved"],
                               "rejected": b["rejected"], "edited": b["edited"],
                               "approval_rate": round(b["approved"] / b["reviewed"], 3) if b["reviewed"] else None,
                               "avg_review_ms": round(sum(b["_ms"]) / len(b["_ms"])) if b["_ms"] else None,
                               "reject_reasons": b["reject_reasons"]})
            # weakest first: most rejections, then lowest approval rate — the "where should
            # engineering invest next" ordering.
            result.sort(key=lambda x: (-x["rejected"], x["approval_rate"] if x["approval_rate"] is not None else 1.0))
            return result

        reasons: dict[str, int] = {}
        for r in rows:
            rr = r.get("reject_reason")
            if r.get("action") == "reject" and rr:
                reasons[rr] = reasons.get(rr, 0) + 1
        return {
            "total": len(rows),
            "by_action": by,
            "reviewed": decided,
            "approval_rate": round(approvals / decided, 3) if decided else None,
            "edit_rate": round(edited_n / approvals, 3) if approvals else None,   # calibration signal
            "avg_review_ms": round(sum(ms) / len(ms)) if ms else None,
            "reject_reasons": reasons,
            "by_rule": _bucket(rows, lambda r: (r.get("rule_id") or "").replace("SC_", "").replace("_", ".") or None),
            "by_format": _bucket(rows, lambda r: (r.get("file") or "").rsplit(".", 1)[-1].lower() if "." in (r.get("file") or "") else None),
        }

    def undo_applied_fix(self, scan_id: str, file: str, rule_id: str) -> bool:
        """R15 — undo ONE deterministic fix ACP claims to have applied.

        There is nothing to restore on the document: remediation never modifies the source, it
        only ever produces a separate corrected copy (ensure_remediated_folder / Blob), so
        'undo' cannot mean 'put the file back' — the file was never touched. It means ACP stops
        CLAIMING this finding is fixed. Both places that claim are cleared:

          - applied_fixes: the older, alt-text-only evidence table (autoFixRows' fallback source)
          - remediation_diff: the newer, all-fix-types before/after evidence table (autoFixRows'
            primary source when populated — record_remediation_diffs REPLACES the whole (scan,
            file) set on every remediate_file run, so this deletion is a snapshot edit, not a
            log entry; if the file is remediated again later, a still-fixable finding is fixed
            again like any other, which is the correct behaviour, not a resurrection bug)

        Once neither table claims the fix, isResolved() (remediationInboxModel.js) has nothing
        to key on for that (file, rule_id) and the finding falls back to whatever state its
        underlying assessment issue is actually in — reappearing in the worklist exactly as if
        the fix had never run. Returns True if either table actually had a row to remove, so the
        caller can tell 'undone' from 'nothing was applied here to begin with'.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM applied_fixes WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, rule_id))
            n1 = cur.rowcount
            self._db.execute(cur,
                "DELETE FROM remediation_diff WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, rule_id))
            n2 = cur.rowcount
        return bool((n1 or 0) + (n2 or 0))

    def get_remediation_diffs(self, scan_id: str, file: str) -> list[dict]:
        """The before→after evidence for one file, ordered by SC then application order —
        what the certification PDF's 'Before → After' section renders."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id,seq,before,after,note FROM remediation_diff "
                "WHERE scan_id=%s AND file=%s ORDER BY rule_id, seq", (scan_id, file))
            return self._db.fetchall(cur)

    def list_remediation_diffs(self, scan_id: str, limit: int = 2000) -> list[dict]:
        """Every verified-cleared before→after record across the whole scan — the honest,
        scan-wide 'what actually got fixed' set. Unlike applied_fixes (image alt text only),
        this covers ALL fix types (reading order, titles, headings, language, tables), so
        the Remediation UI can group real fixes by rule/category without fabricating counts.
        Includes `file` so the caller can reconcile per-document."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,rule_id,seq,before,after,note FROM remediation_diff "
                "WHERE scan_id=%s ORDER BY rule_id, file, seq LIMIT %s", (scan_id, limit))
            return self._db.fetchall(cur)

    def get_remediation_evidence(self, scan_id: str) -> list[dict]:
        """Per-file remediation evidence for the certification report's evidence appendix.

        Returns [{file, applied: [...], proposed: [...]}], files with neither omitted.

        `applied` — fixes that VERIFIABLY cleared the post-fix re-scan. `remediation_diff` is
        only ever written for those (the truthfulness gate in handlers._remediate_file), so
        every entry here is genuinely validated; each is enriched with the concrete value the
        AI wrote + its image thumbnail (`applied_fixes`) and the human sign-off that resolved
        it (`hitl_queue` + the immutable `decision_log`).

        `proposed` — AI proposals still awaiting human approval (`hitl_queue.proposals`,
        status 'pending'). These are NOT fixes: they must never be rendered as remediated or
        as PASS. Keeping the two lists separate is what stops the report claiming work the
        platform has not actually done.

        Attribution comes from `decision_log.actor`, which for a review is the authenticated
        reviewer's email (routes/hitl.py). It falls back to the literal 'reviewer' only when
        there is no signed-in identity (the demo/SSO-less path) — we surface exactly what was
        recorded and never invent a name.
        """
        rule_names = {r["id"]: r["name"] for r in RULE_CATALOG}

        # applied_fixes.rule_id is 'SC_1_1_1'; remediation_diff/hitl_queue use dotted '1.1.1'
        # (and hitl deferrals carry a '1.1.1/deferred' suffix). Normalise to the dotted SC.
        def _sc(rule_id: str) -> str:
            r = (rule_id or "").split("/", 1)[0]
            if r.upper().startswith("SC_"):
                r = r[3:].replace("_", ".")
            return r

        applied_fixes = self.list_applied_fixes(scan_id, limit=1000)
        fixes = {(f["file"], _sc(f["rule_id"]), f.get("seq") or 0): f for f in applied_fixes}

        hitl: dict[tuple, dict] = {}
        for h in self.list_hitl_queue(scan_id=scan_id):
            hitl.setdefault((h["file"], _sc(h["rule_id"])), h)

        reviews: dict[tuple, dict] = {}
        for d in self.list_decisions(scan_id, limit=1000):
            if (d.get("action") or "").startswith("hitl.") and d.get("file"):
                reviews.setdefault((d["file"], _sc(d.get("rule_id") or "")), d)

        # list_remediation_diffs returns every verified-cleared diff scan-wide WITH its file,
        # so one query replaces a per-file fan-out (and the DISTINCT-file helper this method
        # used to carry before that method existed).
        diffs_by_file: dict[str, list] = {}
        for d in self.list_remediation_diffs(scan_id):
            diffs_by_file.setdefault(d["file"], []).append(d)

        files = sorted({k[0] for k in hitl} | {f["file"] for f in applied_fixes}
                       | set(diffs_by_file))
        out: list[dict] = []
        for file in files:
            applied: list[dict] = []
            for d in diffs_by_file.get(file, []):
                sc = _sc(d["rule_id"])
                fx = fixes.get((file, sc, d.get("seq") or 0)) or {}
                hq = hitl.get((file, sc)) or {}
                rv = reviews.get((file, sc)) or {}
                # A criterion auto-cleared by a deterministic fixer has no HITL row at all;
                # one signed off by a human has a row and/or a decision_log entry. Prefer the
                # queue's status, else derive it from the immutable log ('hitl.approved' →
                # 'approved'), else leave None — meaning "no human decision was recorded",
                # which is the truth for an auto-applied deterministic fix.
                decision = hq.get("status") or ((rv.get("action") or "").split(".", 1)[1]
                                                if rv.get("action") else None)
                applied.append({
                    "sc": sc, "criterion": rule_names.get(sc, sc),
                    "before": d.get("before"), "after": d.get("after"), "note": d.get("note"),
                    "value": fx.get("value"), "source": fx.get("source"), "thumb": fx.get("thumb"),
                    "decision": decision, "approved_value": hq.get("approved_value"),
                    "reviewer": rv.get("actor"), "reviewed_at": rv.get("ts") or hq.get("reviewed_at"),
                    "validated": True,   # in remediation_diff ⇒ it cleared the re-scan
                })
            proposed: list[dict] = []
            for (f_, sc), h in hitl.items():
                if f_ != file or h.get("status") != "pending" or not h.get("proposals"):
                    continue
                proposed.append({
                    "sc": sc, "criterion": rule_names.get(sc, h.get("rule_name") or sc),
                    "validated": bool(h.get("validated")),
                    "proposals": h["proposals"],
                })
            if applied or proposed:
                out.append({"file": file, "applied": applied,
                            "proposed": sorted(proposed, key=lambda p: p["sc"])})
        return out

    def _unread_scope_facts(self, scan_id: str) -> dict:
        """What the file-type scope kept this scan from reading, for the scope-of-assertion text.

        Read off the scan's OWN recorded scope rather than the live setting: a report is a
        statement about what happened, and the operator may well have changed the scope since.
        Reading the current setting would let a report re-describe its own past.

        Returns {} when nothing was excluded or the scan predates the field, so the report adds
        no sentence rather than an empty or speculative one.
        """
        import json as _json
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s", (scan_id,))
                row = self._db.fetchone(cur)
            raw = (row or {}).get("scope")
            sc = (_json.loads(raw) if isinstance(raw, str) else raw) or {}
        except Exception:
            return {}
        skipped = int(sc.get("skipped_out_of_scope") or 0)
        scan_scope = sc.get("scan_scope")
        if not skipped and not scan_scope:
            return {}
        fmts = sorted({f for v in (scan_scope or {}).values() for f in (v or ())})
        return {"unread_documents": skipped, "formats_read": fmts}

    def _estate_scope_facts(self, scan_id: str) -> dict:
        """The whole-estate coverage funnel this scan recorded, for the report's scope section.

        Read off the scan's OWN frozen scope (scan_runs.scope), the same rule as
        _unread_scope_facts: a report states what happened, so it must not re-describe its past from
        the live setting. The `inventory` block is what scanner._list wrote (discovered / by_status /
        truncated); estate_inventory.funnel_facts reshapes it into the three honest denominators.

        Returns {} when the scan recorded no inventory — a local scan, or one predating the field —
        so the report simply omits the funnel rather than printing zeros.
        """
        import json as _json
        import estate_inventory
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s", (scan_id,))
                row = self._db.fetchone(cur)
            raw = (row or {}).get("scope")
            sc = (_json.loads(raw) if isinstance(raw, str) else raw) or {}
        except Exception:
            return {}
        funnel = estate_inventory.funnel_facts(sc.get("inventory"))
        return {"estate": funnel} if funnel else {}

    def get_certification_facts(self, scan_id: str, apply_document_selection: bool = False) -> dict:
        """Facts backing the certification-decision block, the richer file inventory, and the
        scope-of-assertion statement (backlog R2 / R6 / R-A). Every number is COUNTED from
        stored rows — none is estimated, and none is a percentage of an invented denominator.

        Per document:
          evaluated       — criteria that actually ran for this file's format (PASS or FAIL).
          not_evaluated   — criteria with NO validator for this format. They were never run;
                            a zero finding-count is not a pass, and their absence is NOT a
                            claim that the criterion does not apply (see _rule_outcome).
          failing         — criteria still failing.
          remediated      — criteria whose fix VERIFIABLY cleared the post-fix re-scan
                            (distinct SCs in remediation_diff — the truthfulness gate).
          remaining       — failing criteria with no verified fix.
          approvals       — HITL items a human approved for this file.
          by_mode         — how the evaluated criteria split across deterministic /
                            AI-assisted / human-only checks. This is what stops a reader
                            treating "100%" as "fully WCAG conformant": it shows how much of
                            the assertion rests on deterministic evidence.

        `scope.catalog_size` is the number of criteria this platform has a validator for —
        NOT the 87 success criteria of WCAG 2.1 AA. The report must never imply the two are
        the same.
        """
        rules = {r["id"]: r for r in RULE_CATALOG}
        traces = self.get_scan_traces(scan_id)
        evidence = {e["file"]: e for e in self.get_remediation_evidence(scan_id)}

        # Approvals are counted from the IMMUTABLE decision_log, not from hitl_queue's current
        # status, so this figure and the evidence appendix's per-fix sign-off line (which also
        # reads the log) can never disagree. Distinct per (file, criterion): re-approving the
        # same finding is one approval, not two.
        approved: set[tuple] = set()
        # Human-review outcomes for the assurance KPI (R9), counted the same immutable-log way as
        # approvals and deduped the same per (file, criterion) way — a re-review of one finding is
        # one outcome, not two. approved/rejected/skipped map to hitl.{status}; only the resolved
        # outcomes are counted (a pending item has no decision to report).
        review_seen: dict[str, set[tuple]] = {"approved": set(), "rejected": set(), "skipped": set()}
        for d in self.list_decisions(scan_id, limit=1000):
            act = d.get("action") or ""
            if act == "hitl.approved" and d.get("file"):
                approved.add((d["file"], d.get("rule_id") or ""))
            if act.startswith("hitl.") and d.get("file"):
                kind = act.split(".", 1)[1]
                if kind in review_seen:
                    review_seen[kind].add((d["file"], d.get("rule_id") or ""))
        approvals: dict[str, int] = {}
        for file, _rule in approved:
            approvals[file] = approvals.get(file, 0) + 1
        review_counts = {k: len(v) for k, v in review_seen.items()}
        review_counts["reviewed"] = sum(review_counts.values())

        per_file: dict[str, dict] = {}
        for t in traces:
            f = per_file.setdefault(t["file"], {
                "file": t["file"], "evaluated": 0, "not_evaluated": 0, "failing": 0,
                "review": 0, "findings": 0, "not_evaluated_criteria": [],
                "review_criteria": [], "by_mode": {}, "principles": {},
            })
            outcome = t.get("outcome")
            # Both tokens: a scan run before the rename, or by a rolled-back image, wrote the
            # old one. Reading only the new token would silently count those criteria as
            # neither evaluated nor skipped, and the coverage identity would quietly stop holding.
            if outcome in (NOT_EVALUATED, _LEGACY_NOT_EVALUATED):
                f["not_evaluated"] += 1
                f["not_evaluated_criteria"].append(t["rule_id"])
                continue
            # 🟡 Review Recommended (ADR 0023) — advisory, evidence-backed, NOT certified. It is
            # its own bucket: assessed-for-review, neither "evaluated" (we didn't verify a
            # pass/fail) nor "not_evaluated" (we did look and flagged a risk). It never blocks
            # certification. Counting it here keeps the identity honest:
            #   evaluated + not_evaluated + review == catalog_size.
            if outcome == REVIEW:
                f["review"] += 1
                f["review_criteria"].append(t["rule_id"])
                continue
            if outcome not in ("PASS", "FAIL"):
                continue                       # ERROR: the rule could not evaluate — assert nothing
            f["evaluated"] += 1
            mode = (rules.get(t["rule_id"], {}) or {}).get("fix_mode", "unknown")
            f["by_mode"][mode] = f["by_mode"].get(mode, 0) + 1
            # POUR (R8): group each evaluated criterion under its WCAG principle (the SC's leading
            # digit). This is a pass rate AMONG EVALUATED checks only — not-evaluated and review
            # criteria never enter it, so it can never be read as a full-conformance percentage.
            principle = _WCAG_PRINCIPLE.get((t["rule_id"] or "").split(".")[0])
            if principle:
                pc = f["principles"].setdefault(principle, {"evaluated": 0, "passed": 0})
                pc["evaluated"] += 1
                if outcome == "PASS":
                    pc["passed"] += 1
            if outcome == "FAIL":
                f["failing"] += 1
                f["findings"] += t.get("finding_count") or 0

        # Per-document carry-through (PRD §6.1): when the caller opts in, narrow the facts to the
        # operator's Remediate-time document selection (triage='inscope') — the per-document twin of
        # scan_scope, so the Assess status card and the conformance report inherit it just as they
        # inherit the criterion×format scope. Read-time (the marks are made after the traces), and
        # gated: without opt-in, or with no selection made, per_file — and every count below — is
        # untouched, so file cards and the coverage matrix keep seeing the whole estate.
        if apply_document_selection:
            selection = selected_documents(self.get_decisions(scan_id))
            if selection is not None:
                per_file = {fn: v for fn, v in per_file.items() if fn in selection}

        docs = []
        principle_tot: dict[str, dict] = {}
        for f in sorted(per_file.values(), key=lambda x: x["file"]):
            remediated = {a["sc"] for a in evidence.get(f["file"], {}).get("applied", [])}
            f["remediated"] = len(remediated)
            f["remaining"] = max(0, f["failing"] - len(remediated))
            f["approvals"] = approvals.get(f["file"], 0)
            f["not_evaluated_criteria"] = sorted(f["not_evaluated_criteria"])
            f["review_criteria"] = sorted(f["review_criteria"])
            # Fold this document's per-principle tallies into the estate total, then drop the
            # per-doc copy so the returned document rows stay the shape existing callers expect.
            for name, pc in f.pop("principles", {}).items():
                agg = principle_tot.setdefault(name, {"evaluated": 0, "passed": 0})
                agg["evaluated"] += pc["evaluated"]
                agg["passed"] += pc["passed"]
            docs.append(f)

        # All four principles, canonical order; one with nothing evaluated stays in the list with
        # evaluated=0 so the report can render "—" rather than silently dropping a principle.
        principles = [
            {"principle": name,
             "evaluated": principle_tot.get(name, {}).get("evaluated", 0),
             "passed": principle_tot.get(name, {}).get("passed", 0)}
            for name in ("Perceivable", "Operable", "Understandable", "Robust")]

        scope_modes: dict[str, int] = {}
        not_evaluated_union: set[str] = set()
        review_union: set[str] = set()
        for f in docs:
            for m, n in f["by_mode"].items():
                scope_modes[m] = scope_modes.get(m, 0) + n
            not_evaluated_union.update(f["not_evaluated_criteria"])
            review_union.update(f["review_criteria"])

        return {
            "documents": docs,
            "scope": {
                "catalog_size": len(RULE_CATALOG),
                "by_mode": scope_modes,
                "not_evaluated_criteria": [
                    {"sc": sc, "name": rules.get(sc, {}).get("name", sc)} for sc in sorted(not_evaluated_union)],
                # 🟡 Review Recommended criteria — listed explicitly as assessed-for-review,
                # NOT certified (kept separate from the certifiable "evaluated" headline).
                "review_criteria": [
                    {"sc": sc, "name": rules.get(sc, {}).get("name", sc)} for sc in sorted(review_union)],
                "human_only_criteria": [
                    {"sc": r["id"], "name": r["name"]} for r in RULE_CATALOG
                    if r["fix_mode"] == "human-only"],
                # FILE TYPES NEVER OPENED — the other half of the negative assurance.
                #
                # Everything above narrows the assertion by CRITERION: "we ran no check for
                # 2.4.3 on a PDF." None of it narrows the assertion by DOCUMENT, and once the
                # file-type scope gates what is read, a whole class of files is absent from this
                # report entirely — not failing, not passing, not evaluated, just never opened.
                #
                # A conformance report that lists the criteria it skipped but not the documents
                # it never saw understates its own boundary in the direction that flatters it,
                # which is precisely the failure the rest of this section exists to prevent. It
                # matters most for the reader this section is written for: an auditor asking
                # "does this cover the estate?" gets "yes" from silence.
                **self._unread_scope_facts(scan_id),
                # WHOLE-ESTATE SHAPE — the other half again, one level out. The unread-formats line
                # above states what was skipped WITHIN the scanned source; this states how much of the
                # discovered estate was ever an assessable format at all. Both are absent-by-silence
                # failures; both are stated here so the auditor's "does this cover the estate?" is
                # answered by numbers, not by omission.
                **self._estate_scope_facts(scan_id),
            },
            "approvals_total": sum(approvals.values()),
            "remediated_total": sum(d["remediated"] for d in docs),
            # POUR per-principle pass rate (R8) — evaluated + passed counted from the same traces;
            # the report renders passed/evaluated with its basis, never a bare percentage.
            "principles": principles,
            # Human-review outcomes (R9) — approved / rejected / skipped, plus their sum "reviewed",
            # each deduped per (file, criterion) from the immutable decision_log.
            "review": review_counts,
        }

    def get_trace_row(self, scan_id: str, file: str, rule_id: str) -> dict | None:
        """Return a single scan_rule_traces row for the AI explain endpoint."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id,rule_name,level,fix_mode,outcome,finding_count "
                "FROM scan_rule_traces WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, rule_id))
            rows = self._db.fetchall(cur)
        return rows[0] if rows else None

    def get_issue_rule_ids(self, scan_id: str, file: str, wcag_sc: str) -> list[str]:
        """Return the engine-level ruleIds (e.g. HTML_MISSING_LANG) for a given
        WCAG SC in a specific file, so the AI prompt can cite concrete check names."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT DISTINCT rule_id FROM issue_records "
                "WHERE scan_id=%s AND file=%s AND wcag LIKE %s",
                (scan_id, file, f"{wcag_sc}%"))
            rows = self._db.fetchall(cur)
        return [r["rule_id"] for r in rows]

    def remediation_status(self, scan_id: str) -> dict:
        """Live remediation facts used by both polling and SSE.

        Keep these as database facts rather than UI estimates: job state explains the queue,
        file_records proves a corrected copy was stored, and remediation_diff proves a fix
        survived the verification pass.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT status,COUNT(*) AS n FROM jobs WHERE scan_id=%s "
                "AND type='remediate_file' AND status IN ('queued','running') GROUP BY status",
                (scan_id,))
            job_counts = {row["status"]: row["n"] for row in self._db.fetchall(cur)}
            queued = int(job_counts.get("queued", 0) or 0)
            running = int(job_counts.get("running", 0) or 0)
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type='remediate_file' "
                "AND status='dead'", (scan_id,))
            failed = self._db.fetchone(cur)["n"]
            self._db.execute(cur,
                "SELECT file,drive_write_url,remediated_at FROM file_records WHERE scan_id=%s "
                "AND remediated_at IS NOT NULL ORDER BY remediated_at DESC LIMIT 5", (scan_id,))
            recent = self._db.fetchall(cur)
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM file_records WHERE scan_id=%s AND remediated_at IS NOT NULL",
                (scan_id,))
            stored = int(self._db.fetchone(cur)["n"] or 0)
            self._db.execute(cur,
                "SELECT COUNT(*) AS fixes,COUNT(DISTINCT file) AS documents "
                "FROM remediation_diff WHERE scan_id=%s", (scan_id,))
            verified = self._db.fetchone(cur) or {}
            self._db.execute(cur,
                "SELECT rule_id,COUNT(*) AS n FROM remediation_diff WHERE scan_id=%s "
                "GROUP BY rule_id ORDER BY n DESC,rule_id LIMIT 8", (scan_id,))
            by_rule = [{"rule": row["rule_id"], "fixes": int(row["n"] or 0)}
                       for row in self._db.fetchall(cur)]
        latest = recent[0] if recent else None
        return {"in_flight": queued + running, "queued": queued, "running": running,
                "failed": failed, "stored_documents": stored,
                "verified_documents": int(verified.get("documents", 0) or 0),
                "fixes_applied": int(verified.get("fixes", 0) or 0), "by_rule": by_rule,
                "latest_file": latest["file"] if latest else None,
                "latest_url": latest["drive_write_url"] if latest else None,
                "recent_files": [{"file": row["file"], "at": row["remediated_at"]}
                                 for row in recent]}

    def get_file_drive_id(self, scan_id: str, file: str) -> str | None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT drive_file_id FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            row = self._db.fetchone(cur)
        return row["drive_file_id"] if row else None

    def record_publish(self, scan_id: str, file: str, published_url: str | None = None) -> str:
        """Mark a file published (ADR 0010 archive-copy). Stores the Drive URL of the
        published fixed copy when one was written; COALESCE keeps a prior URL if this
        publish was record-only."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE file_records SET published_at=%s, published_url=COALESCE(%s, published_url) "
                "WHERE scan_id=%s AND file=%s",
                (now, published_url, scan_id, file))
            if cur.rowcount > 0:
                self._bump_scan_revision(cur, scan_id)
        return now

    def refresh_scan_aggregate(self, scan_id: str) -> dict:
        """Re-compute avg_score and certifiable from current file_records — called after
        a single-file rescore so the scan summary stays consistent without a full finalize."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET "
                "certifiable=(SELECT COALESCE(SUM(compliant),0) FROM file_records WHERE scan_id=%s), "
                "avg_score=(SELECT ROUND(AVG(score)) FROM file_records WHERE scan_id=%s AND score IS NOT NULL) "
                "WHERE id=%s",
                (scan_id, scan_id, scan_id))
            self._bump_scan_revision(cur, scan_id)
            self._db.execute(cur,
                "SELECT files,certifiable,uncertain,error,avg_score FROM scan_runs WHERE id=%s", (scan_id,))
            return self._db.fetchone(cur) or {}

    def get_file_record(self, scan_id: str, file: str) -> dict | None:
        """Return the full file_records row for one file in a scan."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,engine,status,score,compliant,drive_file_id,remediated_at,published_at "
                "FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            return self._db.fetchone(cur)

    def record_remediation(self, scan_id: str, file: str, drive_write_url: str | None = None,
                           blob_url: str | None = None) -> str:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            if blob_url is not None:
                self._db.execute(cur,
                    "UPDATE file_records SET remediated_at=%s, drive_write_url=%s, blob_url=%s "
                    "WHERE scan_id=%s AND file=%s",
                    (now, drive_write_url, blob_url, scan_id, file))
            else:
                # Blob not configured (e.g. local dev) — leave blob_url untouched rather
                # than clobbering a prior value with NULL.
                self._db.execute(cur,
                    "UPDATE file_records SET remediated_at=%s, drive_write_url=%s "
                    "WHERE scan_id=%s AND file=%s",
                    (now, drive_write_url, scan_id, file))
            if cur.rowcount > 0:
                self._bump_scan_revision(cur, scan_id)
        return now

    def get_remediation_urls(self, scan_id: str, file: str,
                             owner: str | None = None) -> dict | None:
        """blob_url + drive_write_url for a remediated file's download route.

        `owner` filters IN SQL, so a foreign row is never read into memory rather than being
        read and then rejected. It is optional only so a caller with no user context (the
        worker tier, a migration) is not forced to invent one; every request path must pass it.

        THE ROW THIS RETURNS IS A CAPABILITY, not a description. `drive_write_url` is a live
        link to a remediated document, and the download route redirects to it — so an unscoped
        lookup here was sufficient on its own to disclose another user's PHI, even though the
        blob read beside it was correctly scoped and returned nothing. Defence in depth is the
        point: the route now checks ownership too, and either check alone would have stopped it.
        """
        sql = "SELECT blob_url, drive_write_url FROM file_records WHERE scan_id=%s AND file=%s"
        params: tuple = (scan_id, file)
        if owner is not None:
            sql += " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)"
            params += (owner,)
        with self._db.cursor() as cur:
            self._db.execute(cur, sql, params)
            return self._db.fetchone(cur)

    def find_remediation_for_file(self, owner: str | None, scan_id: str, file: str) -> dict | None:
        """Most-recent recorded remediation of the SAME document across this owner's scans.

        Both the file_records remediation row AND the Blob object are keyed by scan_id,
        but an ADR 0011 incremental re-scan mints a NEW scan_id and, for an unchanged
        file, reuses the prior analysis WITHOUT re-remediating — so the fixed copy stays
        under the scan_id that actually ran the remediation. When the download route can't
        find a remediation on the scan the user is viewing, resolve the document's stable
        identity (Drive id first — survives rename; else byte-identical checksum; else the
        file name) and return the newest COMPLETED scan that DID record one, so the fixed
        bytes remain reachable from a later scan's drawer. Returns {scan_id, file, blob_url,
        drive_write_url} — scan_id/file identify where the Blob object actually lives (the
        caller downloads from there, not the viewed scan). None if no prior remediation."""
        with self._db.cursor() as cur:
            # Identity of the file as seen in the scan the user is viewing.
            self._db.execute(cur,
                "SELECT drive_file_id, checksum FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            cur_row = self._db.fetchone(cur)
            if not cur_row:
                return None
            drive_file_id = cur_row.get("drive_file_id")
            checksum = cur_row.get("checksum")
            if drive_file_id:
                match_sql, match_val = "fr.drive_file_id=%s", drive_file_id
            elif checksum:
                match_sql, match_val = "fr.checksum=%s", checksum
            else:
                match_sql, match_val = "fr.file=%s", file
            self._db.execute(cur,
                "SELECT fr.scan_id, fr.file, fr.blob_url, fr.drive_write_url "
                "FROM file_records fr JOIN scan_runs sr ON sr.id = fr.scan_id "
                f"WHERE sr.owner_email=%s AND {match_sql} "
                "AND (fr.blob_url IS NOT NULL OR fr.drive_write_url IS NOT NULL) "
                "AND sr.completed_at IS NOT NULL "
                "ORDER BY sr.completed_at DESC LIMIT 1",
                (owner, match_val))
            return self._db.fetchone(cur)

    def _full_catalog_rules(self) -> dict[str, list[dict]]:
        """Return rule-catalog.json grouped by engine (docx/pptx/xlsx/pdf/html)."""
        return {k: v for k, v in _CATALOG_JSON.items() if isinstance(v, list)}

    def get_scan_manifest(self, scan_id: str) -> dict:
        """Return per-file rule-execution manifest for a scan.

        Each file lists every catalog rule and an explicit status:
          PASS / FAIL         — the rule applies to this file's format and ran
          ERROR               — the rule applies, was attempted, and the engine failed on it
          NOT_CHECKED         — the rule applies and did NOT run. Its own status because the
                                alternative was recording it PASS, which is a compliance claim
                                about work never done (see _save_file_manifest).
          NOT_APPLICABLE      — the rule belongs to a different format (e.g. a PPTX rule against
                                a .docx). Recorded explicitly so an auditor can see a rule was
                                *considered*, not silently omitted. N/A does not count against
                                completeness (completeness = checked / applicable).

        WHERE THE FILE LIST COMES FROM, AND WHY IT MOVED. This used to read
        `SELECT DISTINCT file FROM scan_file_manifests`, which defines the scan's files as
        "the files that have manifest rows" — so a file with none was not 0% complete, it was
        ABSENT, and files_total under-reported the scan. _save_file_manifest returns early and
        writes nothing whenever a file's extension has no catalog rules, so that was reachable
        on any scan containing one. Measured: a two-file scan reported files_total 1.

        The file list is now file_records — the scan's actual files — with the manifest table
        unioned in so a manifest row can never be orphaned by a missing file record either. A
        file with no rows is reported, with `reason` saying which kind of nothing it is:
          no_manifest         — its format HAS rules and none were recorded. An integrity fault.
          unsupported_format  — its format has no rules at all, so nothing was ever expected of
                                it. Not a fault, and deliberately not counted as one.

        UNATTRIBUTED ERRORS. `skipped_rules` on file_records is Rubric.assess's count of engine
        errors, and it survives on paths where the error LIST does not (see _save_file_manifest).
        Where that count exceeds the ERROR rows actually recorded, the difference is reported as
        `rules_errored_unattributed` rather than resolved into PASS: the honest statement is
        "N rules errored and which ones was not recorded", not "everything else passed".
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, rule_id, status, finding_count "
                "FROM scan_file_manifests WHERE scan_id=%s ORDER BY file, rule_id",
                (scan_id,))
            rows = self._db.fetchall(cur)
            self._db.execute(cur,
                "SELECT file, status, skipped_rules FROM file_records WHERE scan_id=%s",
                (scan_id,))
            records = {r["file"]: r for r in self._db.fetchall(cur)}
            self._db.execute(cur,
                "SELECT DISTINCT file FROM scan_file_manifests WHERE scan_id=%s", (scan_id,))
            manifest_files = [r["file"] for r in self._db.fetchall(cur)]

        catalog = self._full_catalog_rules()
        # Map every engine rule_id → its engine, for NOT_APPLICABLE derivation.
        all_rule_ids = {r["id"]: eng for eng, rules in catalog.items() for r in rules}
        # The scan's files: what it recorded results for, plus anything with manifest rows.
        scan_files = set(records) | set(manifest_files)

        by_file: dict[str, list[dict]] = {}
        for r in rows:
            by_file.setdefault(r["file"], []).append({
                "rule_id": r["rule_id"],
                "status": r["status"],
                "finding_count": r["finding_count"],
            })
        files = []
        total_expected = total_checked = total_errored = total_na = 0
        total_unchecked = total_unattributed = 0
        for fname in sorted(scan_files):
            rules = by_file.get(fname, [])
            # Whether the scan RECORDED anything for this file, captured before the synthetic
            # NOT_CHECKED rows below are added — `reason` and the completeness rules below both
            # turn on it, and after the append `rules` can no longer answer it.
            had_rows = bool(rules)
            applied_ids = {r["rule_id"] for r in rules}
            record = records.get(fname) or {}
            ext = Path(fname).suffix.lower().lstrip(".")
            own_ids = {r["id"] for r in catalog.get(ext, [])}
            catalog_size = len(own_ids)
            # A file with NO rows still owes its own format's rules, so they are emitted as
            # NOT_CHECKED here rather than swept into NOT_APPLICABLE with every other format's.
            # Without this the summary counted them as missing (below) while the per-rule list
            # called them not-applicable — the two halves of the same answer disagreeing, and the
            # named-checks disclosure in the UI showing nothing for the very file it is about.
            missing_own = ([{"rule_id": rid, "status": "NOT_CHECKED", "finding_count": 0}
                            for rid in sorted(own_ids)] if not rules else [])
            # Rules from other formats → explicit NOT_APPLICABLE.
            claimed = applied_ids | {r["rule_id"] for r in missing_own}
            na = [{"rule_id": rid, "status": "NOT_APPLICABLE", "finding_count": 0}
                  for rid in sorted(all_rule_ids) if rid not in claimed]
            rules = rules + missing_own

            errored = sum(1 for r in rules if r["status"] == "ERROR")
            unchecked = sum(1 for r in rules if r["status"] == "NOT_CHECKED")
            # Errors the rubric counted but no row names. Never folded into `checked`.
            unattributed = max(0, int(record.get("skipped_rules") or 0) - errored)
            # A file with no rows at all is expected to have its whole catalog — `missing_own`
            # above already put those rules in as NOT_CHECKED, so the gap reads as the size of
            # what was skipped rather than as an empty, complete file.
            expected = len(rules) or catalog_size
            # Capped at what is left after the rules already accounted for. On a file where
            # NOTHING ran, every rule is already NOT_CHECKED and the rubric's error count is a
            # second description of the same gap — counting it again would report more missing
            # rules than the file has.
            unattributed = min(unattributed, max(0, expected - errored - unchecked))
            checked = max(0, expected - errored - unchecked - unattributed)

            reason = None
            if not had_rows:
                reason = "unsupported_format" if catalog_size == 0 else "no_manifest"
            # An unsupported format expected nothing, so it is neither complete nor incomplete —
            # it is out of scope, and must not drag the percentage down or up.
            counts_towards_completeness = reason != "unsupported_format"
            if counts_towards_completeness:
                total_expected += expected
                total_checked += checked
                total_errored += errored
                total_unchecked += unchecked
                total_unattributed += unattributed
            total_na += len(na)
            files.append({
                "file": fname,
                "file_status": record.get("status"),
                "reason": reason,
                "rules_expected": expected,
                "rules_checked": checked,
                "rules_errored": errored,
                "rules_not_checked": unchecked,
                "rules_errored_unattributed": unattributed,
                "rules_not_applicable": len(na),
                "completeness_pct": (round(checked / expected * 100) if expected
                                     else (100 if reason == "unsupported_format" else 0)),
                "complete": (checked == expected) if counts_towards_completeness else True,
                "rules": rules + na,
            })
        # `complete` means every applicable rule on every file actually ran. It used to mean
        # `rules_errored_total == 0`, which — with the ERROR branch unreachable — was true of
        # every scan regardless of what happened during it.
        incomplete = total_errored + total_unchecked + total_unattributed
        return {
            "scan_id": scan_id,
            "files_total": len(files),
            "rules_expected_total": total_expected,
            "rules_checked_total": total_checked,
            "rules_errored_total": total_errored,
            "rules_not_checked_total": total_unchecked,
            "rules_errored_unattributed_total": total_unattributed,
            "rules_not_applicable_total": total_na,
            "completeness_pct": (
                round(total_checked / total_expected * 100) if total_expected else 100
            ),
            "complete": incomplete == 0,
            "files": files,
        }

    def rule_findings(self) -> dict:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id FROM scan_runs ORDER BY completed_at DESC LIMIT 1")
            latest = self._db.fetchone(cur)
            if not latest:
                return {}
            self._db.execute(cur,
                "SELECT rule_id, COUNT(*) AS n FROM issue_records "
                "WHERE scan_id=%s GROUP BY rule_id", (latest["id"],))
            return {r["rule_id"]: r["n"] for r in self._db.fetchall(cur)}

    def _pages_for(self, cur, scan_id: str, file: str, rule_id: str) -> list[int]:
        """Distinct pages/slides where this criterion fails in this file, ascending.

        hitl_queue.rule_id is an SC ('1.1.1', or '1.1.1/deferred'); issue_records keys pages by
        the ENGINE rule id and carries the SC in `wcag`. So the join goes through _extract_sc on
        both sides rather than a direct rule_id match — comparing them raw would silently find
        nothing and every item would show no page.
        """
        sc = _extract_sc(rule_id)
        if not sc:
            return []
        self._db.execute(cur,
            "SELECT wcag, page FROM issue_records WHERE scan_id=%s AND file=%s AND page IS NOT NULL",
            (scan_id, file))
        pages = {int(r["page"]) for r in self._db.fetchall(cur)
                 if _extract_sc(r["wcag"]) == sc and r["page"]}
        return sorted(pages)

    def _location_for(self, cur, scan_id: str, file: str, rule_id: str) -> str | None:
        """The finding's position IN WORDS for this (file, criterion) — "Slide 3", "Sheet
        'Findings' cell B2" — or None when no detector could say.

        The sibling of `_pages_for`, and needed because that one answers in integers. A page
        number is the right answer for PDF and there is no such thing for a worksheet or a
        deck, so `pages` came back empty for every Office finding and the review card's
        location chip rendered nothing. The detectors have emitted `location` for these all
        along and `_loc()` has stored it; only the queue row was missing it.

        First non-null wins, matching the finding it describes: these rules report one row per
        file carrying one example, so there is one location to carry.
        """
        sc = _extract_sc(rule_id)
        if not sc:
            return None
        self._db.execute(cur,
            "SELECT wcag, location FROM issue_records "
            "WHERE scan_id=%s AND file=%s AND location IS NOT NULL",
            (scan_id, file))
        for r in self._db.fetchall(cur):
            if _extract_sc(r["wcag"]) == sc and r["location"]:
                return r["location"]
        return None

    def queue_hitl_items(self, scan_id: str) -> list[dict]:
        """Auto-populate HITL queue from ai-assisted FAILs in a saved scan.

        Idempotent: skips (scan_id, file, rule_id) combos already queued.
        Returns the list of newly created items for webhook notification.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, rule_id, rule_name, finding_count "
                "FROM scan_rule_traces "
                "WHERE scan_id=%s AND fix_mode='ai-assisted' AND outcome='FAIL'",
                (scan_id,))
            candidates = self._db.fetchall(cur)
            # Build set of already-queued (file, rule_id) pairs for this scan.
            self._db.execute(cur,
                "SELECT file, rule_id FROM hitl_queue WHERE scan_id=%s", (scan_id,))
            already = {(r["file"], r["rule_id"]) for r in self._db.fetchall(cur)}

        created: list[dict] = []
        for c in candidates:
            if (c["file"], c["rule_id"]) in already:
                continue  # idempotent — skip already-queued items
            item_id = uuid.uuid4().hex[:12]
            with self._db.cursor() as cur:
                pages = self._pages_for(cur, scan_id, c["file"], c["rule_id"])
                location = self._location_for(cur, scan_id, c["file"], c["rule_id"])
                self._db.execute(cur,
                    "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status,page,pages,location) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)",
                    (item_id, now, scan_id, c["file"], c["rule_id"], c["rule_name"], c["finding_count"],
                     pages[0] if pages else None, _pages_csv(pages), location))
            created.append({"id": item_id, "scan_id": scan_id, "file": c["file"],
                             "rule_id": c["rule_id"], "rule_name": c["rule_name"],
                             "finding_count": c["finding_count"], "status": "pending", "created_at": now,
                             "page": pages[0] if pages else None, "pages": _pages_csv(pages),
                             "location": location})
        return created

    def queue_hitl_deferral(self, scan_id: str, file: str, note: str, count: int = 1,
                            rule_id: str = "1.1.1/deferred",
                            rule_name: str | None = None) -> str | None:
        """Queue ONE human-review item for a remediation deferral — e.g. Office images
        with no faithful alt source (remediate_office). Those findings carry fix_mode
        'auto', so queue_hitl_items' ai-assisted pull never sees them; without this
        the deferral is reported in the job result and then silently dropped.
        Idempotent per (scan, file, criterion) like queue_hitl_items.

        A deferral is NOT a separate criterion. '1.1.1/deferred' used to open its own row
        beside the '1.1.1' row that enqueue_proposals / queue_hitl_review_for_file write, and
        scOf() renders both as "WCAG 1.1.1" — so one file showed two identical review cards,
        and the one a reviewer opened was not necessarily the one holding the AI proposals.
        Deferrals now MERGE into the canonical row for their criterion.

        'auto/verify' is not a WCAG criterion (it is "an automatic fix, please eyeball it"),
        so it keeps its own row — see _canonical_rule_id."""
        from datetime import datetime, timezone
        canonical = _canonical_rule_id(rule_id)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, finding_count FROM hitl_queue WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, canonical))
            row = self._db.fetchone(cur)
            if row:
                # The criterion already has a row. Never shrink its finding count: the deferral
                # knows how many images it gave up on, the proposals row knows how many it
                # drafted, and the scan knows the true total. The largest is the safest floor.
                if (count or 0) > (row.get("finding_count") or 0):
                    self._db.execute(cur, "UPDATE hitl_queue SET finding_count=%s WHERE id=%s",
                                     (count, row["id"]))
                return None    # merged, not created — callers must not fire a "new item" webhook
            item_id = uuid.uuid4().hex[:12]
            pages = self._pages_for(cur, scan_id, file, canonical)
            self._db.execute(cur,
                "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status,page,pages) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                (item_id, datetime.now(timezone.utc).isoformat(), scan_id, file, canonical,
                 (rule_name or note)[:200], count, pages[0] if pages else None, _pages_csv(pages)))
        return item_id

    def queue_hitl_review_for_file(self, scan_id: str, file: str,
                                   rules: list[dict]) -> list[dict]:
        """Queue HITL review items for specific FAILing rules of ONE file — the human-
        judgment findings a remediate_file run could NOT verifiably auto-clear (contrast
        sign-off, link purpose, structure, or an auto fix that didn't take on re-scan).
        Without this the residual routes to nobody: queue_hitl_items only pulls
        fix_mode='ai-assisted' scan-wide, so a fix_mode='auto' finding the remediator
        couldn't clear (e.g. 1.4.3 contrast needing design sign-off) silently vanishes and
        the file can never re-validate to compliant. `rules` = [{rule_id, rule_name,
        finding_count}]. Idempotent per (scan, file, rule) like queue_hitl_items /
        queue_hitl_deferral — repeat remediate clicks never duplicate. Returns new items."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        created: list[dict] = []
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, rule_id, finding_count FROM hitl_queue WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            existing = {r["rule_id"]: r for r in self._db.fetchall(cur)}
            already = set(existing)
            for r in rules:
                rid = r.get("rule_id")
                if not rid:
                    continue
                if rid in already:
                    # The criterion already has its row — a deferral merged into it, or a
                    # previous remediate created it. Don't duplicate, but don't let it keep a
                    # smaller count than the scan knows: the deferral counts what it gave up
                    # on, the scan counts every finding.
                    prev = existing[rid]
                    if (r.get("finding_count") or 0) > (prev.get("finding_count") or 0):
                        self._db.execute(cur, "UPDATE hitl_queue SET finding_count=%s WHERE id=%s",
                                         (r["finding_count"], prev["id"]))
                    continue
                item_id = uuid.uuid4().hex[:12]
                name = r.get("rule_name") or rid
                count = r.get("finding_count") or 1
                pages = self._pages_for(cur, scan_id, file, rid)
                self._db.execute(cur,
                    "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status,page,pages) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                    (item_id, now, scan_id, file, rid, name, count,
                     pages[0] if pages else None, _pages_csv(pages)))
                already.add(rid)
                created.append({"id": item_id, "scan_id": scan_id, "file": file,
                                "rule_id": rid, "rule_name": name, "finding_count": count,
                                "status": "pending", "created_at": now})
        return created

    def enqueue_proposals(self, scan_id: str, file: str, sc: str, proposals: list[dict],
                          *, validated: bool = False, rule_name: str | None = None,
                          finding_count: int | None = None) -> str | None:
        """Attach AI-proposed concrete fix values to the HITL row for (scan, file, sc), so the
        reviewer approves a pre-computed value in one click instead of drafting from a blank.

        `proposals` = [{locator, before, proposed_value, rationale, source, thumb?}, …], one
        per finding instance. `validated` is True only when the batch cleared its SC on the
        post-apply re-scan (an honest signal, persisted for confidence.js). Idempotent per
        (scan, file, sc) like the other queue_* methods: a repeat remediate REPLACES the
        proposals on the existing row rather than duplicating — the newest proposal wins.
        Returns the item id, or None when `proposals` is empty (nothing to surface)."""
        if not proposals:
            return None
        import json as _json
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        blob = _json.dumps(proposals)
        vflag = 1 if validated else 0
        count = finding_count if finding_count is not None else len(proposals)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, finding_count FROM hitl_queue WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, sc))
            row = self._db.fetchone(cur)
            if row:
                # Only refresh the proposal payload; never clobber a status the reviewer
                # already moved off 'pending' (approved/rejected/skipped stays put).
                #
                # And never SHRINK the finding count. A deck with 19 unlabelled images whose
                # vision model drafted 1 of them is still a 19-finding criterion; overwriting
                # the count with len(proposals) made the card announce "1 finding" and told the
                # reviewer 18 images had gone away. An explicit finding_count still wins.
                merged = count if finding_count is not None else max(count, row.get("finding_count") or 0)
                self._db.execute(cur,
                    "UPDATE hitl_queue SET proposals=%s, validated=%s, finding_count=%s "
                    "WHERE id=%s",
                    (blob, vflag, merged, row["id"]))
                return row["id"]
            item_id = uuid.uuid4().hex[:12]
            self._db.execute(cur,
                "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,"
                "finding_count,status,proposals,validated) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                (item_id, now, scan_id, file, sc, rule_name or sc, count, blob, vflag))
        return item_id

    def attach_hitl_evidence(self, scan_id: str, file: str, sc: str,
                             evidence: list[dict]) -> str | None:
        """Attach the images a HITL row asks a human to describe: [{locator, thumb}, …].

        Evidence is not a proposal — there is no value to approve, so it must not ride in the
        `proposals` column, where its presence would make confidence.js report an AI proposal
        that does not exist.

        Matches the row for this SC whether it was queued as '1.1.1' (queue_hitl_review_for_file
        / enqueue_proposals) or as '1.1.1/deferred' (queue_hitl_deferral) — the deferral suffix
        is precisely the alt-text case that most needs the picture. Idempotent: a repeat
        remediate REPLACES the evidence rather than appending. Returns the row id, or None when
        there is nothing to attach or no row to attach it to."""
        if not evidence:
            return None
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id FROM hitl_queue WHERE scan_id=%s AND file=%s "
                "AND (rule_id=%s OR rule_id LIKE %s) ORDER BY created_at LIMIT 1",
                (scan_id, file, sc, f"{sc}/%"))
            row = self._db.fetchone(cur)
            if not row:
                return None
            self._db.execute(cur, "UPDATE hitl_queue SET evidence=%s WHERE id=%s",
                             (_json.dumps(evidence), row["id"]))
            return row["id"]

    # ── Approved content: the promise, and the write that keeps it ────────────────────────
    #
    # A value-fix approval (alt text, link text) resolves to CONTENT the document must carry.
    # Storing it on the queue row is evidence of what a human agreed to, not a fix: until it is
    # written in, the images are still undescribed. `applied` records that write. The gate
    # below is what stops a file certifying on a promise.

    @staticmethod
    def _row_approved_values(row: dict) -> dict[str, str]:
        """{locator: final text} for one approved row — the values that must reach the document.

        Prefers the per-proposal `approved_value` (one image, one description; a single column
        could never express a ten-image deck), and falls back to the proposal's own draft. That
        fallback is not a guess: approving a row means accepting the drafts it was showing, and
        a reviewer who edits nothing has agreed to exactly them. It also closes a hole — a
        client that approved without sending approved_values left every proposal valueless, so
        the row held no "content", the gate below counted nothing, and the file certified with
        the drafts never written in.

        Proposals with no locator are skipped: unaddressable content cannot be written anywhere.
        So are EXPLAIN-ONLY proposals (proposals.proposal(explain_only=True)) — a PDF structure
        map, heading map or page reading order, whose approved value is the tagging instruction
        and the compliance evidence, never bytes to write into the document. They are addressable
        and they are approved, but no applier will ever write them, so counting them as content
        the file "does not yet carry" blocks certification for good on a correct approval. The
        test is on the proposal, not the reviewer's action, because of the draft fallback right
        below: a client that suppressed the value would have it handed straight back.

        A row carrying a WCAG-exception `resolution` yields NOTHING. Marking an image decorative
        or an image-of-text an essential logotype resolves the finding BY JUDGEMENT — the
        reviewer authored no value, and the draft the card was showing was never a candidate for
        the document. Without this the fallback below handed the applier the card's own UI label:
        approving "Mark as decorative" wrote descr="Mark as decorative" onto the picture, which
        is a worse outcome than the missing alt text it replaced. The decorative DECISION still
        reaches the document — as the OOXML decorative marker, via approved_decorative_locators
        below — but it is a marking, never prose.

        The test is on the stored row rather than on what the client sent, for the same reason
        the fallback exists at all: EvidenceCard already suppresses the values for a resolution,
        and that suppression was handed straight back by the fallback.

        Also folds in `evidence` entries the reviewer described. A deferred 1.1.1 row (Office
        images with no faithful alt source, and no vision draft) carries `evidence`
        [{locator, thumb}] and NO proposals, so a reviewer's alt text had nowhere per-image to
        live: the value went into the single legacy column with no locator, could never be
        written, and blocked the file forever. Evidence has no draft, so there is no fallback —
        an undescribed evidence image contributes nothing.
        """
        out: dict[str, str] = {}
        if Store._row_is_resolved(row):
            return out
        for p in (row.get("proposals") or []):
            if not isinstance(p, dict):
                continue
            # Explain-only: confirmed evidence, never bytes for the document.
            # Companion: a caption/transcript FILE delivered beside the document. Both are
            # approved and addressable, and neither is content an applier will write in, so
            # counting either as outstanding blocks certification for good.
            if p.get("explain_only") or Store.companion_name(p.get("companion_file")):
                continue
            loc = (p.get("locator") or "").strip()
            val = (p.get("approved_value") or "").strip() or (p.get("proposed_value") or "").strip()
            if loc and val:
                out[loc] = val
        for e in (row.get("evidence") or []):
            if not isinstance(e, dict):
                continue
            loc = (e.get("locator") or "").strip()
            val = (e.get("approved_value") or "").strip()   # no proposed_value: evidence is undrafted
            if loc and val:
                out[loc] = val
        return out

    @staticmethod
    def _row_is_resolved(row: dict) -> bool:
        """True when a reviewer closed this row with a WCAG exception rather than a value.

        Such a row promises the document no prose. That governs _row_approved_values above, and
        it has to govern the legacy single `approved_value` column in the counters below too.
        That column is normally the honest reason a row counts forever — a human agreed to some
        text and we don't know where it goes — but here there is nowhere for it to go BY DESIGN:
        the reviewer's text is a note explaining an exception, not undelivered content. Without
        this a client that posted a headline value alongside the exception would put the file
        straight back into the dead end this closes.
        """
        return bool((row.get("resolution") or "").strip())

    @staticmethod
    def _row_proposal_locators(row: dict) -> list[str]:
        """Every addressable PROPOSAL on a row, in card order.

        Where _row_approved_values answers "what text does this row owe the document", this
        answers "which pieces of content is this row ABOUT" — the question a WCAG exception
        asks, since it is applied to the images themselves and carries no text at all.

        Proposals only. A row's `evidence` entries are addressed by relationship id
        (`part#rId2`, remediate_office), while apply_alt resolves a locator by the element's
        NAME (`part#Picture 3`) — an evidence locator reaches no element, so handing one to a
        writer buys an `apply.unresolved` log line and nothing else.
        """
        seen, out = set(), []
        for p in (row.get("proposals") or []):
            if not isinstance(p, dict):
                continue
            loc = (p.get("locator") or "").strip()
            if loc and loc not in seen:
                seen.add(loc)
                out.append(loc)
        return out
    @staticmethod
    def _row_is_explain_only(row: dict) -> bool:
        """True when EVERY proposal on the row is explain-only (and there is at least one).

        Such a row promises the document nothing, so the counters below must also ignore its
        legacy single `approved_value` column. That column is normally the honest reason a row
        counts forever — a human agreed to some text and we don't know where it goes — but here
        there is nowhere for it to go by design, and the reviewer's headline text is a note about
        a map, not undelivered content. Without this, a client that sent a final value alongside
        the confirmation would put the file straight back into the dead end this closes.

        Deliberately ALL rather than any: a row mixing explain-only and writable proposals still
        owes the document the writable ones, and _row_approved_values keeps that distinction
        per-proposal. No such row exists today (each map card is enqueued alone under its own
        criterion), which is exactly why the mixed case should fail safe rather than silently.
        """
        props = [p for p in (row.get("proposals") or []) if isinstance(p, dict)]
        return bool(props) and all(p.get("explain_only") for p in props)

    @staticmethod
    def companion_name(raw) -> str:
        """A companion filename reduced to a BARE NAME, or "" when there isn't one.

        Sanitised where the value is READ rather than only where it is built, and the reason is
        that the JSON blob is the trust boundary: a row written by an older build, or by a
        proposer someone adds later, has not been through today's builder. The name is derived
        from a media filename out of a customer's estate, it reaches a Content-Disposition header
        and it is the obvious basis for a path — so a `../` in it is a traversal handed to
        whatever writes the file next.

        `PurePosixPath().name` drops every directory component, on either separator, and the
        result is checked against the two names that survive that and still mean a directory.
        """
        import posixpath as _pp
        name = str(raw or "").strip().replace("\\", "/")
        name = _pp.basename(name)
        return "" if name in ("", ".", "..") else name

    @staticmethod
    def _row_companion_files(row: dict) -> dict[str, str]:
        """{filename: content} this row delivers ALONGSIDE the document — never into it.

        The reviewer's `approved_value` wins over the draft, and the fallback is the same one
        `_row_approved_values` argues for: a reviewer who edited nothing has agreed to exactly
        the draft they were shown. Getting this backwards is the quiet failure — a corrected
        caption file and the machine's original are both valid WebVTT, so handing back the wrong
        one looks like nothing at all.

        A row resolved by a WCAG exception yields nothing, for the same reason it yields no
        approved values: the reviewer closed it by judgement and authored no artefact.
        """
        out: dict[str, str] = {}
        if Store._row_is_resolved(row):
            return out
        for p in (row.get("proposals") or []):
            if not isinstance(p, dict):
                continue
            name = Store.companion_name(p.get("companion_file"))
            if not name:
                continue
            # NOT `.strip()`ed, unlike `_row_approved_values`, and the difference is the point.
            # There a value is a STRING going into a document — a stray newline around alt text
            # is noise. Here it is a FILE's bytes: WebVTT is newline-delimited and its trailing
            # newline is part of the artefact, so stripping would hand back a file that differs
            # from the one the reviewer approved. Emptiness is still tested on the stripped form,
            # because a value of only whitespace is not a caption file either.
            val = p.get("approved_value") or ""
            if not val.strip():
                val = p.get("proposed_value") or ""
            if val.strip():
                out[name] = val
        return out

    @staticmethod
    def _row_owes_no_document_content(row: dict) -> bool:
        """True when nothing on this row is content awaiting a write into the document.

        THE PREDICATE THE COUNTERS ASK, replacing `resolved or explain_only` at both call sites.
        A companion row joins that set: a caption file is delivered beside the media and no
        applier will ever write it in, so counting its approved value as outstanding content
        would wedge the file permanently on a correct approval — the exact dead end
        `_row_is_explain_only` was added to close, arriving through a new door.

        Kept as ALL-of, like `_row_is_explain_only`: a row mixing a companion with a writable
        proposal still owes the writable one, and `_row_approved_values` keeps that distinction
        per proposal. No mixed row exists today; the point is that the mixed case fails safe.
        """
        if Store._row_is_resolved(row) or Store._row_is_explain_only(row):
            return True
        props = [p for p in (row.get("proposals") or []) if isinstance(p, dict)]
        return bool(props) and all(Store.companion_name(p.get("companion_file")) for p in props)

    def _approved_unapplied_rows(self, scan_id: str, file: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM hitl_queue WHERE scan_id=%s AND file=%s AND status='approved' "
                "AND (applied IS NULL OR applied=0)", (scan_id, file))
            return [self._decode_proposals(r) for r in self._db.fetchall(cur)]

    def count_unapplied_approved_values(self, scan_id: str, file: str) -> int:
        """Approved items holding content the document does not yet carry.

        A row counts while it has approved content and `applied` is unset. Once
        handlers.apply_approved_values has written those values in and marked the row applied,
        it stops counting and the file may certify — on a re-scan of the written copy, never on
        the approval alone.

        A row whose only approved content is the legacy single `approved_value` column, with no
        proposals to locate it in the document, counts forever: we know a human agreed to some
        text but not where it goes, so we cannot honestly call the file fixed.

        Two kinds of row never count, for the same underlying reason — they promise the
        document no content, so there is nowhere for a legacy value to go. A row resolved by a
        WCAG exception (see _row_is_resolved), and an explain-only row: a confirmed structure or
        heading map, whose value is evidence rather than content awaiting a write (see
        _row_is_explain_only).
        """
        n = 0
        for row in self._approved_unapplied_rows(scan_id, file):
            owes_nothing = self._row_owes_no_document_content(row)
            legacy = "" if owes_nothing else (row.get("approved_value") or "").strip()
            if self._row_approved_values(row) or legacy:
                n += 1
        return n

    def count_unapplied_approved_values_by_file(self, scan_id: str) -> dict[str, int]:
        """Batch form of count_unapplied_approved_values: ONE query for the whole scan, the same
        per-row predicate, keyed by file. scan_status calls this once instead of once per document
        (the 100K-estate hazard its docstring flagged). Files with no counting rows are absent."""
        counts: dict[str, int] = {}
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM hitl_queue WHERE scan_id=%s AND status='approved' "
                "AND (applied IS NULL OR applied=0)", (scan_id,))
            for r in self._db.fetchall(cur):
                row = self._decode_proposals(r)
                owes_nothing = self._row_owes_no_document_content(row)
                legacy = "" if owes_nothing else (row.get("approved_value") or "").strip()
                if self._row_approved_values(row) or legacy:
                    f = str(row.get("file") or "")
                    counts[f] = counts.get(f, 0) + 1
        return counts

    def approved_alt_values(self, scan_id: str, file: str) -> dict[str, str]:
        """{locator: alt text} awaiting a write into `file`, from its approved 1.1.1 rows.

        Scoped to Non-text Content because apply_alt.py writes alt text and nothing else.
        """
        out: dict[str, str] = {}
        for row in self._approved_unapplied_rows(scan_id, file):
            if str(row.get("rule_id") or "").strip() == "1.1.1":
                out.update(self._row_approved_values(row))
        return out

    def approved_decorative_locators(self, scan_id: str, file: str) -> list[str]:
        """The images a reviewer marked DECORATIVE on `file`'s approved 1.1.1 rows.

        A decorative image is not undescribed — it is deliberately undescribed, and WCAG 1.1.1
        asks for it to be marked so, not left blank. Left unmarked the decision lives only in our
        audit log: every future scan re-raises the same finding and the next reviewer decides it
        again, and any other tool reading the file sees a picture missing its alt text.

        So this is a write, not a suppression: handlers._apply_approved_values feeds these
        locators to apply_alt as the DECORATIVE marker (empty descr + the OOXML `adec:decorative`
        marker the analysers already honour — see tests/test_alt_text_decorative_marker.py). The
        row's own `proposed_value` is the card's UI label ("Mark as decorative — no alt text
        needed") and must never reach the document, which is why _row_approved_values drops it.

        Kept separate from approved_alt_values rather than folded in as a magic value, so the
        only lane that can produce a decorative marking is one that asked for it by name — a PDF
        row cannot pick it up (marking a PDF figure decorative means re-tagging it as an
        /Artifact, which no writer here does; that resolution stays a recorded judgement).

        May legitimately return NOTHING for a row that was resolved decorative — a
        `1.1.1/deferred` row, or one whose images are only `evidence` (see
        _row_proposal_locators). The exception still resolves the finding; only the marking is
        unavailable. Certification never depends on this list: the reviewer's judgement is what
        clears the finding, and this write is what stops the next scan asking again.
        """
        out: list[str] = []
        for row in self._approved_unapplied_rows(scan_id, file):
            if (str(row.get("rule_id") or "").strip() == "1.1.1"
                    and (row.get("resolution") or "").strip() == "decorative"):
                out.extend(loc for loc in self._row_proposal_locators(row) if loc not in out)
        return out

    def approved_link_values(self, scan_id: str, file: str) -> dict[str, str]:
        """{locator: link text} awaiting a write into `file`, from its approved 2.4.4/2.4.9 rows.

        Both criteria share proposals.propose_link_texts' locator scheme (the link's resolved
        HREF — see apply_link_text.py's module docstring for why), so one map serves both.
        """
        out: dict[str, str] = {}
        for row in self._approved_unapplied_rows(scan_id, file):
            if str(row.get("rule_id") or "").strip() in ("2.4.4", "2.4.9"):
                out.update(self._row_approved_values(row))
        return out

    def approved_field_values(self, scan_id: str, file: str) -> dict[str, str]:
        """{locator: accessible name} awaiting a write into `file`, from its approved 4.1.2 rows.

        Scoped to Name, Role, Value because the only writer behind it (remediate_pdf's
        `pdf:field:…` → /TU lane) writes form-field accessible names and nothing else.
        """
        out: dict[str, str] = {}
        for row in self._approved_unapplied_rows(scan_id, file):
            if str(row.get("rule_id") or "").strip() == "4.1.2":
                out.update(self._row_approved_values(row))
        return out

    def approved_sensory_values(self, scan_id: str, file: str) -> dict[str, str]:
        """{locator: rewrite} awaiting a write into `file`, from its approved 1.3.3 rows.

        The locator is a sentence prefix, not a part#rId or an href — see
        apply_text_values.py's module docstring for why the two text-span criteria need a
        writer of their own.
        """
        out: dict[str, str] = {}
        for row in self._approved_unapplied_rows(scan_id, file):
            if str(row.get("rule_id") or "").strip() == "1.3.3":
                out.update(self._row_approved_values(row))
        return out

    def approved_language_values(self, scan_id: str, file: str) -> dict[str, str]:
        """{locator: ISO language code} awaiting a write into `file`, from approved 3.1.2 rows.

        Kept apart from the sensory map even though both are text-span keyed: the value is a
        language code rather than prose, the write is an attribute rather than a replacement,
        and each lane may only credit the criterion its own re-scan verified.
        """
        out: dict[str, str] = {}
        for row in self._approved_unapplied_rows(scan_id, file):
            if str(row.get("rule_id") or "").strip() == "3.1.2":
                out.update(self._row_approved_values(row))
        return out

    def approved_structure_label_values(self, scan_id: str, file: str) -> dict[str, str]:
        """{locator: label} awaiting a write into `file`, from approved 2.4.6 xlsx rows.

        Locators are 'sheet:<tab name>' and 'table:<displayName>#col:<colName>', written by
        apply_xlsx_labels. Scoped to xlsx 2.4.6 because the applier renames workbook.xml
        sheet tabs and table column headers — a different write target from link text or alt.
        """
        out: dict[str, str] = {}
        for row in self._approved_unapplied_rows(scan_id, file):
            if str(row.get("rule_id") or "").strip() == "2.4.6":
                out.update(self._row_approved_values(row))
        return out

    def has_approved_values_to_write(self, scan_id: str, file: str) -> bool:
        """True when `file` holds approved content some applier can write into the document.

        The union of every value kind, in one place, because the approve route has to schedule
        the write job on ALL of them: each kind lives in its own hitl row, so a gate naming only
        some of them silently strands the others — the values sit in the database, the document
        never carries them, and the file cannot certify. Add a kind to the handler and it must
        be added here too, or its approvals never reach a job at all.

        "Content" is meant loosely, and deliberately: a decorative marking is a write the
        document owes even though the reviewer approved no text at all. It is a kind like the
        others, and leaving it out would strand it like the others.
        """
        return bool(self.approved_alt_values(scan_id, file)
                    or self.approved_decorative_locators(scan_id, file)
                    or self.approved_link_values(scan_id, file)
                    or self.approved_field_values(scan_id, file)
                    or self.approved_sensory_values(scan_id, file)
                    or self.approved_language_values(scan_id, file)
                    or self.approved_structure_label_values(scan_id, file))

    def approve_proposal_values(self, item_id: str, values: list[str | None]) -> int:
        """Record the reviewer's final text per instance, positionally.

        `values[i]` is the text for instance i: an edited string, or None/"" meaning "accept
        instance i's draft as written". Returns the number of instances now carrying an approved
        value. Extra values are ignored; missing ones fall back to the draft.

        A row's instances are its `proposals` (AI-drafted images) when it has any. When it does
        NOT — a deferred 1.1.1 row that carries only `evidence` thumbnails, because the vision
        model produced no draft — the values are written onto the evidence entries instead, in
        the SAME positional order the card rendered them. Evidence has no draft, so an empty value
        stays empty (the image is still undescribed) rather than falling back to anything.
        """
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT proposals, evidence FROM hitl_queue WHERE id=%s", (item_id,))
            row = self._db.fetchone(cur)
            if not row:
                return 0
            if row.get("proposals"):
                col, has_draft = "proposals", True
            elif row.get("evidence"):
                col, has_draft = "evidence", False
            else:
                return 0
            try:
                items = _json.loads(row[col])
            except (ValueError, TypeError):
                return 0
            n = 0
            for i, p in enumerate(items):
                if not isinstance(p, dict):
                    continue
                supplied = ((values[i] if i < len(values) else None) or "").strip()
                final = (supplied or (p.get("proposed_value") or "").strip()) if has_draft else supplied
                if final:
                    p["approved_value"] = final
                    n += 1
                elif not has_draft:
                    p.pop("approved_value", None)   # cleared: the image is undescribed again
            self._db.execute(cur, f"UPDATE hitl_queue SET {col}=%s WHERE id=%s",
                             (_json.dumps(items), item_id))
        return n

    def mark_row_applied(self, item_id: str) -> None:
        """The approved values on this row are now in the document."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE hitl_queue SET applied=1 WHERE id=%s", (item_id,))

    def approved_unapplied_item_ids(self, scan_id: str, file: str, rule_id: str) -> list[str]:
        return [r["id"] for r in self._approved_unapplied_rows(scan_id, file)
                if str(r.get("rule_id") or "").strip() == rule_id]

    def mark_file_compliant_if_reviewed(self, scan_id: str, file: str) -> bool:
        """After a HITL resolution: a REMEDIATED file whose every HITL item is 'approved' AND
        whose approvals required no unwritten content is fully conformant. Flip
        file_records.compliant=1 and set score=100 so it advances to Publish (Publish gates on
        f.compliant), then refresh the scan aggregate (certifiable = Σcompliant).

        Approval is the gate ONLY for a JUDGEMENT finding — one whose resolution IS the human
        sign-off, with no new content to write (a contrast ratio accepted, a link text deemed
        adequate as it stands). A plain re-scan of the fixed copy cannot clear those, so
        approval must.

        Approval is NOT the gate for a VALUE-FIX finding. Approving an alt-text value records
        the text; the document does not carry it until handlers.apply_approved_values writes it
        in and a re-scan confirms the criterion cleared. Certifying on the approval alone marked
        a PPTX 100/100 and conformant with WCAG 1.1.1 while its ten images were still
        undescribed. A file carrying an approved-but-unapplied value stays non-conformant until
        that value is actually applied and re-scanned — which is what `applied` records.

        Idempotent: an already-compliant file, an un-remediated file, one with any item still
        pending / rejected / skipped, or one with an approved-but-unapplied value returns
        False and changes nothing."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT compliant, remediated_at FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            rec = self._db.fetchone(cur)
            if not rec or not rec.get("remediated_at") or rec.get("compliant"):
                return False
            self._db.execute(cur,
                "SELECT status, COUNT(*) AS n FROM hitl_queue WHERE scan_id=%s AND file=%s "
                "GROUP BY status", (scan_id, file))
            counts = {r["status"]: r["n"] for r in self._db.fetchall(cur)}
        total = sum(counts.values())
        if total == 0 or counts.get("approved", 0) != total:
            return False   # still items pending / rejected / skipped — not fully resolved
        if self.count_unapplied_approved_values(scan_id, file):
            return False   # approved content that no remediator ever wrote into the document
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE file_records SET compliant=1, score=100, status='pass' "
                "WHERE scan_id=%s AND file=%s", (scan_id, file))
        # The certification MOMENT is a fact worth recording (ADR 0026 Epic 5): one immutable
        # decision-log row gives the Assessment Timeline's Certification stage a real timestamp —
        # without it the stage could only be inferred, and we don't fabricate events (ADR 0016).
        try:
            self.log_decision("system", "file.certified", scan_id=scan_id, file=file,
                              detail="All review items approved; no unapplied approved content")
        except Exception:
            # certification itself must not fail on a logging error
            swallowed("store.mark_file_compliant_if_reviewed: logging the revalidation decision "
                      "failed", scan_id)
        self.refresh_scan_aggregate(scan_id)
        return True

    def list_hitl_queue(self, status: str | None = None, scan_id: str | None = None,
                        owner: str | None = None, include_superseded: bool = False) -> list[dict]:
        """List HITL items. `owner` scopes to the signed-in user's own documents (joined via
        the scan's owner_email) — the inbox must not show another tenant's review items.

        Review items for ACP's OWN remediated copies are dropped, exactly as get_scan drops
        those files from the dashboard. Without this a scan showing one document showed two
        identical review cards, the second asking a human to write alt text for the file ACP
        itself produced — and the vision proposals landed on that phantom's row, so opening the
        real document's card showed no AI draft at all.

        SUPERSEDED items are dropped too — see _superseded_items. Pass include_superseded=True
        to get them back, each annotated with `superseded: True`; that is the audit view.

        Same posture as get_scan: this filters the READ. The rows stay on disk, so the audit
        trail of what was queued is never destroyed."""
        conds, params = [], []
        if status:
            conds.append("status=%s"); params.append(status)
        if scan_id:
            conds.append("scan_id=%s"); params.append(scan_id)
        if owner:
            conds.append("scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)"); params.append(owner)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        with self._db.cursor() as cur:
            self._db.execute(cur, f"SELECT * FROM hitl_queue{where} ORDER BY created_at DESC", tuple(params))
            rows = [self._decode_proposals(r) for r in self._db.fetchall(cur)]
            if not rows:
                return rows
            # Per scan, never globally: 'deck (1).pptx' shadows a source in one scan and is a
            # document in its own right in another, where no unstamped sibling exists.
            shadowed: set[tuple[str, str]] = set()
            for sid in {r["scan_id"] for r in rows}:
                shadowed.update((sid, f) for f in self._shadowed_files(cur, sid))
            rows = [r for r in rows if (r["scan_id"], r["file"]) not in shadowed]
            superseded = self._superseded_items(cur, rows)
        if include_superseded:
            for r in rows:
                r["superseded"] = r["id"] in superseded
            return rows
        return [r for r in rows if r["id"] not in superseded]

    def _superseded_items(self, cur, rows: list[dict]) -> set[str]:
        """The ids of queue rows whose finding has stopped being work.

        queue_hitl_items is additive and idempotent, and nothing in api/ ever withdrew a row.
        scan_rule_traces, meanwhile, refresh: save_file_result upserts them ON CONFLICT
        DO UPDATE SET outcome. So a re-scan or a remediation that clears a FAIL updated the
        trace and left the queue row pending forever, inflating the one number a reviewer
        plans their day around.

        A row is superseded when its (scan, file, criterion) trace now reads PASS or
        NOT_EVALUATED. Deliberately NOT on REVIEW: almost no ai-assisted criterion can reach
        PASS at all — 1.1.1, 1.4.5, 2.4.4 and 3.1.2 land on REVIEW for every format, because
        the detector finds whether alt text EXISTS and cannot certify that it is any good. For
        those, REVIEW is precisely "a human still has to look", which is the item's whole
        reason to exist. Retracting on REVIEW would empty the inbox of exactly the work it is
        for.

        Three things are never retracted:
          - Rows a human already decided (status != 'pending'). An approved item is the record
            of a decision, not a work-list entry; its finding passing now is the CONSEQUENCE of
            that approval, and hiding it would erase the reason the document certifies.
          - Rows with no trace at all — deferrals ('1.1.1/deferred') and post-fix verification
            ('auto/verify') carry rule_ids that scan_rule_traces never holds. Absence of a
            trace is not evidence of a pass.
          - Anything whose trace still reads FAIL or REVIEW.

        Computed at read time rather than stamped into a column. A column needs a writer at
        every site that touches an outcome, and one missed site leaves a row lying in the
        opposite direction — a retracted item that never comes back. Deriving it from the
        trace cannot drift, and it self-heals: a criterion that regresses to FAIL reappears in
        the inbox with no sweep to run."""
        pending = [r for r in rows if (r.get("status") or "pending") == "pending"]
        if not pending:
            return set()
        outcomes: dict[tuple[str, str, str], str] = {}
        for sid in {r["scan_id"] for r in pending}:
            self._db.execute(cur,
                "SELECT file, rule_id, outcome FROM scan_rule_traces WHERE scan_id=%s", (sid,))
            for t in self._db.fetchall(cur):
                outcomes[(sid, t["file"], t["rule_id"])] = t["outcome"]
        return {r["id"] for r in pending
                if outcomes.get((r["scan_id"], r["file"], r["rule_id"])) in _SUPERSEDING_OUTCOMES}

    def _shadowed_files(self, cur, scan_id: str) -> set[str]:
        """The files in this scan that are ACP's own output shadowing their source."""
        self._db.execute(cur,
            "SELECT file, acp_stamped FROM file_records WHERE scan_id=%s", (scan_id,))
        return shadowed_acp_outputs(self._db.fetchall(cur))

    def is_shadowed_output(self, scan_id: str, file: str) -> bool:
        """Is this file ACP's OWN remediated copy, shadowing the source it was made from?

        The single predicate behind every "don't touch ACP's own artifact" decision, so the
        dashboard (get_scan), the review inbox (list_hitl_queue) and the remediation worker
        cannot drift apart on what counts as a shadow.

        Note this is DATA-dependent: it reads file_records.acp_stamped, written by
        detect_acp_stamp at scan time. A scan taken before stamping existed carries NULL
        stamps, so its copies are indistinguishable from real documents and will be treated
        as such — the filter cannot retroactively know what it never recorded."""
        with self._db.cursor() as cur:
            return file in self._shadowed_files(cur, scan_id)

    def get_hitl_item(self, item_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM hitl_queue WHERE id=%s", (item_id,))
            return self._decode_proposals(self._db.fetchone(cur))

    @staticmethod
    def _decode_proposals(row: dict | None) -> dict | None:
        """Parse the hitl_queue `proposals` and `evidence` JSON columns into real lists so
        callers/the API get [{locator, proposed_value, …}] / [{locator, thumb}], not raw
        strings. No-op when absent/legacy."""
        if not row:
            return row
        import json as _json
        for col in ("proposals", "evidence"):
            if row.get(col):
                try:
                    row[col] = _json.loads(row[col])
                except (ValueError, TypeError):
                    row[col] = []
        return row

    def update_hitl_item(self, item_id: str, status: str, reviewer_note: str | None = None,
                         approved_value: str | None = None, *,
                         resolution: str | None = None) -> dict | None:
        """approved_value: the reviewer's final (AI-drafted or hand-edited) text for a
        semantic finding — e.g. alt text / link text. COALESCE so a reject/skip call
        (which never passes one) never clobbers a value set by an earlier approve.

        resolution: the WCAG exception applied INSTEAD of a value ('decorative',
        'essential_exception'), or None for an ordinary decision. ASSIGNED, not COALESCEd, and
        deliberately so: a reviewer who marked an image decorative and then came back to write
        real alt text must end up with the alt text written, and a rejection must un-resolve the
        finding. The one production caller (routes/hitl.py) restates the reviewer's actual choice
        on every decision, so plain assignment is what the reviewer last said."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE hitl_queue SET status=%s, reviewed_at=%s, reviewer_note=%s, "
                "approved_value=COALESCE(%s, approved_value), resolution=%s WHERE id=%s",
                (status, now, reviewer_note, approved_value, resolution, item_id))
        return self.get_hitl_item(item_id)

    def assign_hitl_item(self, item_id: str, assignee: str | None) -> dict | None:
        """Set or clear the reviewer assigned to a HITL item. Separate from update_hitl_item
        so assignment can happen without also recording a review decision."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE hitl_queue SET assignee=%s WHERE id=%s", (assignee, item_id))
        return self.get_hitl_item(item_id)

    def claim_hitl_item(self, item_id: str, claimant: str | None) -> dict | None:
        """Transition a queue item to 'in_review' and record the claimant as assignee.
        Deliberately does NOT set reviewed_at — in_review is a 'I am working this' signal,
        not a terminal decision. update_hitl_item handles approved/rejected/skipped."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE hitl_queue SET status='in_review', assignee=COALESCE(%s, assignee) WHERE id=%s",
                (claimant, item_id))
        return self.get_hitl_item(item_id)

    # ── Admin settings (persisted; survives restarts) ─────────────────────────
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT value FROM app_settings WHERE key=%s", (key,))
            row = self._db.fetchone(cur)
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO app_settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (key, value))

    # ── Per-user setting overrides (R7: owner default + per-user override) ─────────────────────
    # A per-user override is stored as an ordinary app_settings row under a namespaced key, so it
    # needs no schema change and inherits the settings table's persistence and RESET treatment. The
    # namespace carries the owner email verbatim; a ':' in an email is not valid, so the three-part
    # "user:<email>:<key>" split is unambiguous. Nothing here changes what a scan resolves — the
    # scan-time precedence (override > owner default) is a separate, reviewed change on the scope hot
    # path (assessment_policy.active_scope); this is only the storage + resolution primitive it will
    # read. See ADR 0035.
    @staticmethod
    def _user_setting_key(user: str, key: str) -> str:
        return f"user:{user}:{key}"

    def set_user_setting(self, user: str, key: str, value: str) -> None:
        """Store a per-user override for `key`. An empty string is a real value (it clears a scope),
        distinct from having no override at all — use clear_user_setting to remove the override."""
        self.set_setting(self._user_setting_key(user, key), value)

    def get_user_setting(self, user: str, key: str) -> str | None:
        """This user's override for `key`, or None when they have none. None is the signal to fall
        back to the owner default — an override that is present but empty ("") is NOT None."""
        return self.get_setting(self._user_setting_key(user, key), None)

    def clear_user_setting(self, user: str, key: str) -> None:
        """Remove this user's override so `key` falls back to the owner default. Idempotent."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM app_settings WHERE key=%s",
                             (self._user_setting_key(user, key),))

    def resolve_setting(self, key: str, user: str | None = None, default: str | None = None) -> str | None:
        """The EFFECTIVE value of `key` for `user`: their own override if they have one, else the
        owner/global default, else `default`. Precedence, highest first:
          1. the user's per-user override (present even if empty)
          2. the global (owner) setting
          3. `default`
        With `user=None` this is exactly get_setting — a caller with no user asks only the global."""
        if user is not None:
            override = self.get_user_setting(user, key)
            if override is not None:
                return override
        return self.get_setting(key, default)

    # ── Scheduled-sweep outcome ───────────────────────────────────────────────
    # A sweep that cannot reach its source deliberately saves NOTHING and leaves the last real
    # scan standing (core._do_scheduled_scan; the alternative — substituting the bundled samples
    # — displaced a 258-document estate every five minutes). That is the right call about the
    # DATA and the wrong one about the UI: with only a container log line, every surface goes on
    # presenting a scan from hours ago as the current estate, with nothing saying it is stale.
    # Recorded here so /schedule can report it and the UI can say so. Same trust problem as the
    # dashboard contradictions: a number nobody can date is a number nobody can act on.
    _SWEEP_KEY = "last_sweep"

    def record_sweep_outcome(self, *, ok: bool, when: str, source: str,
                             scan_id: str | None = None, files: int | None = None,
                             error: str | None = None, skipped: bool = False) -> None:
        """Persist the most recent scheduled sweep's outcome. Best-effort: a sweep must not fail
        because its bookkeeping did.

        `skipped=True` (source='drive' only, when a sync cursor confirms nothing changed) means
        no scan ran at all — deliberately NOT recorded as files=0, which already has a different
        meaning here (a scan DID run and legitimately saw zero files under the sweep's limited
        ADC identity). Conflating the two would recreate exactly the "sweep outcome
        indistinguishable from a collapse" failure mode this method exists to prevent — see
        /monitor/estate's own comment on telling a sweep apart from a real collapse."""
        import json as _json
        try:
            self.set_setting(self._SWEEP_KEY, _json.dumps({
                "ok": bool(ok), "at": when, "source": source,
                "scan_id": scan_id, "files": files, "skipped": bool(skipped),
                # Truncated: this reaches the browser, and a Google HttpError repr carries the
                # full request URL. Enough to recognise the failure, not a wall of query string.
                "error": (error or None) and str(error)[:400],
            }))
        except Exception:
            swallowed("store.record_sweep_outcome: recording the sweep outcome failed", scan_id)

    def get_last_sweep(self) -> dict | None:
        """The last recorded sweep outcome, or None if none has run since this was added."""
        import json as _json
        raw = self.get_setting(self._SWEEP_KEY)
        if not raw:
            return None
        try:
            return _json.loads(raw)
        except Exception:
            return None

    def ping(self) -> None:
        """One cheap round-trip to the database. Returns nothing; raises if it cannot be done.

        WHAT THIS IS FOR, AND WHY IT READS NO TABLE. The container-local readiness probe
        (routes/system.py `probe_readyz`) has to answer one question — can THIS process reach
        the database and get an answer back — and it has to answer it about the replica the
        platform is deciding whether to send traffic to. Any query over real data would make
        the answer depend on what happens to be stored, which is a different question and one
        a rollout gate must not be able to fail on. `SELECT 1` still exercises the whole path:
        pool checkout, socket, server, response parse.

        Deliberately NOT bounded here. `_getconn` already caps the pool wait at 5s, and the
        probe's own `timeoutSeconds` bounds the rest from outside the process; a second timeout
        inside would be a third number to keep in sync with those two, and it could not stop
        the underlying thread anyway. See probe_readyz for how a hung ping is prevented from
        piling up.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT 1")
            self._db.fetchone(cur)

    # Every role a worker container can be started as (core._worker_job_types validates the same
    # set). Enumerated rather than discovered by scanning app_settings for a key prefix: the set
    # is closed and small, and a prefix scan would silently start reporting any future key that
    # happened to share the namespace.
    WORKER_ROLES = ("mixed", "discovery", "assess", "remediate", "processing")

    def worker_roles_status(self, window_s: int = 120) -> dict:
        """Per-ROLE heartbeat, keyed by role. The shared key cannot answer this.

        WHY THIS EXISTS. worker_main writes its beat TWICE (worker_main.py:105-106): once to
        `worker_tier_heartbeat`, and once to `worker_tier_heartbeat:<role>`. `worker_tier_status`
        reads only the first, which is a single row — so with more than one worker service
        running (acp-worker and acp-discovery, since #1169), it reports WHICHEVER BEAT LAST.

        That is not a hypothetical. Measured against production on 2026-09-01, sampling /readyz
        every 6s for 90s while the app was on 2026.9.1.23:

            2026.8.31.39  pool=2   x13
            2026.8.31.20  pool=3   x1

        Two services alternating in one field. Read as a single tier, that looks like a version
        flapping at random; read per role, it is two services each with its own answer. Anything
        that compares "the worker version" against an expected build — a deploy check, a monitor,
        an operator — needs the second reading, because the first is a coin toss between services.

        A role absent from the result has never beaten under that key. That is deliberately
        distinct from a role that beat and went stale (present, `alive` false, with an age), the
        same distinction `worker_tier_status` draws for the tier as a whole.
        """
        from datetime import datetime, timezone
        out: dict[str, dict] = {}
        for role in self.WORKER_ROLES:
            raw = self.get_setting(f"worker_tier_heartbeat:{role}")
            if not raw:
                continue
            iso, pool_size, version = _parse_worker_tier_heartbeat(raw)
            entry = {"heartbeat_at": iso or None, "age_s": None, "alive": False,
                     "pool_size": pool_size, "version": version}
            try:
                beat = datetime.fromisoformat(iso)
            except (ValueError, TypeError):
                # Same posture as worker_tier_status: a corrupt timestamp is a real fault and must
                # not read as "never started". Reported against the ORIGINAL value.
                entry["heartbeat_at"] = f"unparseable: {raw!r}"
                out[role] = entry
                continue
            if beat.tzinfo is None:
                beat = beat.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - beat).total_seconds()
            entry["age_s"] = round(age, 1)
            entry["alive"] = age <= window_s
            out[role] = entry
        return out

    def worker_tier_status(self, window_s: int = 120) -> dict:
        """The heartbeat with its AGE, not just a boolean.

        `worker_tier_alive` answers the scan-start guard's yes/no question, which is all that
        guard needs. It is useless for alerting: "false" cannot distinguish a worker that died
        thirty seconds ago from one that has been gone for a fortnight, and those want different
        responses. This returns the timestamp and its age so a monitor can say which.

        Age is None when no worker has EVER beaten — a fresh deploy that never started its
        worker tier, which is a different failure from one that stopped, and reads differently
        in an alert.

        `pool_size` is the worker container's own `core.WORKERS` at process start, carried in
        the heartbeat's JSON envelope (see `_parse_worker_tier_heartbeat`). It's None when the
        beat is old-format (bare ISO string) or never carried one — never a crash either way.

        `version` is the worker image's ACP_BUILD_VERSION, and it is the only way to learn which
        image the worker tier is running: acp-worker has no ingress, so nothing can ask it
        directly, and app and worker deploy from different images with nothing sequencing them
        (ADR 0045 §6). Compare it against /healthz's `version` to see whether a deploy reached
        both tiers. None means the beat predates the field — which is itself the answer, not a
        gap — and is deliberately not conflated with "dev" (an image that never went through
        deploy.sh). See _parse_worker_tier_heartbeat for why those must stay distinct.
        """
        from datetime import datetime, timezone
        raw = self.get_setting("worker_tier_heartbeat")
        out = {"alive": False, "heartbeat_at": raw or None, "age_s": None,
               "window_s": window_s, "ever_seen": bool(raw), "pool_size": None,
               "version": None}
        if not raw:
            return out
        iso, pool_size, version = _parse_worker_tier_heartbeat(raw)
        out["pool_size"] = pool_size
        out["version"] = version
        out["heartbeat_at"] = iso or None
        try:
            beat = datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            # A malformed timestamp is a real fault, not "no heartbeat" — say so rather than
            # letting it read identically to a tier that never started. Report against the
            # ORIGINAL raw value, not the JSON-unwrapped `iso`, so a garbage JSON envelope
            # (or garbage bare string) shows the actual stored value in the error.
            out["heartbeat_at"] = f"unparseable: {raw!r}"
            return out
        if beat.tzinfo is None:
            beat = beat.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - beat).total_seconds()
        out["age_s"] = round(age, 1)
        out["alive"] = age <= window_s
        return out

    def worker_tier_alive(self, window_s: int = 120) -> bool:
        """True if a standalone worker container (worker_main, #113) beat within `window_s`.

        The API tier runs ACP_WORKERS=0 in the split topology, so the scan-start "are there
        workers?" guard must look here, not at its local pool. Freshness-based on a real
        heartbeat — a dead worker goes stale and the guard correctly refuses again.
        """
        from datetime import datetime, timedelta, timezone
        raw = self.get_setting("worker_tier_heartbeat")
        if not raw:
            return False
        iso, _pool_size, _version = _parse_worker_tier_heartbeat(raw)
        try:
            beat = datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            return False
        if beat.tzinfo is None:
            beat = beat.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - beat <= timedelta(seconds=window_s)

    def get_allowlist(self) -> list[str]:
        """Runtime-editable allowed emails (managed from Settings), lowercased."""
        raw = self.get_setting("allowed_emails", "") or ""
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def set_allowlist(self, emails: list[str]) -> list[str]:
        clean = sorted({e.strip().lower() for e in (emails or []) if e and "@" in e})
        self.set_setting("allowed_emails", ",".join(clean))
        return clean

    def get_people(self) -> list[dict]:
        """Durable onboarding metadata; the allowlist remains the login gate."""
        import json as _json
        try:
            rows = _json.loads(self.get_setting("people_records", "[]") or "[]")
        except (TypeError, ValueError):
            rows = []
        return sorted((r for r in rows if isinstance(r, dict) and r.get("email")),
                      key=lambda r: r["email"])

    def upsert_person(self, person: dict) -> dict:
        import json as _json
        email = (person.get("email") or "").strip().lower()
        rows = {r["email"]: r for r in self.get_people()}
        rows[email] = {**rows.get(email, {}), **person, "email": email}
        self.set_setting("people_records", _json.dumps(list(rows.values()), sort_keys=True))
        return rows[email]

    def remove_person(self, email: str) -> None:
        import json as _json
        target = (email or "").strip().lower()
        rows = [r for r in self.get_people() if r.get("email") != target]
        self.set_setting("people_records", _json.dumps(rows, sort_keys=True))

    def get_admins(self) -> list[str]:
        """Runtime-editable additional Platform Admins (managed from Settings → Users), lowercased.
        Distinct from the env grants: ACP_OWNER_EMAIL (the immutable owner) and ACP_ADMIN_EMAILS
        (permanent, set at deploy) are NOT stored here — this is only the UI-managed set the owner
        can promote/demote. `core.is_admin` unions all three."""
        raw = self.get_setting("admin_emails", "") or ""
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def set_admins(self, emails: list[str]) -> list[str]:
        clean = sorted({e.strip().lower() for e in (emails or []) if e and "@" in e})
        self.set_setting("admin_emails", ",".join(clean))
        return clean

    def list_ai_provider_configs(self) -> list[dict]:
        """All configured AI gateway providers (ADR 0019 §6) — NON-SECRET config only. There is
        no key column: `key_secret_ref` names the environment/Key-Vault secret the adapter reads
        at call time, so this method can never leak a credential."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT provider,enabled,endpoint,deployment,model,key_secret_ref,updated_at,updated_by "
                "FROM ai_provider_config ORDER BY provider")
            rows = self._db.fetchall(cur)
        for r in rows:
            r["enabled"] = bool(r.get("enabled"))
        return rows

    def get_ai_provider_config(self, provider: str) -> dict | None:
        """One provider's non-secret config, or None if never configured."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT provider,enabled,endpoint,deployment,model,key_secret_ref,updated_at,updated_by "
                "FROM ai_provider_config WHERE provider=%s", (provider,))
            r = self._db.fetchone(cur)
        if r:
            r["enabled"] = bool(r.get("enabled"))
        return r

    def upsert_ai_provider_config(self, provider: str, *, enabled: bool, endpoint: str | None,
                                  deployment: str | None, model: str | None,
                                  key_secret_ref: str | None, updated_by: str | None = None) -> None:
        """Write a provider's NON-SECRET config (ADR 0019 §6). The caller must have rejected any
        key value before reaching here — only a secret *reference name* is ever persisted."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO ai_provider_config(provider,enabled,endpoint,deployment,model,"
                "key_secret_ref,updated_at,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(provider) DO UPDATE SET enabled=EXCLUDED.enabled,"
                "endpoint=EXCLUDED.endpoint,deployment=EXCLUDED.deployment,model=EXCLUDED.model,"
                "key_secret_ref=EXCLUDED.key_secret_ref,updated_at=EXCLUDED.updated_at,"
                "updated_by=EXCLUDED.updated_by",
                (provider, 1 if enabled else 0, endpoint, deployment, model,
                 key_secret_ref, now, updated_by))

    # ── Enterprise review memory (ADR 0021) ───────────────────────────────────
    def add_org_memory(self, org: str, kind: str, guidance: str, *, rule_id: str | None = None,
                       format: str | None = None, status: str = "active",
                       evidence: str | None = None, author: str | None = None) -> str:
        """Insert one org_memory rule and return its id. Admin-authored `style`/`glossary`
        default to 'active'; the derivation job (ADR 0021 §D) inserts `derived` rows as
        'proposed' — inert until an admin accepts (set_org_memory_status → 'active')."""
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        mid = uuid.uuid4().hex[:12]
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO org_memory(id,org,kind,rule_id,format,guidance,status,evidence,"
                "author,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (mid, org, kind, rule_id, format, guidance, status, evidence, author, now, now))
        return mid

    def list_org_memory(self, org: str, *, status: str | None = None) -> list[dict]:
        """An org's memory rules (optionally filtered by status), newest first. Org-isolated:
        never returns another tenant's rules."""
        with self._db.cursor() as cur:
            if status:
                self._db.execute(cur,
                    "SELECT * FROM org_memory WHERE org=%s AND status=%s ORDER BY created_at DESC",
                    (org, status))
            else:
                self._db.execute(cur,
                    "SELECT * FROM org_memory WHERE org=%s ORDER BY created_at DESC", (org,))
            return self._db.fetchall(cur)

    def set_org_memory_status(self, org: str, mid: str, status: str) -> bool:
        """Accept ('active'), dismiss/retire ('archived'), or re-propose a rule. Org-scoped so
        one tenant can't touch another's memory. Returns True if the row exists and was set."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE org_memory SET status=%s, updated_at=%s WHERE id=%s AND org=%s",
                (status, now, mid, org))
            self._db.execute(cur,
                "SELECT status FROM org_memory WHERE id=%s AND org=%s", (mid, org))
            row = self._db.fetchone(cur)
        return bool(row and row.get("status") == status)

    def list_org_owners(self) -> list[str]:
        """Distinct scan owners — the orgs the nightly derivation job iterates (ADR 0021)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT DISTINCT owner_email FROM scan_runs WHERE owner_email IS NOT NULL")
            return [r["owner_email"] for r in self._db.fetchall(cur) if r.get("owner_email")]

    def list_hitl_events_for_org(self, org: str, *, since_iso: str | None = None,
                                 limit: int = 5000) -> list[dict]:
        """Every HITL decision across an ORG's scans (joined via scan_runs.owner_email) —
        the raw learning signal ADR 0021's derivation job reads. Org-isolated: an org's memory
        can only ever derive from that org's own reviewers. `since_iso` windows to recent
        behaviour (recency, ADR 0021 §D)."""
        with self._db.cursor() as cur:
            if since_iso:
                self._db.execute(cur,
                    "SELECT e.* FROM hitl_events e JOIN scan_runs r ON e.scan_id=r.id "
                    "WHERE r.owner_email=%s AND e.created_at>=%s ORDER BY e.created_at DESC LIMIT %s",
                    (org, since_iso, limit))
            else:
                self._db.execute(cur,
                    "SELECT e.* FROM hitl_events e JOIN scan_runs r ON e.scan_id=r.id "
                    "WHERE r.owner_email=%s ORDER BY e.created_at DESC LIMIT %s", (org, limit))
            return self._db.fetchall(cur)

    def memory_applied_rules(self, org: str, rule_id: str | None,
                             format: str | None) -> list[dict]:
        """The ACTIVE org_memory ROWS that apply to a (org, rule, format) draft, ordered
        most-specific-first (rule+format > rule > format > org-wide). Only 'active' rules —
        'proposed'/'derived' never influence a draft until accepted (ADR 0021 §D).

        This is the ONE selection. `memory_guidance` (what goes into the prompt) is this list
        mapped to its guidance strings, and the card's "house style applied" chip renders these
        same rows — so the chip cannot name a rule the prompt did not actually receive, or miss
        one it did. Splitting the two into parallel implementations is the failure this shape
        exists to prevent: the chip is a claim about what shaped a draft a human is about to
        certify, and a claim derived from a second, drifting copy of the specificity rules is
        exactly the invisible dishonesty ADR 0021 §E forbids.

        Each row carries `kind` and `evidence` as well as the guidance, because an ACCEPTED
        derived rule stays `kind='derived'` (acceptance flips status, not kind) and keeps the
        count that justified it — which is what the chip expands to show (ADR 0016)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,rule_id,format,guidance,kind,evidence FROM org_memory "
                "WHERE org=%s AND status='active'", (org,))
            rows = self._db.fetchall(cur)

        def applies(r) -> bool:
            return ((r.get("rule_id") in (None, "", rule_id))
                    and (r.get("format") in (None, "", format)))

        def specificity(r) -> int:
            return (2 if r.get("rule_id") else 0) + (1 if r.get("format") else 0)

        keep = [r for r in rows if applies(r)]
        keep.sort(key=specificity, reverse=True)
        # De-dup identical guidance text (an org-wide + a rule-scoped copy) while keeping order.
        seen: set[str] = set()
        out: list[dict] = []
        for r in keep:
            g = (r.get("guidance") or "").strip()
            if g and g not in seen:
                seen.add(g)
                out.append({"id": r.get("id"), "kind": r.get("kind"), "guidance": g,
                            "rule_id": r.get("rule_id"), "format": r.get("format"),
                            "evidence": r.get("evidence")})
        return out

    def memory_guidance(self, org: str, rule_id: str | None, format: str | None) -> list[str]:
        """The ACTIVE guidance fragments that apply to a (org, rule, format) draft, ordered
        most-specific-first. The raw strings the caller composes into the prompt — the same
        rows `memory_applied_rules` returns, in the same order, by construction rather than by
        a matching second implementation."""
        return [r["guidance"] for r in self.memory_applied_rules(org, rule_id, format)]

    def get_ai_enabled(self) -> bool:
        """Platform AI mode. Defaults to enabled; admin can hard-disable it
        (deterministic-only mode) — which overrides any per-scan ?ai=true."""
        return self.get_setting("ai_enabled", "true") != "false"

    def set_ai_enabled(self, enabled: bool) -> None:
        self.set_setting("ai_enabled", "true" if enabled else "false")

    def get_auto_apply_validated(self) -> bool:
        """Auto-apply policy for CROSS-CHECKED vision drafts (opt-in, default OFF). When on,
        an ungrounded alt draft that an independent second reading confirms ('consistent'
        consistency cross-check — a measurement, never a model's self-assessment, ADR 0016)
        is applied inline like a grounded one instead of queueing for one-click approval.
        The provenance string on the fix says exactly that, and the re-scan verify gate
        still decides whether the criterion actually cleared."""
        return self.get_setting("auto_apply_validated", "false") == "true"

    def set_auto_apply_validated(self, enabled: bool) -> None:
        self.set_setting("auto_apply_validated", "true" if enabled else "false")

    def get_drive_mirror_enabled(self) -> bool:
        """ADR 0010: whether a successful Blob remediation is also auto-mirrored to
        Drive. Defaults to enabled (the original ADR 0010 behavior). Off = Blob-only;
        a Drive copy can still be produced on demand elsewhere (e.g. FileDrawer's own
        upload-to-drive action), just not automatically after every remediation."""
        return self.get_setting("drive_mirror_enabled", "true") != "false"

    def set_drive_mirror_enabled(self, enabled: bool) -> None:
        self.set_setting("drive_mirror_enabled", "true" if enabled else "false")

    def get_drive_mirror_folder(self) -> str:
        """Drive folder name remediated copies are mirrored into. Defaults to the
        original hardcoded 'Remediated'."""
        return self.get_setting("drive_mirror_folder", "Remediated")

    def set_drive_mirror_folder(self, folder: str) -> None:
        self.set_setting("drive_mirror_folder", folder)

    # ── Immutable decision audit log ──────────────────────────────────────────
    def log_decision(self, actor: str, action: str, *, scan_id: str | None = None,
                     file: str | None = None, rule_id: str | None = None,
                     detail: str | None = None) -> None:
        """Append one row to the immutable decision log. Never updated/deleted."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO decision_log(id,ts,actor,action,scan_id,file,rule_id,detail) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (uuid.uuid4().hex[:12], now, actor, action, scan_id, file, rule_id, detail))

    def list_decisions(self, scan_id: str | None = None, limit: int = 500) -> list[dict]:
        with self._db.cursor() as cur:
            if scan_id:
                self._db.execute(cur,
                    "SELECT * FROM decision_log WHERE scan_id=%s ORDER BY ts DESC LIMIT %s",
                    (scan_id, limit))
            else:
                self._db.execute(cur,
                    "SELECT * FROM decision_log ORDER BY ts DESC LIMIT %s", (limit,))
            return self._db.fetchall(cur)

    # ── Durable scan-lifecycle event log (ADR 0042) ───────────────────────────
    #
    # NO CALLER YET, deliberately: this is PR 1 of the ADR's four, which lands the table and its
    # two accessors with zero behaviour change so the emit sites (PR 2) and the read surface
    # (PR 3) can be reviewed on their own. See the schema comment on scan_events for what may be
    # written here and — more importantly — what may not.

    # The closed set of lifecycle transitions. Closed on purpose: a reader (PR 3's history view)
    # renders per-kind, so a typo'd or ad-hoc kind is a row nothing knows how to display. Extend
    # it by ADR amendment, not in passing.
    SCAN_EVENT_KINDS = frozenset({
        "scan.queued", "scan.claimed", "scan.listing_started", "scan.listing_complete",
        "scan.inventory_saved", "scan.lifecycle_applied", "scan.discovered",
        "scan.assess_started", "scan.retrying", "scan.paused", "scan.resumed",
        "scan.cancelled", "scan.completed", "scan.failed", "scan.interrupted",
    })

    _SCAN_EVENT_SEQ_ATTEMPTS = 4

    def append_scan_event(self, scan_id: str, kind: str, *, phase: str | None = None,
                          job_id: str | None = None, worker_id: str | None = None,
                          attempt: int | None = None, detail: dict | None = None,
                          owner_email: str | None = None,
                          occurred_at: str | None = None) -> int | None:
        """Append one lifecycle event and return its per-scan `seq` (None if it was not written).

        RAISES on a bad `kind` or a missing `scan_id`, and only on those — they are programming
        errors a test must catch, not runtime conditions. Every other failure is swallowed and
        returns None: PR 2's call sites wrap this anyway, but the contract belongs here, next to
        the write, exactly as activity.py holds it ("a progress line must never be able to fail
        the work it describes"). A missing row is a gap in narration; it is never a wrong
        statement, because nothing is ever overwritten.

        `seq` IS ASSIGNED BY THE INSERT, in one statement:

            INSERT INTO scan_events (...) SELECT %s, ..., COALESCE(MAX(seq),0)+1, ...
              FROM scan_events WHERE scan_id = %s

        One statement because there is no transaction to hold a read and a write together — the
        SQLite adapter opens a fresh connection per cursor() — and because an aggregate with no
        GROUP BY returns exactly one row even over an empty table, so the first event of a scan
        gets seq=1 without a special case. Two writers racing produce the same seq and the UNIQUE
        index rejects the loser, which is the point: the loser retries and gets the next number,
        instead of the event being silently dropped. Measured on a 12-thread race against a real
        store: this design landed 12/12 with a gap-free sequence, while SELECT-then-INSERT landed
        2/12 and lost the other ten (see test_scan_events_store.py). Retries are bounded — a
        contended write is not worth blocking a scan thread on, and by design this path is barely
        contended (run-level transitions come one at a time per job).

        `detail` is a dict, stored as JSON. Keep it small and narrative.
        """
        if not scan_id:
            raise ValueError("append_scan_event requires a scan_id")
        if kind not in self.SCAN_EVENT_KINDS:
            raise ValueError(
                f"unknown scan event kind {kind!r} — add it to Store.SCAN_EVENT_KINDS "
                f"(and to ADR 0042's vocabulary) before emitting it")
        import json as _json
        now = occurred_at or self._now()
        payload = None
        if detail is not None:
            try:
                payload = _json.dumps(detail)
            except (TypeError, ValueError):
                payload = None      # unserializable detail loses the detail, never the event
        sql = ("INSERT INTO scan_events"
               "(event_id,scan_id,seq,occurred_at,kind,phase,job_id,worker_id,attempt,detail,owner_email) "
               "SELECT %s,%s,COALESCE(MAX(seq),0)+1,%s,%s,%s,%s,%s,%s,%s,%s "
               "FROM scan_events WHERE scan_id=%s")
        for _ in range(self._SCAN_EVENT_SEQ_ATTEMPTS):
            event_id = uuid.uuid4().hex
            try:
                with self._db.cursor() as cur:
                    self._db.execute(cur, sql, (
                        event_id, scan_id, now, kind, phase, job_id, worker_id, attempt,
                        payload, owner_email, scan_id))
                # Read back rather than recomputing MAX: another writer may have appended in the
                # gap, and reporting ITS seq as this event's would be a quietly wrong return value.
                with self._db.cursor() as cur:
                    self._db.execute(cur,
                        "SELECT seq FROM scan_events WHERE event_id=%s", (event_id,))
                    row = self._db.fetchone(cur)
                return int(row["seq"]) if row else None
            except Exception:
                continue            # lost the seq race (or the store is unavailable) — try again
        return None

    def list_scan_events(self, scan_id: str, *, after_seq: int | None = None,
                         owner: str | None = None, limit: int = 500) -> list[dict]:
        """This scan's lifecycle events in `seq` order, oldest first. Never raises — an unknown
        scan, a foreign one, or an unavailable store all read as [].

        ASCENDING and after_seq-able because the consumer is "what happened, and what did I miss
        since seq N" — the opposite of list_decisions' newest-first audit browse. `owner` scopes
        on the denormalized owner_email; pass it whenever a request context has one. Note that
        events written before an owner was known carry owner_email=NULL and are therefore NOT
        returned by an owner-scoped read: the route must gate on get_scan(owner=...) first, the
        same way every other per-scan endpoint already does, rather than treating this filter as
        the access check.

        `detail` comes back as the dict it was written as (or None), never as a raw JSON string.
        """
        import json as _json
        where, params = "scan_id=%s", [scan_id]
        if after_seq is not None:
            where += " AND seq>%s"; params.append(int(after_seq))
        if owner:
            where += " AND owner_email=%s"; params.append(owner)
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    f"SELECT * FROM scan_events WHERE {where} ORDER BY seq LIMIT %s",
                    tuple(params + [limit]))
                rows = self._db.fetchall(cur)
        except Exception:
            return []
        for r in rows:
            raw = r.get("detail")
            if raw:
                try:
                    r["detail"] = _json.loads(raw)
                except (TypeError, ValueError):
                    r["detail"] = None
            else:
                r["detail"] = None
        return rows

    # ── Operational event stream (orchestration_events / worker_instances) ────
    #
    # PR 1 of a 5-PR delivery plan modeled on ADR 0042's scan_events (the CUSTOMER-FACING
    # scan-lifecycle narrative — always scan-anchored). This is the broader OPERATIONAL layer:
    # job attempts, worker identity/readiness, Azure capacity transitions, dependency health —
    # including events with NO scan_id at all. Coexisting, additive infrastructure; scan_events,
    # append_scan_event and its emit sites are untouched.
    #
    # NO CALLER YET, deliberately, exactly like scan_events' own PR 1: this lands the tables and
    # their store methods with ZERO behaviour change so the emit sites (a later PR, touching
    # worker.py's claim/reclaim/zombie-write-suppression paths) can be reviewed on their own, with
    # explicit human review — that PR is materially riskier than this one and is not started here.

    # Closed set of operational transitions. Closed for the same reason SCAN_EVENT_KINDS is: a
    # future reader renders per-kind, so a typo'd or ad-hoc kind is a row nothing knows how to
    # display. Extend by design amendment, not in passing.
    ORCHESTRATION_EVENT_KINDS = frozenset({
        "job.submitted", "job.eligible", "job.claimed", "job.stage_started", "job.stage_completed",
        "job.completed", "job.cancel_requested", "job.cancelled", "job.failed",
        "job.retry_scheduled", "job.retry_started", "job.lease_expired", "job.reclaimed",
        "job.dead_lettered", "job.zombie_write_suppressed",
        "worker.starting", "worker.ready", "worker.busy", "worker.draining", "worker.unhealthy",
        "worker.offline",
        "capacity.shortage_detected", "capacity.provisioning_observed", "capacity.replica_running",
        "capacity.worker_ready", "capacity.scale_in_observed",
        "dependency.throttled", "dependency.authentication_failed", "dependency.unavailable",
        "dependency.recovered",
    })

    # Closed set for the `error_class` field. Used by a later PR's classification logic; validated
    # now (when a caller happens to supply one) so a bad value can never reach the table and be
    # discovered only when someone tries to render/aggregate by it.
    ERROR_CLASS_VOCABULARY = frozenset({
        "capacity", "worker_startup", "worker_crash", "lease_expired", "source_authentication",
        "source_authorization", "source_rate_limit", "source_unavailable", "storage", "database",
        "model_rate_limit", "model_safety", "model_unavailable", "invalid_document",
        "unsupported_document", "timeout", "cancelled", "unknown",
    })

    # Closed set for worker_instances.state.
    WORKER_INSTANCE_STATES = frozenset({
        "starting", "ready", "busy", "draining", "unhealthy", "offline",
    })

    _ORCH_EVENT_SCHEMA_VERSION = 1
    # 2KB, matching SUBSTR(last_error,1,200)'s spirit of bounding free text elsewhere in this
    # file — detail_json is narration (a file count, a retry attempt, an error class), never a
    # second source of truth, so there is no correctness reason for it to be large.
    _ORCH_DETAIL_MAX_BYTES = 2048

    def append_orchestration_event(self, *, owner_email: str, kind: str,
                                   occurred_at: str | None = None, scan_id: str | None = None,
                                   job_id: str | None = None, job_type: str | None = None,
                                   attempt: int | None = None, workflow: str | None = None,
                                   stage: str | None = None, severity: str | None = None,
                                   worker_id: str | None = None, replica_id: str | None = None,
                                   revision_name: str | None = None,
                                   correlation_id: str | None = None, provider: str | None = None,
                                   error_class: str | None = None, duration_ms: int | None = None,
                                   detail: dict | None = None) -> str | None:
        """Append one operational event and return its event_id (None if it was not written).

        RAISES on a bad `kind`, a bad `error_class` (when one is supplied), or a missing
        `owner_email` — these are programming errors a test must catch, not runtime conditions.
        Every OTHER failure (the store being unavailable, mid-outage) is swallowed and returns
        None: this deliberately mirrors append_scan_event's contract, which itself mirrors
        activity.py's — "a progress line must never be able to fail the work it describes". A
        future emit-site PR will wrap every call site anyway, but the guarantee belongs here, next
        to the write, not re-derived at every caller. A missing row is a gap in narration; it is
        never a wrong statement, because nothing in this table is ever overwritten.

        No `seq`/MAX+1 dance like append_scan_event: there is no shared per-key counter to race
        over here in the first place. scan_events' seq is a per-SCAN counter contended by however
        many writers touch that one scan_id at once; this table's ordering key is
        (occurred_at, event_id), and event_id is a fresh uuid4 per call — two concurrent writers
        never contend for the same identity, so there is nothing to retry. (scan_events could not
        make the same simplification: it needed a per-scan monotonic position, which is exactly
        the thing concurrent writers collide on.)

        `detail` is a dict, stored as JSON, capped at `_ORCH_DETAIL_MAX_BYTES`. An oversized or
        unserializable `detail` never costs the event itself:
          - unserializable → detail_json is dropped to NULL (event still written).
          - serializable but over the cap → replaced with {"truncated": true, "original_size": N}
            rather than cut mid-JSON, which would emit invalid JSON no reader could parse.
        detail_json must NEVER contain document contents, access tokens, prompts, model responses,
        PHI, or credentials — see the schema comment on orchestration_events for the full
        redaction contract. This method enforces size, not content: a caller passing a credential
        in `detail` is a bug at the call site, not something this method can detect.
        """
        if not owner_email:
            raise ValueError("append_orchestration_event requires an owner_email")
        if kind not in self.ORCHESTRATION_EVENT_KINDS:
            raise ValueError(
                f"unknown orchestration event kind {kind!r} — add it to "
                f"Store.ORCHESTRATION_EVENT_KINDS before emitting it")
        if error_class is not None and error_class not in self.ERROR_CLASS_VOCABULARY:
            raise ValueError(
                f"unknown error_class {error_class!r} — add it to "
                f"Store.ERROR_CLASS_VOCABULARY before emitting it")
        import json as _json
        now = occurred_at or self._now()
        payload = None
        if detail is not None:
            try:
                raw = _json.dumps(detail)
            except (TypeError, ValueError):
                raw = None          # unserializable detail loses the detail, never the event
            if raw is not None:
                if len(raw.encode("utf-8")) > self._ORCH_DETAIL_MAX_BYTES:
                    raw = _json.dumps({"truncated": True, "original_size": len(raw.encode("utf-8"))})
                payload = raw
        event_id = uuid.uuid4().hex
        sql = ("INSERT INTO orchestration_events "
               "(event_id,occurred_at,owner_email,scan_id,job_id,job_type,attempt,workflow,stage,"
               "kind,severity,worker_id,replica_id,revision_name,correlation_id,provider,"
               "error_class,duration_ms,detail_json,schema_version) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur, sql, (
                    event_id, now, owner_email, scan_id, job_id, job_type, attempt, workflow,
                    stage, kind, severity, worker_id, replica_id, revision_name, correlation_id,
                    provider, error_class, duration_ms, payload,
                    self._ORCH_EVENT_SCHEMA_VERSION))
            return event_id
        except Exception:
            return None

    def list_orchestration_events(self, *, owner_email: str | None = None,
                                  scan_id: str | None = None, job_id: str | None = None,
                                  worker_id: str | None = None, kind: str | None = None,
                                  after: tuple | list | None = None,
                                  limit: int = 500) -> list[dict]:
        """Operational events in `(occurred_at, event_id)` order, oldest first. Never raises — an
        unavailable store, or filters that match nothing, both read as [].

        `owner_email` scopes to one tenant's events when given; omit it for a global/admin read
        (matching job_stats'/dead_letter_breakdown's own owner-optional pattern) — there is no
        implicit access check here, so a caller with a request-scoped owner must always pass it.
        Every other filter narrows further and is independent — pass any subset.

        `after` is a `(occurred_at, event_id)` keyset cursor (the last row's own two fields from a
        previous page), not a bare timestamp: ordering here has a TIEBREAK specifically because
        `occurred_at` alone is not a safe total order (two events can share a timestamp), so a
        cursor over `occurred_at` alone could silently skip or repeat a same-timestamp neighbour
        depending on where it falls relative to the page boundary. Comparing the full tuple —
        `(occurred_at, event_id) > (%s, %s)` — is what keeps "what did I miss since my last page"
        correct across ties, the same reasoning list_scan_events' `after_seq` exists for, adapted
        to a key that has no single monotonic column to lean on.

        `detail` comes back as the dict it was written as (or None), never as a raw JSON string.
        """
        import json as _json
        where, params = ["1=1"], []
        if owner_email:
            where.append("owner_email=%s"); params.append(owner_email)
        if scan_id:
            where.append("scan_id=%s"); params.append(scan_id)
        if job_id:
            where.append("job_id=%s"); params.append(job_id)
        if worker_id:
            where.append("worker_id=%s"); params.append(worker_id)
        if kind:
            where.append("kind=%s"); params.append(kind)
        if after is not None:
            after_occurred_at, after_event_id = after
            where.append("(occurred_at,event_id)>(%s,%s)")
            params.extend([after_occurred_at, after_event_id])
        sql = (f"SELECT * FROM orchestration_events WHERE {' AND '.join(where)} "
               "ORDER BY occurred_at, event_id LIMIT %s")
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur, sql, tuple(params + [limit]))
                rows = self._db.fetchall(cur)
        except Exception:
            return []
        for r in rows:
            raw = r.get("detail_json")
            if raw:
                try:
                    r["detail"] = _json.loads(raw)
                except (TypeError, ValueError):
                    r["detail"] = None
            else:
                r["detail"] = None
            r.pop("detail_json", None)
        return rows

    # Columns upsert_worker_instance may write. A whitelist, not the caller's kwarg names taken
    # on faith — **fields feeds directly into a dynamically-built SQL column list, and this is
    # what keeps that safe.
    _WORKER_INSTANCE_FIELDS = frozenset({
        "replica_id", "revision_name", "started_at", "last_heartbeat_at", "supported_job_types",
        "concurrency_limit", "active_job_count", "available_slots", "state",
        "last_claimed_job_id", "software_version",
    })

    def upsert_worker_instance(self, worker_id: str, **fields) -> None:
        """Create or update ONE worker's current-state row. Current-state, NOT append-only —
        a second call for the same worker_id UPDATES that row in place; it never inserts a
        second one. Partial: only the columns actually passed are written/overwritten, so a
        heartbeat that only wants to bump `last_heartbeat_at` and `active_job_count` does not
        clobber `supported_job_types`/`concurrency_limit` set by an earlier, fuller call.

        `state`, if passed, must be one of WORKER_INSTANCE_STATES — raises ValueError otherwise,
        same closed-set contract as append_orchestration_event's `kind`.

        `supported_job_types`, if passed as a list/tuple, is JSON-encoded to match the column's
        TEXT storage; passed as a string it is stored as-is (assumed already-encoded).

        Unlike append_orchestration_event, this does NOT swallow store failures — a worker
        registering its own readiness is not "telemetry about a customer job in flight" (the
        contract that clause protects), and a caller (the future heartbeat loop) needs to know if
        its own state write failed rather than believe a stale row.
        """
        if not worker_id:
            raise ValueError("upsert_worker_instance requires a worker_id")
        unknown = set(fields) - self._WORKER_INSTANCE_FIELDS
        if unknown:
            raise ValueError(f"unknown worker_instances field(s): {sorted(unknown)}")
        if "state" in fields and fields["state"] not in self.WORKER_INSTANCE_STATES:
            raise ValueError(
                f"unknown worker state {fields['state']!r} — must be one of "
                f"Store.WORKER_INSTANCE_STATES")
        if "supported_job_types" in fields and isinstance(fields["supported_job_types"], (list, tuple)):
            import json as _json
            fields = dict(fields)
            fields["supported_job_types"] = _json.dumps(list(fields["supported_job_types"]))

        cols = ["worker_id"] + list(fields.keys())
        placeholders = ",".join(["%s"] * len(cols))
        col_list = ",".join(cols)
        if fields:
            update_clause = ",".join(f"{c}=EXCLUDED.{c}" for c in fields)
            sql = (f"INSERT INTO worker_instances ({col_list}) VALUES ({placeholders}) "
                   f"ON CONFLICT(worker_id) DO UPDATE SET {update_clause}")
        else:
            # Nothing to update — just make sure the row exists.
            sql = (f"INSERT INTO worker_instances ({col_list}) VALUES ({placeholders}) "
                   f"ON CONFLICT(worker_id) DO NOTHING")
        with self._db.cursor() as cur:
            self._db.execute(cur, sql, tuple([worker_id] + list(fields.values())))

    def list_worker_instances(self, *, state: str | None = None) -> list[dict]:
        """The worker registry's current state, ordered by worker_id for a stable read. Never
        raises — an unavailable store reads as []."""
        where, params = "1=1", []
        if state:
            where = "state=%s"; params = [state]
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    f"SELECT * FROM worker_instances WHERE {where} ORDER BY worker_id",
                    tuple(params))
                return self._db.fetchall(cur)
        except Exception:
            return []

    # ── Audit trail (maturity Phase 4) ────────────────────────────────────────
    def document_timeline(self, scan_id: str, file: str, limit: int = 300) -> list[dict]:
        """Chronological provenance for ONE document in ONE scan — the auditor's answer to
        "what happened to this file and who decided what". Assembled entirely from rows the
        pipeline already persists (scan_runs, file_records, ai_calls, hitl_queue,
        hitl_events, applied_fixes, decision_log); nothing is inferred or fabricated
        (ADR 0016). Every event: {ts, kind, title, detail?, actor?, rule_id?}. Best-effort
        per source — a missing table (older DB) skips that source, never errors."""
        events: list[dict] = []

        def _add(ts, kind, title, detail=None, actor=None, rule_id=None):
            if ts:
                events.append({"ts": ts, "kind": kind, "title": title,
                               "detail": detail or None, "actor": actor or None,
                               "rule_id": rule_id or None})

        def _rows(sql, params):
            try:
                with self._db.cursor() as cur:
                    self._db.execute(cur, sql, params)
                    return self._db.fetchall(cur)
            except Exception:
                return []

        for r in _rows("SELECT * FROM scan_runs WHERE id=%s", (scan_id,)):
            _add(r.get("started_at"), "scan", f"Scan started ({r.get('source') or 'local'})")
            _add(r.get("assessed_at"), "scan", "Assessed against WCAG rubric",
                 detail=f"rubric {r.get('rubric_hash') or ''}".strip() or None)
        for r in _rows("SELECT * FROM file_records WHERE scan_id=%s AND file=%s", (scan_id, file)):
            _add(r.get("remediated_at"), "fix", "Auto-remediation applied",
                 detail=("remediated copy in Blob store" if r.get("blob_url") else None))
            _add(r.get("published_at"), "publish", "Published",
                 detail=r.get("drive_write_url") or r.get("blob_url"))
        for r in _rows("SELECT * FROM ai_calls WHERE scan_id=%s AND file=%s ORDER BY ts", (scan_id, file)):
            zone = r.get("zone") or "local"
            _add(r.get("ts"), "ai",
                 f"AI {r.get('surface') or 'call'} · {r.get('provider') or ''} {r.get('model') or ''}".strip(),
                 detail=f"zone={zone} · {'ok' if r.get('ok') else 'failed'}"
                        + (f" · ${r['cost_usd']:.4f}" if r.get("cost_usd") else ""))
        for r in _rows("SELECT * FROM hitl_queue WHERE scan_id=%s AND file=%s", (scan_id, file)):
            _add(r.get("created_at"), "review", f"Queued for human review · {r.get('rule_id') or ''}".strip(" ·"),
                 detail=r.get("rule_name"), rule_id=r.get("rule_id"))
        for r in _rows("SELECT * FROM hitl_events WHERE scan_id=%s AND file=%s ORDER BY created_at",
                       (scan_id, file)):
            action = r.get("action") or "decision"
            detail = None
            if r.get("edited"):
                detail = "reviewer edited the AI draft before approving"
            if r.get("reject_reason") and r["reject_reason"] != "unspecified":
                detail = f"reason: {r['reject_reason']}"
            _add(r.get("created_at"), "human", f"Human {action} · {r.get('rule_id') or ''}".strip(" ·"),
                 detail=detail, actor=r.get("reviewer"), rule_id=r.get("rule_id"))
        for r in _rows("SELECT * FROM applied_fixes WHERE scan_id=%s AND file=%s ORDER BY created_at",
                       (scan_id, file)):
            _add(r.get("created_at"), "fix", f"Fix written into document · {r.get('rule_id') or ''}".strip(" ·"),
                 detail=(r.get("value") or "")[:160] or None, rule_id=r.get("rule_id"))
        for r in _rows("SELECT * FROM decision_log WHERE scan_id=%s AND file=%s ORDER BY ts",
                       (scan_id, file)):
            action = r.get("action") or "decision"
            if action == "file.certified":
                # its own timeline stage, not a generic review decision
                _add(r.get("ts"), "certify", "Certified conformant",
                     detail=(r.get("detail") or "")[:160] or None, actor=r.get("actor"))
            else:
                _add(r.get("ts"), "decision", action,
                     detail=(r.get("detail") or "")[:160] or None, actor=r.get("actor"),
                     rule_id=r.get("rule_id"))
        events.sort(key=lambda e: e["ts"])
        return events[:limit]

    # ── Durable job queue (ADR 0004) ──────────────────────────────────────────
    # A worker claims the next eligible job, runs it, and marks it done — or, on
    # failure, requeues it with backoff until max_attempts, then dead-letters it.
    # Step-1 claim is optimistic (conditional UPDATE on status='queued'), which is
    # correct for one worker and portable across Postgres + SQLite. Postgres
    # `FOR UPDATE SKIP LOCKED` is the throughput optimization for the multi-worker
    # step (ADR 0004, step 2).

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def enqueue_job(self, type: str, payload: dict | None = None, *,
                    priority: int | None = None, max_attempts: int = 5,
                    run_after: str | None = None, scan_id: str | None = None,
                    campaign_id: str | None = None, batch_id: str | None = None) -> str:
        import json as _json
        now = self._now()
        job_id = uuid.uuid4().hex[:16]
        if priority is None:
            priority = job_priority(type)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO jobs(id,type,payload,status,priority,attempts,max_attempts,"
                "run_after,campaign_id,batch_id,scan_id,created_at,updated_at) "
                "VALUES(%s,%s,%s,'queued',%s,0,%s,%s,%s,%s,%s,%s,%s)",
                (job_id, type, _json.dumps(payload or {}), priority, max_attempts,
                 run_after or now, campaign_id, batch_id, scan_id, now, now))
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM jobs WHERE id=%s", (job_id,))
            row = self._db.fetchone(cur)
        if row and isinstance(row.get("payload"), str):
            import json as _json
            try:
                row["payload"] = _json.loads(row["payload"])
            except Exception:
                swallowed("store.get_job: decoding the job payload failed")
        return row

    @staticmethod
    def _lease_expiry(lease_seconds: int | None = None) -> str:
        from datetime import datetime, timezone, timedelta
        secs = lease_seconds if lease_seconds is not None else int(
            os.environ.get("ACP_JOB_LEASE_S", "600"))
        return (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()

    def claim_job(self, worker_id: str, *, job_types=None) -> dict | None:
        """Atomically claim the next eligible job. Returns the claimed job (with
        attempts already incremented), or None if the queue is empty.

        Within one priority class, candidates are tenant-fair: the owner with the fewest active
        jobs goes first, then the owner least recently served, then the oldest job. This is
        deliberately work-conserving — a sole tenant may use every slot — while preventing a
        large fan-out from continually winning over another tenant's equally-prioritized work.

        Postgres: single-statement UPDATE...WHERE id=(SELECT...FOR UPDATE SKIP LOCKED)
        RETURNING * — each worker atomically grabs a distinct row with no round-trip race.
        SQLite: two-step optimistic CAS — SELECT then conditional UPDATE on status='queued'
        (SQLite serialises writers, so the window between the two is closed in practice)."""
        if job_types is not None and not job_types:
            return None
        types = tuple(job_types or ())
        lane_key = ",".join(sorted(types)) if types else "*"
        clause = " AND qj.type IN (" + ",".join(["%s"] * len(types)) + ") " if types else " "
        active_types = " AND aj.type IN (" + ",".join(["%s"] * len(types)) + ") " if types else " "
        fair_params = (*types, *types)
        now = self._now()
        expires = self._lease_expiry()
        # owner_email is ACP's current tenant boundary (ADR 0044). Jobs without a scan are
        # deliberately their own scheduling key, so maintenance/system work does not collapse
        # into one fictional tenant. Priority precedes fairness: a finalizer or control job may
        # be correctness-critical, while ordinary per-file jobs share the same priority and are
        # the population this interleaves.
        owner_key = "COALESCE(qsr.owner_email,qj.scan_id,qj.id)"
        active_key = "COALESCE(asr.owner_email,aj.scan_id,aj.id)"
        fair_order = (
            " ORDER BY qj.priority, "
            "(SELECT COUNT(*) FROM jobs aj LEFT JOIN scan_runs asr ON asr.id=aj.scan_id "
            f" WHERE aj.status='running' AND {active_key}={owner_key}" + active_types + "), "
            "COALESCE(tqs.last_claimed_at,''), "
            "qj.run_after,qj.created_at,qj.id "
        )
        candidate_from = (
            " FROM jobs qj LEFT JOIN scan_runs qsr ON qsr.id=qj.scan_id "
            f" LEFT JOIN tenant_queue_state tqs ON tqs.tenant_key={owner_key} AND tqs.lane_key=%s "
        )
        record_claim = (
            "INSERT INTO tenant_queue_state(tenant_key,lane_key,last_claimed_at) "
            "SELECT COALESCE(sr.owner_email,j.scan_id,j.id),%s,%s FROM jobs j "
            "LEFT JOIN scan_runs sr ON sr.id=j.scan_id WHERE j.id=%s "
            "ON CONFLICT(tenant_key,lane_key) DO UPDATE SET last_claimed_at=EXCLUDED.last_claimed_at"
        )
        if self._db.supports_skip_locked:
            # Postgres path: atomic single-statement claim with SKIP LOCKED.
            with self._db.cursor() as cur:
                self._db.execute(cur, "SELECT pg_advisory_xact_lock(%s)",
                                 (self._FAIR_CLAIM_ADVISORY_KEY,))
                self._db.execute(cur,
                    "UPDATE jobs SET status='running', locked_at=%s, locked_by=%s, "
                    "attempts=attempts+1, updated_at=%s, lease_expires_at=%s, phase=NULL "
                    "WHERE id = ("
                    "  SELECT qj.id" + candidate_from +
                    "  WHERE qj.status='queued' AND qj.run_after<=%s "
                    + clause + fair_order +
                    # Only qj is claimable. The LEFT JOIN rows provide scheduling metadata and
                    # may be absent, so PostgreSQL must not try to lock their nullable sides.
                    "  FOR UPDATE OF qj SKIP LOCKED LIMIT 1"
                    ") RETURNING id",
                    (now, worker_id, now, expires, lane_key, now, *fair_params))
                row = self._db.fetchone(cur)
                if row:
                    self._db.execute(cur, record_claim, (lane_key, now, row["id"]))
            if not row:
                return None
            return self.get_job(row["id"])
        else:
            # SQLite path: optimistic two-step CAS.
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "SELECT qj.id" + candidate_from +
                    "WHERE qj.status='queued' AND qj.run_after<=%s "
                    + clause + fair_order + "LIMIT 1", (lane_key, now, *fair_params))
                row = self._db.fetchone(cur)
                if not row:
                    return None
                jid = row["id"]
                self._db.execute(cur,
                    "UPDATE jobs SET status='running', locked_at=%s, locked_by=%s, "
                    "attempts=attempts+1, updated_at=%s, lease_expires_at=%s, phase=NULL "
                    "WHERE id=%s AND status='queued'",
                    (now, worker_id, now, expires, jid))
                claimed = getattr(cur, "rowcount", 1) == 1
                if claimed:
                    self._db.execute(cur, record_claim, (lane_key, now, jid))
            return self.get_job(jid) if claimed else None

    def set_job_phase(self, job_id: str, phase: str | None) -> None:
        """Record what this job is doing right now, for the queue panel's per-row line.

        Best-effort and never fatal: progress reporting must not be able to fail the work it
        reports on. Bumps updated_at, which is also what the panel's elapsed timer reads — so
        a job that stops reporting stops looking busy.
        """
        try:
            with self._db.cursor() as cur:
                self._db.execute(cur, "UPDATE jobs SET phase=%s, updated_at=%s WHERE id=%s",
                                 (phase, self._now(), job_id))
        except Exception as e:
            print(f"[jobs] could not record phase for {job_id}: {e}", flush=True)

    _SECRET_PAYLOAD_KEYS = ("drive_token", "sp_token", "token")

    def _scrub_payload_secrets(self, job_id: str) -> str | None:
        """Payload JSON with short-lived auth tokens removed — so a TERMINAL (done/dead)
        job row doesn't persist a plaintext Drive/Graph token in Postgres (dead-lettered
        rows otherwise linger until purge). In-flight (queued/running) jobs keep the
        token: it's the deliberate cross-replica/restart durability path (see
        handlers._remediate_file), and it's short-lived (~1h) anyway. Returns None when
        there's no payload or nothing to scrub, so the caller leaves payload untouched."""
        import json as _j
        job = self.get_job(job_id)
        if not job:
            return None
        payload = job.get("payload")
        try:
            data = payload if isinstance(payload, dict) else _j.loads(payload or "{}")
        except Exception:
            return None
        if not isinstance(data, dict) or not any(k in data for k in self._SECRET_PAYLOAD_KEYS):
            return None
        for k in self._SECRET_PAYLOAD_KEYS:
            data.pop(k, None)
        return _j.dumps(data)

    # The identity of a claim: which worker holds the job, on which attempt. claim_job sets
    # both, so both are available to every caller that legitimately holds the job.
    _CLAIM_OWNED = " AND status='running' AND locked_by=%s AND attempts=%s"

    def _claim_is_current(self, job_id: str, worker_id: str, attempt: int) -> bool:
        """True if (worker_id, attempt) is still the claim running this job.

        Advisory only — the authority is the ownership predicate compiled into each outcome
        UPDATE, which is atomic. This exists so a caller can skip SIDE EFFECTS it would
        otherwise perform before that UPDATE ever runs (fail_job writes dead file rows before
        it writes the status). Racy by construction: a job can be reclaimed between this
        returning True and the UPDATE, which is exactly why the UPDATE keeps its own guard.
        """
        job = self.get_job(job_id)
        if not job:
            return False
        return (job.get("status") == "running"
                and job.get("locked_by") == worker_id
                and job.get("attempts") == attempt)

    def complete_job(self, job_id: str, *, worker_id: str, attempt: int) -> bool:
        """Mark the job done. Guarded against a reclaimed job's original (zombie) worker
        completing AFTER a second worker already finished it: reclaim_stuck_jobs() requeues a
        job whose lease expired so a SECOND worker can claim and run it, but does nothing to
        stop the FIRST worker's handler from finishing later and calling complete_job on the
        same job_id, unaware it lost the lease. Without this guard that late call would
        silently overwrite whatever terminal status the second run already recorded — harmless
        when both happen to write 'done', but a real clobber (a completed job flipped back to
        'dead'/'cancelled') if the zombie instead hits fail_job/mark_job_cancelled. Whichever
        writer's terminal state lands first now wins; every later one is a safe no-op.
        Returns True if this call's write applied, False if it did not.

        ONLY THE CURRENT CLAIM MAY PUBLISH AN OUTCOME. The terminal guard above stops a zombie
        overwriting a job that already FINISHED; it does nothing about one overwriting a job
        still RUNNING under a replacement claim, because 'running' is not in the guarded set.
        That is the live half of the same race: worker-B is mid-run when worker-A's stale
        handler returns, A's completion lands, and B's own write is then refused as "already
        terminal" — the suppression message naming the wrong writer. So `locked_by` and
        `attempts` must both match, exactly as touch_job requires them (#1075): a worker can
        legitimately re-claim a job it ran before, and the earlier execution must not publish
        for the later one. Both are REQUIRED keyword arguments, deliberately — an optional
        guard is one a future caller forgets, silently. Pinned by
        tests/test_outcome_claim_ownership.py."""
        scrubbed = self._scrub_payload_secrets(job_id)
        with self._db.cursor() as cur:
            if scrubbed is not None:
                self._db.execute(cur,
                    "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL, payload=%s "
                    "WHERE id=%s AND status NOT IN ('done','dead','cancelled')" + self._CLAIM_OWNED,
                    (self._now(), scrubbed, job_id, worker_id, attempt))
            else:
                self._db.execute(cur,
                    "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL "
                    "WHERE id=%s AND status NOT IN ('done','dead','cancelled')" + self._CLAIM_OWNED,
                    (self._now(), job_id, worker_id, attempt))
            won = (getattr(cur, "rowcount", 0) or 0) > 0
        if not won:
            print(f"[acp] complete_job: job {job_id} already terminal — zombie-worker no-op", flush=True)
        return won

    def request_job_cancellation(self, job_id: str) -> bool:
        """Signal a running or queued job to stop at its next checkpoint.

        Sets cancel_requested_at so a handler calling worker.check_cancel() will raise
        JobCancelledError on its next checkpoint poll. Returns True if the flag was set,
        False when the job is already terminal (done/dead/cancelled) or missing."""
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET cancel_requested_at=%s, updated_at=%s "
                "WHERE id=%s AND status IN ('queued','running') AND cancel_requested_at IS NULL",
                (now, now, job_id))
            return (getattr(cur, "rowcount", 0) or 0) > 0

    def is_job_cancelled(self, job_id: str) -> bool:
        """True if cancel_requested_at has been set for this job."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT cancel_requested_at FROM jobs WHERE id=%s", (job_id,))
            row = self._db.fetchone(cur)
        return bool(row and row.get("cancel_requested_at"))

    def mark_job_cancelled(self, job_id: str, *, worker_id: str, attempt: int) -> bool:
        """Stamp the job as status='cancelled' after cooperative cancellation completes.

        Same reclaimed-job guard as complete_job (see its docstring): a late call arriving
        after the job already reached a DIFFERENT terminal state — e.g. a second worker's
        complete_job already ran following a lease reclaim — is a safe no-op, never a clobber.
        Ownership is required for the same reason it is on complete_job (see there): a stale
        attempt's JobCancelledError must not stop the replacement that took its job over. That
        matters more since #1079 — cancellation now reaches the pool threads, so more attempts
        can raise it and arrive here.
        Returns True if this call's write applied, False if it did not."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='cancelled', updated_at=%s "
                "WHERE id=%s AND status NOT IN ('done','dead','cancelled')" + self._CLAIM_OWNED,
                (self._now(), job_id, worker_id, attempt))
            won = (getattr(cur, "rowcount", 0) or 0) > 0
        if not won:
            print(f"[acp] mark_job_cancelled: job {job_id} already terminal — zombie-worker no-op", flush=True)
        return won

    # A job that reached a terminal state because someone STOPPED it, not because it failed.
    #
    # WHAT A TERMINAL ROW PLUS cancel_requested_at DOES AND DOES NOT PROVE. An earlier version of
    # this comment claimed the pair meant "nothing belonging to this job can still run or write".
    # That was false, and it was the same species of overclaim the rest of this method exists to
    # remove — a label asserting more than its data supports.
    #
    # _end_running_scan writes status='dead' AND cancel_requested_at in ONE statement, while a
    # handler may still be mid-flight: the worker does not stop until its next check_cancel()
    # checkpoint. The row goes terminal immediately; the execution does not. Job-row writes from
    # the late worker are refused (complete_job/fail_job/mark_job_cancelled are all guarded on
    # `status NOT IN ('done','dead','cancelled')` plus the claim), but the handler can still be
    # running, and can still write elsewhere — save_file_result is not gated on job status.
    #
    # THREE STATES, and only two of them are provable from a row:
    #
    #   requested       cancel_requested_at is set. Work may still be running. Says nothing
    #                   about whether anyone has noticed.
    #   acknowledged    status='cancelled'. PROVABLE, and the strong one: mark_job_cancelled is
    #                   the only writer of that status on this table (see its docstring), and
    #                   worker.py calls it in exactly two places, both AFTER the handler returned
    #                   or raised. So the execution really has ended.
    #   ended-by-decision  the row is terminal and cancel_requested_at is set. This says the job
    #                   will not be retried and did not fail. It does NOT say the process
    #                   stopped, unless the status is also 'cancelled'.
    #
    # `stopped` below counts ended-by-decision, which is the right bucket for a FAULT diagnostic:
    # the question it answers is "is this an incident", and a pressed button is not one either
    # way. It carries the acknowledged/unacknowledged split so the stronger question — has the
    # work actually ceased — has a real answer instead of an implied one.
    #
    # WHY IT LOOKS LIKE A FAILURE TODAY. _end_running_scan (cancel_scan and supersede_scan both
    # route through it) sets status='dead' on every queued/running job of the scan, and its own
    # comment records the consequence as deliberate: the worker's later mark_job_cancelled is
    # guarded `status NOT IN ('done','dead','cancelled')`, so it no-ops and "the job KEEPS its
    # 'dead' status — dead-letter accounting is unchanged".
    #
    # Unchanged, and wrong for the operator. dead_letter_breakdown answers "why are jobs dying",
    # and every Stop press was landing in that answer as a failure — inflating `n`,
    # `affected_runs` and `total_attempts`, and grouping under whatever last_error happened to be
    # on the row. A pressed button is not an incident, and a diagnostic that cannot tell them
    # apart makes the real incidents harder to see, which is the opposite of its purpose.
    #
    # The data to separate them was already there: those rows carry cancel_requested_at. Nothing
    # read it that way. Kept as one predicate rather than inlined, so a future query cannot apply
    # the distinction in one place and forget it in another — which is how it was lost the first
    # time.
    _STOPPED = " AND cancel_requested_at IS NOT NULL"
    _FAILED = " AND cancel_requested_at IS NULL"
    # The one status that is acknowledgement evidence. Written by mark_job_cancelled and nothing
    # else, from worker.py's two post-handler call sites. Portable CASE rather than FILTER, which
    # SQLite and Postgres do not agree on.
    _ACKNOWLEDGED_CASE = "SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END)"

    def dead_letter_breakdown(self, owner: str | None = None) -> dict:
        """Diagnostic: jobs that FAILED, grouped by type + the most common errors — and,
        separately, jobs that were STOPPED.
        owner scopes to the caller's own jobs so error text (which can name a file)
        never leaks across tenants.

        `stopped` reports jobs that ended BY DECISION, split by whether a worker acknowledged
        it (see the comment above _STOPPED). `stopped.n` is not a claim that the work has
        ceased; `stopped.acknowledged` is.

        `by_type`, `top_errors` and `failed` exclude deliberately-stopped jobs (see _STOPPED).
        They used to include them, because a Stop marks its jobs 'dead' and this read status
        alone — so pressing Stop on a 200-document scan added 200 "failures" to the operator's
        why-are-jobs-dying view. `stopped` reports that count instead of hiding it: the jobs are
        still terminal and still worth seeing, they are simply not faults.

        Each `top_errors` group also carries incident-shaped context for the UI (Monitor's
        dead-letter banner): a scan (run) fans out into many jobs — scan_file/scan_batch/
        scan_folder per file or chunk — so several dead job ROWS sharing one error can all
        belong to the SAME run. `n` (unchanged) counts those job rows; `affected_runs` counts
        the distinct scans they came from, which is the number a human means by "runs" and can
        be smaller than `n`. Separately, `claim_job` increments a job's own `attempts` on
        every retry of that SAME row (fail_job requeues in place, it does not insert a new
        row) — so `total_attempts`, the SUM of `attempts` across the group, captures retry
        volume that `n` alone (one row per job, however many times it was retried) cannot."""
        scope = " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        sp = (owner,) if owner else ()
        out: dict = {}
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT type, COUNT(*) AS n FROM jobs WHERE status='dead'"
                             + self._FAILED + scope + " GROUP BY type", sp)
            out["by_type"] = {r["type"]: r["n"] for r in self._db.fetchall(cur)}
            # Deliberate stops, counted and reported rather than dropped: a user who stopped a
            # run should still be able to see that its jobs ended, and an operator should not
            # have to subtract them from a failure count by eye.
            self._db.execute(cur, "SELECT COUNT(*) AS n, COUNT(DISTINCT scan_id) AS runs, "
                             + self._ACKNOWLEDGED_CASE + " AS acked "
                             "FROM jobs WHERE status IN ('dead','cancelled')"
                             + self._STOPPED + scope, sp)
            _st = self._db.fetchone(cur) or {}
            _n = int(_st.get("n") or 0)
            # int() because Postgres hands SUM() back as a Decimal and SQLite as an int; the
            # subtraction below must not depend on which database answered.
            _acked = int(_st.get("acked") or 0)
            out["stopped"] = {
                "n": _n, "affected_runs": _st.get("runs") or 0,
                # A worker confirmed it stopped: the handler returned or raised first.
                "acknowledged": _acked,
                # Marked terminal by the cancellation itself. The job will not be retried, but no
                # worker has confirmed the execution ended — it may still be between checkpoints.
                "unacknowledged": max(0, _n - _acked),
            }
            # The number the operator's red banner is ENTITLED to describe as "failed
            # permanently". It equals sum(by_type.values()) by construction, but affected_runs
            # is not derivable from by_type, and a caller that has to sum a dict to learn the
            # headline figure will eventually sum the wrong one — QueuePanel read `stats.dead`,
            # which is that mistake with a different source.
            self._db.execute(cur, "SELECT COUNT(*) AS n, COUNT(DISTINCT scan_id) AS runs "
                             "FROM jobs WHERE status='dead'" + self._FAILED + scope, sp)
            _fl = self._db.fetchone(cur) or {}
            out["failed"] = {"n": _fl.get("n") or 0, "affected_runs": _fl.get("runs") or 0}
            self._db.execute(cur,
                "SELECT type, SUBSTR(last_error,1,200) AS err, COUNT(*) AS n, "
                "COUNT(DISTINCT scan_id) AS affected_runs, SUM(attempts) AS total_attempts, "
                "MIN(created_at) AS first_seen, MAX(updated_at) AS last_seen FROM jobs "
                "WHERE status='dead'" + self._FAILED + scope
                + " GROUP BY type, SUBSTR(last_error,1,200) ORDER BY n DESC LIMIT 15", sp)
            out["top_errors"] = [{"type": r["type"], "n": r["n"], "error": r["err"],
                                  "affected_runs": r["affected_runs"],
                                  "total_attempts": r["total_attempts"],
                                  "first_seen": r["first_seen"], "last_seen": r["last_seen"]}
                                 for r in self._db.fetchall(cur)]
        return out

    def purge_dead_jobs(self, owner: str | None = None) -> int:
        """Delete dead-lettered jobs (unrecoverable). owner scopes the purge to the
        caller's own jobs so one tenant can't clear another's. Returns how many removed."""
        scope = " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        sp = (owner,) if owner else ()
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE status='dead'" + scope, sp)
            n = self._db.fetchone(cur)["n"]
            self._db.execute(cur, "DELETE FROM jobs WHERE status='dead'" + scope, sp)
        return n

    def purge_done_jobs(self, older_than_hours: int = 24) -> int:
        """Delete completed ('done') jobs older than the cutoff so the jobs table (and the
        claim index) don't grow unbounded — done rows were previously never purged (audit
        P2). Dead jobs are retained for diagnostics; purge_dead_jobs handles those."""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE status='done' AND updated_at<%s", (cutoff,))
            n = self._db.fetchone(cur)["n"]
            self._db.execute(cur, "DELETE FROM jobs WHERE status='done' AND updated_at<%s", (cutoff,))
        return n

    def touch_job(self, job_id: str, *, worker_id: str, attempt: int) -> None:
        """Heartbeat: extend a running job's lease so the stuck-job sweeper won't
        reclaim a slow-but-alive job (e.g. a long PII scan). Called periodically by
        the worker while the handler runs.

        ONLY THE CURRENT HOLDER MAY RENEW. The predicate used to be `id=%s AND
        status='running'`, which any process still believing it owned the job satisfied —
        including one whose claim the sweeper reclaimed minutes ago. A wedged worker's
        heartbeat thread outlives its claim, so it went on extending the lease of whichever
        worker took the job over.

        That is worse than a wasted write. The lease is the ONLY mechanism that recovers a job
        from a dead worker, so while a zombie keeps renewing it the new holder's death is
        invisible: the lease never goes stale, reclaim_stuck_jobs never fires, and the job sits
        'running' behind a heartbeat from a process doing no work. The zombie masks the failure
        of its own replacement. Bounded by max_unverified_lease_s (ACP_JOB_MAX_LEASE_S, 3600s
        by default) rather than small.

        `attempt` as well as `worker_id`, because a worker can legitimately re-claim a job it
        ran before — same locked_by, later attempt — and the earlier execution's heartbeat must
        not renew the later one's lease. claim_job sets both fields, so both are available to
        check against.

        Both are REQUIRED keyword arguments, deliberately: an optional guard is one a future
        caller forgets, and the failure would be silent. Pinned by tests/test_lease_ownership.py.
        """
        now = self._now()
        expires = self._lease_expiry()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET locked_at=%s, updated_at=%s, lease_expires_at=%s "
                "WHERE id=%s AND status='running' AND locked_by=%s AND attempts=%s",
                (now, now, expires, job_id, worker_id, attempt))

    # Job types whose payload names documents that COUNT toward a scan's finalize total.
    # A dead-letter on one of these has to leave a file_records row behind — see
    # _record_dead_scan_files. Deliberately not `rescore_file`: that re-scores a document whose
    # row already exists, so its failure leaves the previous result standing rather than a gap.
    _COUNTED_FILE_JOBS = ("scan_file", "scan_batch")

    def _dead_job_files(self, job: dict) -> list[dict]:
        """The documents a dead per-file job was carrying: [{file, drive_file_id}].

        Two payload shapes, and missing the second one is how a whole batch disappears:
        `scan_file` names ONE `file`; `scan_batch` (ADR 0008, estates over the batch threshold)
        carries `items` — up to ACP_SCAN_BATCH_SIZE documents that all vanish together.
        """
        if job.get("type") not in self._COUNTED_FILE_JOBS:
            return []
        payload = job.get("payload") or {}
        if isinstance(payload, str):
            import json as _j
            try:
                payload = _j.loads(payload)
            except Exception:
                return []
        if payload.get("items"):
            return [{"file": it.get("file"), "drive_file_id": it.get("drive_file_id")}
                    for it in payload["items"] if isinstance(it, dict) and it.get("file")]
        return [{"file": payload["file"], "drive_file_id": payload.get("drive_file_id")}] \
            if payload.get("file") else []

    # The per-FOLDER checkpoint unit (ADR 0004 item 6). Its own _COUNTED_FILE_JOBS equivalent,
    # kept separate because the accounting is a different one: a dead scan_file is missing a
    # file_records ROW, a dead scan_folder is missing a COUNTER increment.
    _FOLDER_CHECKPOINT_JOBS = ("scan_folder",)

    def _record_dead_scan_folder(self, job: dict) -> None:
        """Advance completed_folders for a folder job that will never come back to do it itself.

        WHY THIS EXISTS — the same failure _record_dead_scan_files describes, on the other
        counter, and it was not covered. `_scan_folder` calls increment_completed_folders only on
        its success path, and rescue_unfinalized_scans finalizes a per-folder scan only when
        `completed_folders >= total_folders`. A folder job that dead-letters returns through
        neither:

            completed_folders   incremented by _scan_folder's success path   -> never runs
            finalize trigger    fires at completed >= total                  -> never reached
            rescue sweeper      requires completed >= total                  -> cannot help

        so the run sits at 'running' with no outstanding work and nothing able to end it. Measured
        rather than reasoned: tests/test_dead_folder_job_wedges_the_scan.py drives one folder job
        to 'dead' and rescue_unfinalized_scans returns 0.

        Counted as ACCOUNTED FOR, not as succeeded. The folder's documents were never scanned and
        this writes no file_records rows claiming otherwise; the dead job row keeps the error, so
        the dead-letter view still reports what happened. What changes is only that the run can
        reach a terminal state — reporting a partial scan is a fact, hanging at 0% is not.

        Still called only once the terminal UPDATE has WON, but that ordering is no longer the
        only thing standing between this and an over-count. It used to be, and the reason is
        worth keeping: unlike _record_dead_scan_files, whose per-document write is an upsert and
        so survives being repeated, an increment was not idempotent, and running it for a zombie
        worker's refused dead-letter would finalize a scan whose folders were still being
        processed. Ordering answers that for the zombie. It never answered the case where the
        SAME folder is counted by two different paths — an attempt that incremented on its success
        path and then died before its row reached 'done', requeued, exhausting its retries here —
        because the two calls are both legitimate and neither is a loser to be suppressed. Passing
        the folder makes the counter idempotent per folder, which decides all of it structurally
        rather than by call ordering.

        Best-effort by construction, for the same reason as its sibling: telemetry must never turn
        a dead-letter into an exception inside the queue.
        """
        if job.get("type") not in self._FOLDER_CHECKPOINT_JOBS:
            return
        scan_id = job.get("scan_id")
        if not scan_id:
            return
        payload = job.get("payload") or {}
        if isinstance(payload, str):
            import json as _j
            try:
                payload = _j.loads(payload)
            except Exception:
                payload = {}
        folder_id = payload.get("folder_id") if isinstance(payload, dict) else None
        try:
            done, total = self.increment_completed_folders(scan_id, folder_id)
            print(f"[acp] dead folder job accounted for: scan={scan_id} "
                  f"folder={folder_id or '?'} folders {done}/{total}", flush=True)
        except Exception as e:  # noqa: BLE001 — see the best-effort note above
            print(f"[acp] _record_dead_scan_folder: could not advance the folder counter for "
                  f"scan {scan_id}: {e}", flush=True)

    def _record_dead_scan_files(self, job: dict, error: str, now_iso: str) -> None:
        """Leave an 'error' file_records row for every document a dead-lettered job was carrying.

        WHY THIS EXISTS. `count_files_done` counts file_records against `scan_runs.files`, and
        `scan_finalize` fires only when the two meet. The handlers already record an error row for
        every failure they CATCH — a bad download, a per-file timeout — precisely so the counter
        keeps advancing. But a job that DEAD-LETTERS never returns through that code: retries are
        exhausted, or `force_dead` fired (an expired Drive token takes this path immediately, with
        no retries at all). No row was written, so the document was counted nowhere:

            files_done            counts file_records            → not counted
            run.error / "unable to assess"  file_records status='error'  → not counted
            jobs queued / running  the job is 'dead'              → not counted

        The document simply left the accounting. `files - files_done` then reports it as NOT
        STARTED forever, `count_files_done` can never reach the total, `scan_finalize` never fires,
        and the run sits at 0% with nothing able to end it — `rescue_unfinalized_scans` cannot help
        either, because it requires `file_records >= files`, the very thing that is missing.

        One expired token mid-run was therefore enough to wedge a whole estate permanently.

        Best-effort by construction: a telemetry write must never turn a dead-letter into an
        exception inside the queue. The row is an upsert, so a late-finishing orphan thread that
        does produce a real result simply replaces it.
        """
        rows = self._dead_job_files(job)
        if not rows:
            return
        scan_id = job.get("scan_id")
        if not scan_id:
            return
        for r in rows:
            try:
                # Fenced by the dying job itself: an error row for attempt 1 must not land on a
                # result attempt 2 has already produced. fail_job's _claim_is_current bail
                # protects THIS caller, but that guard lives in the caller — passing the job
                # makes the write safe on its own terms.
                self.save_file_result(scan_id, {
                    "file": r["file"], "engine": "n/a", "status": "error", "score": None,
                    "compliant": 0, "skipped_rules": 0, "issues": [],
                    "drive_file_id": r.get("drive_file_id")}, now_iso, job=job)
            except Exception:
                swallowed("store._record_dead_scan_files: saving an error row for a dead scan file failed")
            # The REASON, in the one place the UI already looks for it: fileErrorReason.js reads
            # `scan.file_error` rows to say why a document has no findings, and refuses to invent a
            # reason when none was recorded. Without this the drawer would say the reason was not
            # recorded — which would be true, and useless, when the queue knew it all along.
            try:
                self.log_decision("system", "scan.file_error", scan_id=scan_id, file=r["file"],
                                  detail=f"job dead-lettered: {error}"[:200])
            except Exception:
                swallowed("store._record_dead_scan_files: logging the dead-scan-files decision failed")

    def fail_job(self, job_id: str, error: str, backoff_seconds: float = 0.0,
                 force_dead: bool = False, error_class: str | None = None,
                 *, worker_id: str, attempt: int) -> str:
        """Requeue a failed job with backoff, or dead-letter it once attempts are
        exhausted (or immediately when force_dead). Returns 'queued' or 'dead'.

        error_class ('rate_limit', 'auth', 'corrupt', 'transient') is persisted on the
        row for operator diagnostics; pass it from the worker's classify_job_error().

        Requires the current claim (worker_id, attempt), as complete_job does — see there. Two
        failure shapes rather than one: a stale DEAD-letter writes failure rows for documents
        the replacement is processing successfully, and a stale REQUEUE is worse than a lost
        update — it flips a running job back to 'queued' with locked_by=NULL, so a third worker
        can claim it alongside the one still running and every document is processed twice.

        Returns 'queued' or 'dead' when this call's write applied, 'missing' if the job is gone,
        and 'stale' when the caller no longer holds the claim — including when the job has since
        gone terminal. 'stale' replaces the old behaviour of returning 'queued'/'dead' for a
        write that was actually suppressed, which said an outcome had been recorded when none
        had."""
        from datetime import datetime, timezone, timedelta
        job = self.get_job(job_id)
        if job is None:
            return "missing"
        # Bail BEFORE the side effects, not just before the status write. The dead branch calls
        # _record_dead_scan_files first, which writes a failure row per document — so a stale
        # claim whose UPDATE is about to be refused would still record its documents as failed,
        # over a replacement that is processing them successfully. The UPDATE's own ownership
        # predicate remains the authority (this read is racy by construction); this only stops
        # the writes that happen on the way there.
        if not self._claim_is_current(job_id, worker_id, attempt):
            print(f"[acp] fail_job: job {job_id} is no longer held by {worker_id} "
                  f"attempt={attempt} — outcome refused (stale claim)", flush=True)
            return "stale"
        now = datetime.now(timezone.utc)
        if force_dead or job["attempts"] >= job["max_attempts"]:
            # BEFORE the payload is scrubbed — scrubbing is what removes the file names this needs.
            self._record_dead_scan_files(job, error, now.isoformat())
            scrubbed = self._scrub_payload_secrets(job_id)
            # Guarded against a reclaimed job's original (zombie) worker dead-lettering it AFTER
            # a second worker already completed/cancelled it — same race as complete_job's
            # docstring describes. Without this, a zombie's late failure could flip a job a
            # fresher worker already finished successfully back to 'dead', with no error raised
            # anywhere. Whichever writer's terminal state lands first wins.
            with self._db.cursor() as cur:
                if scrubbed is not None:
                    self._db.execute(cur,
                        "UPDATE jobs SET status='dead', last_error=%s, error_class=%s, "
                        "updated_at=%s, payload=%s WHERE id=%s "
                        "AND status NOT IN ('done','dead','cancelled')" + self._CLAIM_OWNED,
                        (error[:2000], error_class, now.isoformat(), scrubbed, job_id,
                         worker_id, attempt))
                else:
                    self._db.execute(cur,
                        "UPDATE jobs SET status='dead', last_error=%s, error_class=%s, "
                        "updated_at=%s WHERE id=%s "
                        "AND status NOT IN ('done','dead','cancelled')" + self._CLAIM_OWNED,
                        (error[:2000], error_class, now.isoformat(), job_id,
                         worker_id, attempt))
                won = (getattr(cur, "rowcount", 0) or 0) > 0
            if not won:
                print(f"[acp] fail_job: job {job_id} already terminal — zombie-worker "
                      "no-op (dead-letter suppressed)", flush=True)
                return "dead"
            # One greppable stdout line per dead-letter — the platform alert
            # (Log Analytics scheduled query) keys on 'job dead-lettered'.
            print(f"[acp] job dead-lettered: id={job_id} type={job.get('type')} "
                  f"class={error_class or 'unclassified'} error={error[:160]}", flush=True)
            # AFTER `won`, deliberately — the increment is not idempotent. See the method's own
            # docstring for why a folder job that dies without this wedges the whole run.
            self._record_dead_scan_folder(job)
            # The scan/scan_discover job IS the scan — unlike a per-file job (remediate_file,
            # apply_approved_values) whose death doesn't mean the whole run failed. Without
            # this, a discover job that exhausts retries (an unexpected exception the handler's
            # own try/except doesn't already catch — see _scan_discover's listing-specific one,
            # which sets scan_runs.status='failed' itself and never reaches here) leaves
            # scan_runs stuck at 'running' forever: no retry can help (attempts are exhausted),
            # no later event ever flips it, and the only user-visible signal is the generic
            # 90s "appears stalled" warning — which doesn't say it will never finish. Guarded to
            # non-terminal statuses only, so this can never clobber a scan that already
            # completed, or was cancelled/superseded, via some other path.
            if job.get("scan_id") and job.get("type") in ("scan", "scan_discover"):
                try:
                    with self._db.cursor() as cur:
                        self._db.execute(cur,
                            "UPDATE scan_runs SET status='failed' WHERE id=%s "
                            "AND status IN ('queued','running')",
                            (job["scan_id"],))
                except Exception:
                    # best-effort — the dead-letter itself must still be recorded
                    swallowed("store.fail_job: rolling back the fail_job transaction failed")
            return "dead"
        run_after = (now + timedelta(seconds=backoff_seconds)).isoformat()
        # Same reclaimed-job guard as the dead-letter branch above: a zombie's late transient
        # failure must not requeue a job a second worker already finished or dead-lettered.
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='queued', run_after=%s, locked_at=NULL, "
                "locked_by=NULL, last_error=%s, error_class=%s, updated_at=%s "
                "WHERE id=%s AND status NOT IN ('done','dead','cancelled')" + self._CLAIM_OWNED,
                (run_after, error[:2000], error_class, now.isoformat(), job_id,
                 worker_id, attempt))
            won = (getattr(cur, "rowcount", 0) or 0) > 0
        if not won:
            print(f"[acp] fail_job: job {job_id} already terminal — zombie-worker "
                  "no-op (requeue suppressed)", flush=True)
        return "queued"

    # The phase a reclaimed job carries while it waits to be picked up again.
    #
    # DISTINCT FROM 'retrying' ON PURPOSE. Both are legitimate waiting states, but they answer
    # different questions. 'retrying' means a handler raised and fail_job requeued it with
    # backoff — the process is fine, the work failed. 'reclaimed' means the worker DIED holding
    # the job: nothing failed, nothing was reported, the lease simply expired. An operator
    # reading "a previous attempt failed" about a SIGSEGV is being told the wrong thing.
    RECLAIMED_PHASE = "reclaimed"

    def reclaim_stuck_jobs(self, lease_seconds: int = 600) -> int:
        """Requeue jobs stuck in 'running' past their lease (worker died mid-job).

        Uses lease_expires_at < now() when the column is set (all jobs claimed after the
        migration), falling back to the locked_at+lease_seconds arithmetic for rows that
        pre-date the column (no lease_expires_at) — so the sweeper is correct across a
        rolling deploy.

        WHY THIS ALSO NARRATES. A worker killed by the OS runs no code on the way out: no
        `except` clause, no `on_retry` hook, no event. The graceful failure path emits
        `scan.retrying` carrying the attempt number (worker.py), which is the ONLY way an
        attempt count reaches the UI — routes/scans.py threads `attempt` out of scan_events and
        nowhere else. So a crash produced complete silence, and the run went on rendering an
        ordinary in-progress checklist as though nothing had happened.

        Measured on 2026-08-31 against a production Discovery job: the worker logged
        `double free or corruption (!prev)` and Azure recorded exit 139; the job was reclaimed
        EIGHT MINUTES later and re-claimed as attempt 2, and no surface anywhere said so. Worse
        than the silence, `claim_job` sets `phase=NULL` on every claim — so once attempt 2
        started it was indistinguishable from a first attempt.

        This closes both halves: the requeued row carries RECLAIMED_PHASE while it waits, and a
        `scan.interrupted` event carries the attempt into the SSE stream the UI already reads.
        `scan.interrupted` was already in SCAN_EVENT_KINDS and already rendered by
        frontend/src/scanHistory.js as "Interrupted" — the vocabulary and the reader existed;
        only the emitter was missing.

        The event write is best-effort by construction (append_scan_event swallows everything but
        a programming error), and it happens AFTER the UPDATE: narration must never be able to
        stop a job being reclaimed. A reclaim that lands with no event is a gap in the story, not
        a job left stuck.
        """
        from datetime import datetime, timezone, timedelta
        now = self._now()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)).isoformat()
        # Read the doomed rows BEFORE the UPDATE clears locked_by and bumps nothing else: the
        # event wants the worker that died and the attempt it died on, and both are gone from
        # the row a moment later.
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, scan_id, locked_by, attempts, type FROM jobs "
                "WHERE status='running' AND (lease_expires_at<%s OR locked_at<%s)",
                (now, cutoff))
            doomed = self._db.fetchall(cur) or []
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='queued', locked_at=NULL, locked_by=NULL, "
                "lease_expires_at=NULL, updated_at=%s, phase=%s "
                "WHERE status='running' AND (lease_expires_at<%s OR locked_at<%s)",
                (now, self.RECLAIMED_PHASE, now, cutoff))
            n = getattr(cur, "rowcount", 0) or 0
        for row in doomed:
            if not row.get("scan_id"):
                continue
            try:
                self.append_scan_event(
                    row["scan_id"], "scan.interrupted",
                    phase=self.RECLAIMED_PHASE, job_id=row.get("id"),
                    worker_id=row.get("locked_by"), attempt=row.get("attempts"),
                    detail={"reason": "lease expired — the worker stopped without reporting",
                            "job_type": row.get("type")})
            except Exception as e:  # noqa: BLE001 — narration must not fail the reclaim
                print(f"[sweeper] could not record scan.interrupted for job "
                      f"{row.get('id')}: {e}", flush=True)
        return n

    def sweep_exhausted_jobs(self) -> int:
        """Dead-letter queued jobs that have already used all their attempts.

        reclaim_stuck_jobs() requeues a running job without inspecting attempts — so a
        job reclaimed at max_attempts re-enters the queue and would keep being claimed and
        failing. This sweep catches those jobs and moves them to 'dead' exactly once, with
        a sweep-generated error message. Returns the number of jobs dead-lettered."""
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, type FROM jobs "
                "WHERE status='queued' AND attempts >= max_attempts",
                ())
            rows = self._db.fetchall(cur)
        count = 0
        for row in rows:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "UPDATE jobs SET status='dead', last_error=%s, updated_at=%s "
                    "WHERE id=%s AND status='queued' AND attempts >= max_attempts",
                    ("max_attempts reached — dead-lettered by reconciliation sweeper",
                     now, row["id"]))
                if (getattr(cur, "rowcount", 0) or 0) > 0:
                    count += 1
                    print(f"[sweeper] job dead-lettered (exhausted): id={row['id']} "
                          f"type={row.get('type')}", flush=True)
        return count

    def sweep_orphaned_scans(self, grace_seconds: int = 600) -> int:
        """Mark 'running' scan_runs with no outstanding jobs as 'interrupted'.

        A running scan with zero queued/running job rows is stranded — its worker died
        after the fan-out but before finalize ran, or the jobs were reclaimed and
        never re-enqueued. Past the grace window (default 10 min, to let discover
        finish enqueuing before the sweep can touch it) the scan is marked 'interrupted'
        and rescue_unfinalized_scans() handles re-enqueuing finalize if needed.

        Returns the number of scans marked interrupted."""
        from datetime import datetime, timezone, timedelta
        grace_cutoff = (datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, started_at FROM scan_runs "
                "WHERE status='running' AND started_at<%s "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM jobs WHERE scan_id=scan_runs.id "
                "  AND status IN ('queued','running')"
                ")",
                (grace_cutoff,))
            rows = self._db.fetchall(cur)
        count = 0
        now = self._now()
        for row in rows:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "UPDATE scan_runs SET status='interrupted', completed_at=%s "
                    "WHERE id=%s AND status='running'",
                    (now, row["id"]))
                if (getattr(cur, "rowcount", 0) or 0) > 0:
                    self._stamp_assessed_if_ran(cur, row["id"])
                    count += 1
                    print(f"[sweeper] scan {row['id']}: marked interrupted — running "
                          f"with no outstanding jobs", flush=True)
        return count

    def job_stats(self, owner: str | None = None) -> dict:
        # owner → only this user's jobs (scoped via their scans), so the queue view
        # doesn't leak other tenants' activity. None = global (operator/admin context).
        scope = " WHERE scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT status, COUNT(*) AS n FROM jobs" + scope + " GROUP BY status",
                             (owner,) if owner else ())
            return {r["status"]: r["n"] for r in self._db.fetchall(cur)}

    def oldest_queued_job(self, owner: str | None = None) -> dict | None:
        """The single longest-waiting eligible job (status='queued', run_after already due), or
        None when nothing is waiting.

        Exists to answer a question `job_stats`/`worker_tier_alive` cannot: a fresh heartbeat
        proves the worker CONTAINER is up, not that anything is actually claiming work (see
        worker.py's own max_unverified_lease_s docstring — a hung handler or, found live
        2026-08-29, a worker pool that silently booted at zero threads both look identical to
        "online" from the heartbeat alone). A queued job's own age is a fact the worker tier
        cannot fake by merely existing: if it has been waiting past a normal claim latency while
        the tier reports alive, something between "online" and "actually draining the queue" is
        broken, whatever that turns out to be this time.

        A job stuck behind a future run_after (retry backoff) is not eligible and must not count
        as evidence of a stall — same run_after<=now() gate claim_job() itself uses."""
        scope = " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, type, created_at FROM jobs WHERE status='queued' AND run_after<=%s" + scope +
                " ORDER BY created_at ASC LIMIT 1",
                (self._now(), owner) if owner else (self._now(),))
            return self._db.fetchone(cur)

    def list_jobs(self, status: str | None = None, limit: int = 200, owner: str | None = None) -> list[dict]:
        clauses, params = [], []
        if status:
            clauses.append("status=%s"); params.append(status)
        if owner:                                      # scope to the caller's own jobs
            clauses.append("scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)"); params.append(owner)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM jobs" + where + " ORDER BY updated_at DESC LIMIT %s", tuple(params))
            return self._db.fetchall(cur)

    def admin_live_activity(self, *, recent_seconds: int = 900) -> list[dict]:
        """Cross-user, payload-free live and recently completed work for the admin map.

        A run is returned once per active pipeline stage, plus completed stages whose last job
        changed within ``recent_seconds``. Keeping a short tail matters operationally: otherwise
        a fast run disappears between the user's click and the next two-second SSE snapshot and
        the map looks broken. The newest running filename is extracted for the authorized detail
        drawer; raw payloads and document contents never leave this method.
        """
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        recent_cutoff = (_dt.now(_tz.utc) - _td(seconds=max(0, recent_seconds))).isoformat()
        kinds = {
            "scan_discover": "discover", "scan_folder": "discover", "scan_batch": "discover",
            "scan_file": "assess", "scan_assess": "assess", "assess_trace": "assess",
            "remediate_file": "remediate", "rescore_file": "remediate",
            "apply_approved_values": "remediate",
            "publish_file": "release", "publish_batch": "release",
        }
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT j.scan_id,j.type,j.status,j.created_at,j.updated_at,j.payload,"
                "sr.owner_email,sr.source,sr.files,sr.files_done "
                "FROM jobs j JOIN scan_runs sr ON sr.id=j.scan_id "
                "WHERE j.scan_id IN (SELECT DISTINCT scan_id FROM jobs "
                "WHERE status IN ('queued','running')) OR "
                "(j.status='done' AND j.updated_at>=%s) "
                "ORDER BY j.updated_at DESC LIMIT %s", (recent_cutoff, 5000))
            rows = self._db.fetchall(cur)

        grouped: dict[tuple[str, str], dict] = {}
        active: set[tuple[str, str]] = set()
        recent: set[tuple[str, str]] = set()
        for row in rows:
            stage = kinds.get(row.get("type"))
            if not stage:
                continue
            key = (row["scan_id"], stage)
            item = grouped.setdefault(key, {
                "scan_id": row["scan_id"], "owner": row.get("owner_email") or "unknown",
                "source": row.get("source") or "unknown", "stage": stage,
                "queued": 0, "running": 0, "completed": 0, "total": 0,
                "started_at": row.get("created_at"), "updated_at": row.get("updated_at"),
                "oldest_queued_at": None, "current_file": None,
                "current_job_type": None, "current_rule_id": None,
            })
            status = row.get("status")
            item["total"] += 1
            if status == "queued":
                item["queued"] += 1
                created = row.get("created_at")
                if created and (not item["oldest_queued_at"] or str(created) < str(item["oldest_queued_at"])):
                    item["oldest_queued_at"] = created
            elif status == "running": item["running"] += 1
            elif status == "done":
                item["completed"] += 1
                if str(row.get("updated_at") or "") >= recent_cutoff:
                    recent.add(key)
            if status in ("queued", "running"):
                active.add(key)
            if status == "running" and not item["current_file"]:
                try:
                    payload = row.get("payload") or {}
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        item["current_file"] = (payload.get("file") or payload.get("filename")
                                                or payload.get("path"))
                        item["current_rule_id"] = (payload.get("current_rule_id")
                                                   or payload.get("rule_id") or payload.get("wcag"))
                        item["current_job_type"] = row.get("type")
                except (TypeError, ValueError):
                    pass
            if row.get("created_at") and str(row["created_at"]) < str(item.get("started_at") or row["created_at"]):
                item["started_at"] = row["created_at"]
            if str(row.get("updated_at") or "") > str(item.get("updated_at") or ""):
                item["updated_at"] = row.get("updated_at")
        result = [grouped[key] for key in active | recent]
        for item in result:
            item["status"] = "active" if (item["queued"] or item["running"]) else "recent"
        waiting = sorted((r for r in result if r["queued"]),
                         key=lambda r: str(r.get("oldest_queued_at") or ""))
        for position, item in enumerate(waiting, 1):
            item["queue_position"] = position
        return result

    def list_scan_jobs_of_type(self, scan_id: str, job_type: str) -> list[dict]:
        """Every job of one type already enqueued for one scan, whatever its status.

        The RESUME primitive for a fan-out handler. enqueue_job has no idempotency key, so a
        fan-out that is interrupted half-way and then reclaimed would enqueue the whole
        population a second time — the first half twice, and `files` (set from the population,
        not from the queue) describing neither. Reading what is already there lets the second
        attempt enqueue only the remainder, which is what makes the fan-out a checkpoint rather
        than a restart.

        Status is deliberately NOT filtered: a job that already ran and is 'done', or one that
        dead-lettered, must both count as enqueued. Re-enqueuing a done file would redo work the
        results already reflect, and re-enqueuing a dead-lettered one would resurrect a job the
        queue has deliberately given up on.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id, type, status, payload FROM jobs WHERE scan_id=%s AND type=%s",
                (scan_id, job_type))
            return self._db.fetchall(cur)

    # Job `type` -> the user-facing phase it belongs to, for the pickup-estimate panel on
    # Discover/Assess/Remediate. Several types (scan_finalize) are shared tail-of-pipeline
    # steps; classified under the phase that enqueues them in the common case.
    _JOB_KIND = {
        "scan_batch": "discover", "scan_file": "discover", "scan_folder": "discover",
        "scan_finalize": "discover",
        "scan_assess": "assess", "assess_trace": "assess",
        "remediate_file": "remediate", "rescore_file": "remediate",
        "apply_approved_values": "remediate",
    }
    _KIND_TYPES = {"discover": (), "assess": (), "remediate": ()}
    for _jt, _k in _JOB_KIND.items():
        _KIND_TYPES[_k] = _KIND_TYPES[_k] + (_jt,)
    del _jt, _k

    def queue_estimate(self, scan_id: str, kind: str, *, owner: str | None = None,
                       ready_workers: int | None = None, window_s: int = 1800) -> dict:
        """"When will my work actually begin?" for one scan's Discover/Assess/Remediate job —
        the queue-status panel's data source.

        Answers with what the `jobs` table can actually prove, and says so when it can't:
          - compatible_jobs_ahead / compatible_workers_busy are exact live counts, not modeled.
          - the wait estimate is `compatible_jobs_ahead ÷ recent throughput` (jobs of this kind
            completed in the last `window_s`), which needs no per-worker concurrency figure —
            aggregate throughput already accounts for however many workers are actually running.
            `ready_workers` is caller-supplied (core.WORKERS, or the split-topology worker tier)
            purely for display ("N workers busy / M ready"); it plays no part in the wait math.
          - fewer than 3 completions in the window means there isn't enough recent history for
            an honest range, so state is "insufficient_history" and earliest_at/latest_at stay
            null rather than a confident-looking guess from thin data.

        Returns {"available": False} when the scan has no live job of this kind (nothing
        queued or running — already done, or this phase hasn't started)."""
        from datetime import datetime as _dt, timedelta as _td
        types = self._KIND_TYPES.get(kind, ())
        if not types:
            raise ValueError(f"unknown queue-estimate kind: {kind!r}")
        now = self._now()
        with self._db.cursor() as cur:
            # Owner scoping happens once here, up front — every count below is either about
            # THIS job (already owner-checked) or a GLOBAL queue fact (how many jobs of this
            # kind are queued/running across all tenants), which is infrastructure state, not
            # per-tenant data, and matches oldest_queued_job's/job_stats' own global-by-default
            # shape.
            self._db.execute(cur,
                "SELECT j.* FROM jobs j JOIN scan_runs s ON s.id=j.scan_id "
                "WHERE j.scan_id=%s AND j.type IN (" + ",".join(["%s"] * len(types)) + ") "
                "AND j.status IN ('queued','running') "
                "AND (%s IS NULL OR s.owner_email=%s) "
                "ORDER BY CASE j.status WHEN 'running' THEN 0 ELSE 1 END, j.priority, j.run_after "
                "LIMIT 1",
                (scan_id, *types, owner, owner))
            job = self._db.fetchone(cur)
            if not job:
                return {"available": False}

            if job["status"] == "running":
                return {"available": True, "state": "claimed", "job_type": job["type"],
                        "worker_assigned_at": job.get("locked_at"), "phase": job.get("phase"),
                        "estimated_at": now}

            if job.get("run_after") and job["run_after"] > now:
                return {"available": True, "state": "scheduled", "job_type": job["type"],
                        "run_after": job["run_after"], "estimated_at": now}

            if ready_workers is not None and ready_workers <= 0:
                return {"available": True, "state": "no_worker_available", "job_type": job["type"],
                        "compatible_workers_busy": 0, "ready_workers": 0, "estimated_at": now}

            type_ph = ",".join(["%s"] * len(types))
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE type IN (" + type_ph + ") "
                "AND status='queued' AND run_after<=%s "
                "AND (priority < %s OR (priority = %s AND run_after < %s))",
                (*types, now, job["priority"], job["priority"], job["run_after"]))
            jobs_ahead = self._db.fetchone(cur)["n"]

            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE type IN (" + type_ph + ") AND status='running'",
                types)
            workers_busy = self._db.fetchone(cur)["n"]

            window_start = (_dt.fromisoformat(now) - _td(seconds=window_s)).isoformat()
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE type IN (" + type_ph + ") "
                "AND status='done' AND updated_at>=%s",
                (*types, window_start))
            recent_done = self._db.fetchone(cur)["n"]

        base = {"available": True, "job_type": job["type"],
                "compatible_jobs_ahead": jobs_ahead, "compatible_workers_busy": workers_busy,
                "ready_workers": ready_workers, "estimated_at": now}
        if recent_done < 3:
            return {**base, "state": "insufficient_history",
                    "earliest_at": None, "latest_at": None, "confidence": None, "basis": None}

        throughput_per_s = recent_done / window_s
        wait_s = jobs_ahead / throughput_per_s
        now_dt = _dt.fromisoformat(now)
        confidence = "high" if recent_done >= 10 else "medium"
        return {**base, "state": "estimated",
                "earliest_at": (now_dt + _td(seconds=wait_s * 0.7)).isoformat(),
                "latest_at": (now_dt + _td(seconds=wait_s * 1.3)).isoformat(),
                "confidence": confidence, "basis": f"recent_{kind}_throughput"}

    # ── Document-centric layer (ADR 0003, Phase 1) ─────────────────────────────
    def upsert_document(self, doc_id: str, *, source: str, path: str, content_hash: str | None,
                        owner: str | None, created_at: str, last_seen: str,
                        triage_score: int, triage_rationale: str,
                        classify: dict | None = None, owner_email: str | None = None,
                        size_kb: int | None = None) -> None:
        """Upsert a document's scan-derived fields. department/regulatory_tags/
        business_criticality/usage_signal aren't set here (no real-scan source for them
        yet — ADR 0003's own noted gap) and are left for an admin/connector to populate
        later; the ON CONFLICT clause deliberately doesn't touch those columns.

        `classify` (ADR 0020 stage 2) is the Discover-side inventory peek — pages/images/
        has_text/has_images/is_scanned/doc_class. Additive: absent → those columns are left
        as-is (so a re-run without classify never wipes a prior classification).

        `size_kb` is NOT part of `classify` — it's a plain scan-derived fact (like path or
        last_seen), not an ADR-0020 classification, so it always overwrites on conflict rather
        than being left alone when absent. The caller already computes it (scanner.py's
        _inv_size_kb, the same value scan_inventory.size_kb stores) for every file; it simply
        was not threaded through to this table until now."""
        c = classify or {}
        b = lambda v: (1 if v else 0) if v is not None else None  # noqa: E731
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO documents(doc_id,source,path,content_hash,owner,created_at,"
                "last_seen,triage_score,triage_rationale,pages,images,has_text,has_images,"
                "is_scanned,doc_class,classified_at,owner_email,size_kb) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                # owner_email IS updated on conflict, and the reason is worth stating because the
                # alternative looks safer and is not. doc_id falls back to
                # `{source}:{content_hash}` (documents.resolve_doc_id), so two tenants scanning
                # the SAME BYTES — a shared template, the same public PDF — collide on one row.
                #
                # Either choice loses VISIBILITY for one of them; neither leaks, because a scoped
                # read matches a single owner_email. Updating means the row reflects whoever
                # scanned last, which at least stays consistent with the rest of the row (path,
                # last_seen, classification) — all of which already come from that same scan.
                # Leaving it would pin ownership to whoever happened to scan first while every
                # other column describes someone else's file.
                #
                # The real fix is a composite key, PRIMARY KEY (owner_email, doc_id), so the two
                # tenants get two rows. That is a bigger migration than adding a column and is
                # deliberately NOT smuggled in here — see the test that pins this behaviour so the
                # follow-up is a decision rather than a discovery.
                "ON CONFLICT(doc_id) DO UPDATE SET path=EXCLUDED.path, "
                "content_hash=EXCLUDED.content_hash, last_seen=EXCLUDED.last_seen, "
                "owner_email=EXCLUDED.owner_email, size_kb=EXCLUDED.size_kb, "
                "triage_score=EXCLUDED.triage_score, triage_rationale=EXCLUDED.triage_rationale"
                + (", pages=EXCLUDED.pages, images=EXCLUDED.images, has_text=EXCLUDED.has_text, "
                   "has_images=EXCLUDED.has_images, is_scanned=EXCLUDED.is_scanned, "
                   "doc_class=EXCLUDED.doc_class, classified_at=EXCLUDED.classified_at"
                   if classify else ""),
                (doc_id, source, path, content_hash, owner, created_at, last_seen,
                 triage_score, triage_rationale,
                 c.get("pages"), c.get("images"), b(c.get("has_text")), b(c.get("has_images")),
                 b(c.get("is_scanned")), c.get("doc_class"),
                 (last_seen if classify else None), owner_email, size_kb))

    def estate_by_department(self, owner_email: str, *, department: str | None = None,
                             owner: str | None = None) -> list[dict]:
        """Document counts per department for ONE tenant — the control plane's core query.

        SCOPED, AND NULL IS NOT A WILDCARD. `owner_email IS NOT NULL AND owner_email = %s` rather
        than a bare equality: rows written before that column existed carry NULL, and in SQL
        `NULL = 'anyone'` is not true — but a hand-written OR that tried to be helpful about
        "unknown" rows is exactly how one customer's estate reaches another. Excluding them shows
        a document to nobody; including them shows it to the wrong person. Those are not the same
        size of mistake, so the omission is deliberate and stated rather than incidental.
        `owner_email` is REQUIRED, not defaulted — an optional tenant is one forgotten argument
        away from an unscoped read, and the caller always knows who is asking.

        `department` and `owner` narrow further and are the operator's own filters. NULL/empty
        departments are reported under a single "(unassigned)" bucket rather than dropped: ADR
        0003 notes department has no scan-derived source yet, so on most estates that bucket IS
        the estate, and hiding it would show an operator a confident, tiny, wrong total.
        """
        where = ["owner_email IS NOT NULL", "owner_email = %s"]
        params: list = [owner_email]
        if department:
            where.append("COALESCE(NULLIF(department, ''), '(unassigned)') = %s")
            params.append(department)
        if owner:
            where.append("owner = %s")
            params.append(owner)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COALESCE(NULLIF(department, ''), '(unassigned)') AS department, "
                "COUNT(*) AS documents, "
                "COUNT(DISTINCT owner) AS owners, "
                "AVG(triage_score) AS avg_triage, "
                "MAX(last_seen) AS last_seen "
                f"FROM documents WHERE {' AND '.join(where)} "
                "GROUP BY COALESCE(NULLIF(department, ''), '(unassigned)') "
                "ORDER BY COUNT(*) DESC", tuple(params))
            rows = [dict(r) for r in self._db.fetchall(cur)]
        for r in rows:
            # AVG returns a Decimal on Postgres and a float on SQLite. The UI renders it either
            # way, but a Decimal is not JSON-serialisable and the failure is a 500 from the route
            # rather than anything that points at this line.
            r["avg_triage"] = round(float(r["avg_triage"]), 1) if r["avg_triage"] is not None else None
        return rows

    def estate_owners(self, owner_email: str) -> list[dict]:
        """Document counts per BUSINESS owner, for one tenant. The other half of "filter by
        dept, user" — and a different question from list_org_owners(), which answers "which
        tenants exist". Same scoping rule as above."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COALESCE(NULLIF(owner, ''), '(unassigned)') AS owner, "
                "COUNT(*) AS documents, "
                "COUNT(DISTINCT COALESCE(NULLIF(department, ''), '(unassigned)')) AS departments "
                "FROM documents WHERE owner_email IS NOT NULL AND owner_email = %s "
                "GROUP BY COALESCE(NULLIF(owner, ''), '(unassigned)') "
                "ORDER BY COUNT(*) DESC", (owner_email,))
            return [dict(r) for r in self._db.fetchall(cur)]

    def get_document_examined(self, path: str) -> dict | None:
        """The engine-reported inventory counts for a document, by path (latest classification
        wins). Backs the honest examined-element denominators (ADR 0026 Epic 2): classify() walks
        every raster media part / PDF page at scan time, so "of N images examined" is a real count,
        not an estimate. None when the document was never classified — the UI then shows nothing."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT pages, images, has_text, is_scanned, classified_at FROM documents "
                "WHERE path=%s AND classified_at IS NOT NULL ORDER BY classified_at DESC", (path,))
            row = self._db.fetchone(cur)
            return dict(row) if row else None

    def get_document(self, doc_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM documents WHERE doc_id=%s", (doc_id,))
            return self._db.fetchone(cur)

    # ── Per-violation remediation state (ADR 0003, Phase 2) ────────────────────
    def list_file_identities(self, scan_id: str) -> list[dict]:
        """{file, drive_file_id, checksum} for every file in a scan -- the inputs
        resolve_doc_id needs, kept as its own narrow query so get_scan's broader
        (widely-called) SELECT doesn't grow just for this."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, drive_file_id, checksum FROM file_records WHERE scan_id=%s",
                (scan_id,))
            return self._db.fetchall(cur)

    def seed_remediation_state(self, doc_id: str, rule_id: str, scan_id: str) -> None:
        """Create a 'not_started' row for a newly-seen violation. Never overwrites an
        existing row -- state only ever moves forward via an explicit transition
        (upsert_remediation_state), so a violation still failing on a later scan doesn't
        get silently reset if it had already progressed."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO remediation_state(doc_id,rule_id,state,updated_at,last_scan_id) "
                "VALUES(%s,%s,'not_started',%s,%s) ON CONFLICT(doc_id,rule_id) DO NOTHING",
                (doc_id, rule_id, self._now(), scan_id))

    def upsert_remediation_state(self, doc_id: str, rule_id: str, state: str, scan_id: str) -> None:
        """Explicit forward transition (HITL resolution, auto-remediation applied)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO remediation_state(doc_id,rule_id,state,updated_at,last_scan_id) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(doc_id,rule_id) DO UPDATE SET "
                "state=EXCLUDED.state, updated_at=EXCLUDED.updated_at, last_scan_id=EXCLUDED.last_scan_id",
                (doc_id, rule_id, state, self._now(), scan_id))

    def get_remediation_state(self, doc_id: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id, state, updated_at, last_scan_id FROM remediation_state "
                "WHERE doc_id=%s ORDER BY rule_id", (doc_id,))
            return self._db.fetchall(cur)

    def get_remediation_state_for_file(self, scan_id: str, file: str) -> list[dict]:
        """Same as get_remediation_state, but keyed by (scan_id, file) — what the UI
        actually has on hand — instead of doc_id, which it doesn't."""
        from documents import resolve_doc_id
        drive_file_id = self.get_file_drive_id(scan_id, file)
        doc_id = resolve_doc_id("drive", drive_file_id, file, None)
        return self.get_remediation_state(doc_id)

    def list_auto_fail_rules(self, scan_id: str, file: str) -> list[str]:
        """rule_ids that FAILed for this file and are deterministically auto-fixable --
        what a successful remediate_file run actually addresses."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id FROM scan_rule_traces "
                "WHERE scan_id=%s AND file=%s AND fix_mode='auto' AND outcome='FAIL'",
                (scan_id, file))
            return [r["rule_id"] for r in self._db.fetchall(cur)]

    # ── Configurable disposition (ADR 0003, Phase 3 — preview only) ────────────
    def create_disposition_policy(self, policy_id: str, *, name: str, match: str, action: str,
                                  action_config: str, requires_approval: bool, enabled: bool,
                                  owner_email: str | None = None) -> None:
        """`priority` is assigned here, not passed in: the next integer past this tenant's
        current max (0 when they have no rules yet), computed in the same INSERT rather than a
        separate SELECT so two rules created back-to-back can't race onto the same priority.
        A brand new rule always starts LAST — the safe default; reordering is a separate,
        deliberate act (reorder_disposition_policies)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO disposition_policy(policy_id,name,match,action,action_config,"
                "requires_approval,enabled,owner_email,priority) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,"
                "(SELECT COALESCE(MAX(priority),0)+1 FROM disposition_policy WHERE owner_email=%s))",
                (policy_id, name, match, action, action_config, int(requires_approval),
                 int(enabled), owner_email, owner_email))

    def list_disposition_policies(self, owner: str | None = None) -> list[dict]:
        """Every rule this tenant authored — filtered to `owner_email`, same NULL-excluded
        semantics as list_all_documents. `disposition_policy` had NO ownership column at all
        until this migration: `list_policies()` returned every rule to every signed-in user,
        demo account included, which is the isolation gap this scoping closes.

        ORDER BY priority (NULLs last — a pre-priority row, not a claim to run first), then name
        as the tiebreaker rows without a priority already used. This is THE precedence order:
        handlers._evaluate_discover_lifecycle_rules and the conflicts report both just consume
        whatever order this returns, so reordering here is reordering evaluation, not a
        display-only sort."""
        order = "ORDER BY CASE WHEN priority IS NULL THEN 1 ELSE 0 END, priority, name"
        with self._db.cursor() as cur:
            if owner:
                self._db.execute(cur,
                    f"SELECT * FROM disposition_policy WHERE owner_email=%s {order}", (owner,))
            else:
                self._db.execute(cur, f"SELECT * FROM disposition_policy {order}")
            return self._db.fetchall(cur)

    def reorder_disposition_policies(self, owner: str, policy_ids: list[str]) -> None:
        """Assign priority 1..N to `policy_ids` in the order given — the whole ordering in one
        call, not a per-rule "move up/down" that could interleave with another tab's edit.
        The caller (routes/disposition.reorder_policies) is responsible for checking `policy_ids`
        is exactly this owner's current rule set before calling; this method trusts it and just
        writes the numbers."""
        with self._db.cursor() as cur:
            for i, policy_id in enumerate(policy_ids, start=1):
                self._db.execute(cur,
                    "UPDATE disposition_policy SET priority=%s WHERE policy_id=%s AND owner_email=%s",
                    (i, policy_id, owner))

    def get_disposition_policy(self, policy_id: str, owner: str | None = None) -> dict | None:
        """A single rule, or None if it doesn't exist OR belongs to a different tenant — the
        same shape as get_scan(sid, owner=...): a foreign policy_id 404s rather than leaking
        whether it exists. Pass owner=None only for an internal, already-scoped lookup (e.g.
        _readable's enrichment join, which starts from an owner-filtered policy list)."""
        with self._db.cursor() as cur:
            if owner:
                self._db.execute(cur,
                    "SELECT * FROM disposition_policy WHERE policy_id=%s AND owner_email=%s",
                    (policy_id, owner))
            else:
                self._db.execute(cur, "SELECT * FROM disposition_policy WHERE policy_id=%s",
                                 (policy_id,))
            return self._db.fetchone(cur)

    def set_disposition_policy_enabled(self, policy_id: str, enabled: bool) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE disposition_policy SET enabled=%s WHERE policy_id=%s",
                             (int(enabled), policy_id))

    def delete_disposition_policy(self, policy_id: str) -> None:
        """Remove a rule's row outright. The caller (routes/disposition.delete_policy) is the
        policy: a rule with any disposition_audit history is refused before this is ever called,
        the same guard update_disposition_policy's caller applies to a definition change — a
        deleted policy_id would otherwise leave audit rows and scan_inventory.lifecycle_rule_id
        references naming a rule that no longer exists to explain itself. A rule with no history
        has nothing pointing at it, so removing the row loses nothing an auditor would look for."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM disposition_policy WHERE policy_id=%s", (policy_id,))

    def update_disposition_policy(self, policy_id: str, *, name: str, match: str, action: str,
                                  action_config: str, requires_approval: bool) -> None:
        """Overwrite a saved rule's editable columns. NEVER touches `enabled`.

        That omission is the safety property, not an oversight. `enabled` is what decides whether a
        rule runs at all, and it has its own route and its own audit line
        (set_disposition_policy_enabled). If an edit could also set it, a save a person read as
        "fix the folder path" would be capable of arming the rule at the same time — and the whole
        posture of this feature is that rules are created disabled and armed by a separate,
        deliberate act.

        The caller (routes/disposition.update_policy) decides whether the edit is ALLOWED — a rule
        that has already produced audit records may no longer change its definition, because
        nothing records which definition produced them. This method is the write, not the policy.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE disposition_policy SET name=%s, match=%s, action=%s, action_config=%s, "
                "requires_approval=%s WHERE policy_id=%s",
                (name, match, action, action_config, int(requires_approval), policy_id))

    def merge_scan_scope(self, scan_id: str, facts: dict) -> None:
        """Merge `facts` into an existing run's `scan_runs.scope` JSON, leaving every other key be.

        Read-modify-write rather than a targeted column, because `scope` IS a JSON blob — that is
        how `skipped_out_of_scope`, `excluded` and `inventory` all ride along without a migration
        (see init_scan_run). This is the same shelf, written at a later moment: discovery records
        what it covered at discover time, and the facts Assess learns (what its lifecycle rules
        held back) can only be recorded once Assess has run.

        ONLY WRITES WHAT IT IS GIVEN. A key the caller does not pass is not touched and not
        defaulted — an absent count must stay absent, because a reader distinguishes "this run
        did not record that" from "this run measured zero", and collapsing the first into the
        second is a reassuring answer to a question nobody asked.

        Returns quietly, changing nothing, when the run does not exist or its scope is unreadable.
        An unreadable scope is already a loss; overwriting it with a fresh dict holding only these
        three keys would turn that into the loss of the discovery boundary as well.
        """
        if not facts:
            return
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT scope FROM scan_runs WHERE id=%s", (scan_id,))
            row = self._db.fetchone(cur)
            if row is None:
                return
            raw = row.get("scope")
            if isinstance(raw, dict):
                scope = dict(raw)
            elif raw:
                try:
                    scope = _json.loads(raw)
                except Exception:
                    return          # unreadable is unknown — never overwrite it with a guess
                if not isinstance(scope, dict):
                    return
            else:
                scope = {}
            scope.update(facts)
            self._db.execute(cur, "UPDATE scan_runs SET scope=%s WHERE id=%s",
                             (_json.dumps(scope), scan_id))

    def list_all_documents(self, owner: str | None = None) -> list[dict]:
        """Document rows -- used by the disposition preview evaluator, which needs the full
        (tenant-scoped) set to run a predicate in Python (see api/disposition.py).

        `owner` scopes to `documents.owner_email` — the column added specifically to separate
        WHICH TENANT a document belongs to from `owner` (a business-owner fact that collides
        with a tenant id the moment anyone populates it as designed; see the column's own
        migration comment above). Omit `owner` only for genuinely cross-tenant internal callers
        (there are none today); every route-level caller must pass the requesting user's email.

        NULL is EXCLUDED when `owner` is given, never matched as a wildcard — a row predating
        this column, or written by a path that never stamped it, is tenant-unknown. The cost of
        excluding it is a document nobody's disposition policy can see; the cost of including it
        is a document the wrong customer's policy can act on. Those are not the same size of
        mistake, so the query never uses `owner_email IS NULL OR owner_email=%s`.
        """
        with self._db.cursor() as cur:
            if owner:
                self._db.execute(cur, "SELECT * FROM documents WHERE owner_email=%s", (owner,))
            else:
                self._db.execute(cur, "SELECT * FROM documents")
            return self._db.fetchall(cur)

    def list_pending_disposition_candidates(self, owner: str | None = None) -> list[dict]:
        """`scan_inventory` rows for scans still awaiting Assess (`status='discovered'`),
        reshaped like a `documents` row so `disposition.matches()` can evaluate them exactly as
        `handlers._evaluate_discover_lifecycle_rules` already does at Discover time.

        Exists because `list_all_documents` alone — the `documents` table, written only by
        Assess's `upsert_document` — is what the preview/conflicts evaluators
        (api/routes/disposition.py) read. A Discover-only estate that has never been assessed has
        ZERO `documents` rows no matter how large the real estate is, so a rule preview always
        reported "would_match: 0" regardless of what it would actually tag at the next Discover —
        found live 2026-08-21 on a fresh 385-file account: an unconditioned-equivalent rule that
        should have matched virtually everything still previewed as matching nothing.

        Scoped to `status='discovered'` scans only: once Assess runs, its files become real
        `documents` rows and the scan's status moves off 'discovered' (`set_scan_status`) — so a
        file is covered by exactly one of `list_all_documents` and this method at any time, never
        both, and the two lists never need deduplicating against each other.
        """
        with self._db.cursor() as cur:
            q = ("SELECT si.scan_id, si.file, si.path, si.parent_folder, si.created_at, "
                 "si.source_modified, si.owner, si.doc_class, si.size_kb, "
                 "si.lifecycle_status, sr.source "
                 "FROM scan_inventory si JOIN scan_runs sr ON sr.id = si.scan_id "
                 "WHERE sr.status='discovered'")
            params: tuple = ()
            if owner:
                q += " AND sr.owner_email=%s"
                params = (owner,)
            self._db.execute(cur, q, params)
            rows = self._db.fetchall(cur)
        return [{"doc_id": f"scan:{r['scan_id']}:{r['file']}", "source": r.get("source"),
                 "path": r.get("path"), "parent_folder": r.get("parent_folder"),
                 "created_at": r.get("created_at"), "source_modified": r.get("source_modified"),
                 "owner": r.get("owner"), "doc_class": r.get("doc_class"),
                 "size_kb": r.get("size_kb"),
                 "lifecycle_status": r.get("lifecycle_status")}
                for r in rows]

    # ── Per-file WCAG scope rules (PRD §4.4 / AC-09 — C4) ───────────────────────
    def create_scope_rule(self, rule_id: str, *, name: str, selector: str, value: str,
                          codes: list[str], priority: int = 0, is_override: bool = False,
                          enabled: bool = True, created_by: str | None = None) -> None:
        """Persist a scope rule. `codes` is stored as a JSON array. Caller validates the rule
        (api/scope_resolver.validate_scope_rule) before this."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scope_rule(rule_id,name,selector,value,codes,priority,is_override,"
                "enabled,created_at,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (rule_id, name, selector, value, _json.dumps(list(codes)), int(priority),
                 int(is_override), int(enabled), self._now(), created_by))

    def list_scope_rules(self, enabled_only: bool = False) -> list[dict]:
        """All scope rules, codes decoded to a list, ordered by priority desc then name.
        `is_override`/`enabled` come back as bools for the resolver."""
        import json as _json
        q = "SELECT * FROM scope_rule"
        if enabled_only:
            q += " WHERE enabled=1"
        q += " ORDER BY priority DESC, name"
        with self._db.cursor() as cur:
            self._db.execute(cur, q)
            rows = self._db.fetchall(cur)
        for r in rows:
            r["codes"] = _json.loads(r.get("codes") or "[]")
            r["is_override"] = bool(r.get("is_override"))
            r["enabled"] = bool(r.get("enabled"))
        return rows

    def get_scope_rule(self, rule_id: str) -> dict | None:
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM scope_rule WHERE rule_id=%s", (rule_id,))
            r = self._db.fetchone(cur)
        if r:
            r["codes"] = _json.loads(r.get("codes") or "[]")
            r["is_override"] = bool(r.get("is_override"))
            r["enabled"] = bool(r.get("enabled"))
        return r

    def set_scope_rule_enabled(self, rule_id: str, enabled: bool) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE scope_rule SET enabled=%s WHERE rule_id=%s",
                             (int(enabled), rule_id))

    def delete_scope_rule(self, rule_id: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM scope_rule WHERE rule_id=%s", (rule_id,))

    # ── Disposition audit (ADR 0003 Phase 3 — execute path) ─────────────────────
    def create_disposition_audit(self, audit_id: str, *, doc_id: str, policy_id: str,
                                 action: str, result: str, detail: str,
                                 owner_email: str | None = None) -> None:
        """Append-only, like decision_log: rows are inserted and their result may move
        forward (pending_approval → applied/failed/rejected) but never deleted.

        owner_email is stamped at creation from the caller's identity, not re-derived from
        doc_id/policy_id — the route has already confirmed both belong to this tenant before
        calling, so this is a record of who ran the disposition, same pattern as decision_log."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO disposition_audit(id,ts,doc_id,policy_id,action,result,detail,"
                "owner_email) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (audit_id, self._now(), doc_id, policy_id, action, result, detail, owner_email))

    def bulk_create_disposition_audit(self, rows: list) -> None:
        """Bulk-insert disposition audit rows accumulated by the lifecycle rule evaluator.
        rows: (audit_id, doc_id, policy_id, action, result, detail, owner_email, policy_version).

        policy_version is REQUIRED rather than defaulted: a row that cannot say which version of
        a rule produced it can never be part of a grouped approval (PRD §8), and defaulting it to
        1 would make a stale row look like a current one to the batch route."""
        if not rows:
            return
        now = self._now()
        with self._db.cursor() as cur:
            self._db.executemany(cur,
                "INSERT INTO disposition_audit(id,ts,doc_id,policy_id,action,result,detail,"
                "owner_email,policy_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(id) DO NOTHING",
                [(audit_id, now, doc_id, policy_id, action, result, detail, owner_email, version)
                 for audit_id, doc_id, policy_id, action, result, detail, owner_email, version
                 in rows])

    def list_disposition_audit_by_ids(self, audit_ids: list[str], owner: str) -> list[dict]:
        """The batch a reviewer actually selected, in ONE query, owner-scoped.

        PRD §11: "Bulk approval displays and submits explicit document ids; it never means 'all
        current matches' at execute time." So this takes ids and nothing else — there is
        deliberately no filter-based sibling that could re-expand to whatever matches now."""
        if not audit_ids:
            return []
        placeholders = ",".join(["%s"] * len(audit_ids))
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT * FROM disposition_audit WHERE id IN ({placeholders}) AND owner_email=%s",
                (*audit_ids, owner))
            return self._db.fetchall(cur)

    def get_disposition_audit(self, audit_id: str, owner: str | None = None) -> dict | None:
        with self._db.cursor() as cur:
            if owner:
                self._db.execute(cur,
                    "SELECT * FROM disposition_audit WHERE id=%s AND owner_email=%s",
                    (audit_id, owner))
            else:
                self._db.execute(cur, "SELECT * FROM disposition_audit WHERE id=%s", (audit_id,))
            return self._db.fetchone(cur)

    def list_disposition_audit(self, result: str | None = None,
                               policy_id: str | None = None, doc_id: str | None = None,
                               limit: int = 500, owner: str | None = None) -> list[dict]:
        q, params = "SELECT * FROM disposition_audit", []
        conds = []
        if owner:
            conds.append("owner_email=%s"); params.append(owner)
        if result:
            conds.append("result=%s"); params.append(result)
        if policy_id:
            conds.append("policy_id=%s"); params.append(policy_id)
        if doc_id:
            conds.append("doc_id=%s"); params.append(doc_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY ts DESC LIMIT %s"; params.append(limit)
        with self._db.cursor() as cur:
            self._db.execute(cur, q, tuple(params))
            return self._db.fetchall(cur)

    def set_disposition_audit_result(self, audit_id: str, result: str, detail: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE disposition_audit SET result=%s, detail=%s WHERE id=%s",
                (result, detail, audit_id))

    def set_disposition_before_state(self, audit_id: str, before: dict | None) -> None:
        """Record what the file looked like before an applied action (PRD §8).

        Written only on the applied path and never overwritten: a second write would mean the
        stored 'before' no longer describes the state the first action moved the file out of,
        and an undo against that is a move to somewhere the file has never been. NULL stays NULL
        for a failure, because a before-state that MIGHT be true is worse than none."""
        if not before:
            return
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE disposition_audit SET before_state=%s "
                "WHERE id=%s AND before_state IS NULL",
                (json.dumps(before, separators=(",", ":")), audit_id))

    def get_disposition_before_state(self, audit_id: str, owner: str) -> dict | None:
        """The recorded before-state for one audit row, or None. Owner-scoped."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT before_state FROM disposition_audit WHERE id=%s AND owner_email=%s",
                (audit_id, owner))
            row = self._db.fetchone(cur)
        if not row or not row.get("before_state"):
            return None
        try:
            return json.loads(row["before_state"])
        except Exception:      # noqa: BLE001 — an unreadable record must refuse, never guess
            return None

    def doc_has_disposition(self, doc_id: str, policy_id: str) -> bool:
        """True if this policy already produced a live outcome for this doc — used to
        make execute idempotent (rejected/failed rows don't block a re-run).

        'approved' is LIVE. A decision recorded without execution (approve?execute=false) is
        still a decision: leaving it out would let the next execute run re-propose the same
        document, asking the reviewer a question they have already answered. rejected/failed
        stay non-live deliberately — those are the cases a re-run should be free to raise again.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT 1 FROM disposition_audit WHERE doc_id=%s AND policy_id=%s "
                "AND result IN ('pending_approval','applied','approved') LIMIT 1",
                (doc_id, policy_id))
            return self._db.fetchone(cur) is not None

    def get_scan_dispositions(self, scan_id: str) -> set:
        """Return the set of (doc_id, policy_id) pairs that already have a live outcome
        for this scan. One query replaces N per-file doc_has_disposition() calls in the
        lifecycle rule evaluator (idempotency guard AC-13, bulk pre-load path)."""
        prefix = f"scan:{scan_id}:"
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT doc_id, policy_id FROM disposition_audit "
                "WHERE doc_id LIKE %s AND result IN ('pending_approval','applied','approved')",
                (prefix + "%",))
            return {(r["doc_id"], r["policy_id"]) for r in self._db.fetchall(cur)}

    # ── Phased remediation campaigns (ADR 0003, Phase 4) ────────────────────────
    def create_campaign(self, campaign_id: str, *, name: str, status: str, scope: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO campaign(campaign_id,name,status,scope,created_at) VALUES(%s,%s,%s,%s,%s)",
                (campaign_id, name, status, scope, self._now()))

    def list_campaigns(self, scan_id: str | None = None) -> list[dict]:
        """scan_id filters in Python (scope is opaque JSON) -- campaign counts are
        small, not worth a JSON-path query across the sqlite/postgres split."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM campaign ORDER BY created_at DESC")
            rows = self._db.fetchall(cur)
        if scan_id is None:
            return rows
        import json as _json
        return [r for r in rows if _json.loads(r["scope"] or "{}").get("scan_id") == scan_id]

    def get_campaign(self, campaign_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM campaign WHERE campaign_id=%s", (campaign_id,))
            return self._db.fetchone(cur)

    def update_campaign_status(self, campaign_id: str, status: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE campaign SET status=%s WHERE campaign_id=%s", (status, campaign_id))

    def create_campaign_batch(self, batch_id: str, *, campaign_id: str, seq: int, status: str,
                              filter: str, deadline: str | None) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO campaign_batch(batch_id,campaign_id,seq,status,filter,deadline) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (batch_id, campaign_id, seq, status, filter, deadline))

    def list_campaign_batches(self, campaign_id: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM campaign_batch WHERE campaign_id=%s ORDER BY seq", (campaign_id,))
            return self._db.fetchall(cur)

    def update_campaign_batch_status(self, batch_id: str, status: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE campaign_batch SET status=%s WHERE batch_id=%s", (status, batch_id))

    # ── ACP Managed Content Workspace (ADR 0044, PRD Phase 1) ───────────────────
    _CONTENT_WORKSPACE_COLS = (
        "id,owner_email,name,purpose,business_owner,department,wcag_standard,retention_policy,"
        "permitted_file_types,due_date,project,processing_region,external_ai_policy,status,"
        "created_at,updated_at")

    def create_content_workspace(self, workspace_id: str, *, owner_email: str, name: str,
                                 purpose: str | None = None, business_owner: str | None = None,
                                 department: str | None = None, wcag_standard: str | None = None,
                                 retention_policy: str | None = None,
                                 permitted_file_types: list[str] | None = None,
                                 due_date: str | None = None, project: str | None = None,
                                 processing_region: str | None = None,
                                 external_ai_policy: str | None = None) -> None:
        import json as _json
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"INSERT INTO content_workspaces({self._CONTENT_WORKSPACE_COLS}) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (workspace_id, owner_email, name, purpose, business_owner, department,
                 wcag_standard, retention_policy,
                 _json.dumps(permitted_file_types) if permitted_file_types is not None else None,
                 due_date, project, processing_region, external_ai_policy, "active", now, now))

    def list_content_workspaces(self, owner_email: str) -> list[dict]:
        """Owner-scoped, same tenant boundary as every other per-user list in this app — never
        a global listing (see ADR 0044: owner_email is the tenant, no admin-sees-all carve-out
        decided yet)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspaces WHERE owner_email=%s ORDER BY created_at DESC",
                (owner_email,))
            return self._db.fetchall(cur)

    def get_content_workspace(self, workspace_id: str, *, owner_email: str) -> dict | None:
        """`owner_email` required and checked in the SAME query, not after — a foreign
        workspace id must come back exactly like a nonexistent one (see
        tests/test_foreign_scan_404.py's identical contract for scans: an id is never an
        existence oracle across owners)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspaces WHERE id=%s AND owner_email=%s",
                (workspace_id, owner_email))
            return self._db.fetchone(cur)

    # ── ACP Managed Content Workspace: documents & versions (ADR 0044) ──────────
    # No ownership check against content_workspaces here — same convention as
    # create_campaign/create_campaign_batch (which don't re-verify the scan they attach to
    # either): the CALLER (the future upload route, item 19) is responsible for having already
    # resolved and owner-checked the workspace via get_content_workspace before reaching here.

    def create_content_workspace_document(self, document_id: str, *, workspace_id: str,
                                          owner_email: str, display_name: str | None = None,
                                          relative_path: str | None = None,
                                          status: str = "uploading") -> None:
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO content_workspace_documents"
                "(id,workspace_id,owner_email,display_name,relative_path,status,created_at,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (document_id, workspace_id, owner_email, display_name, relative_path, status, now, now))

    def list_content_workspace_documents(self, workspace_id: str, *, owner_email: str) -> list[dict]:
        """Owner-scoped like every other list here — a workspace_id belonging to a different
        owner returns [] (indistinguishable from an empty workspace), never another owner's
        documents."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspace_documents "
                "WHERE workspace_id=%s AND owner_email=%s ORDER BY created_at DESC",
                (workspace_id, owner_email))
            return self._db.fetchall(cur)

    def get_content_workspace_document(self, document_id: str, *, owner_email: str) -> dict | None:
        """Same 404-not-403 contract as get_content_workspace: owner_email checked in the SAME
        query, never after."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspace_documents WHERE id=%s AND owner_email=%s",
                (document_id, owner_email))
            return self._db.fetchone(cur)

    def update_content_workspace_document_status(self, document_id: str, status: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE content_workspace_documents SET status=%s, updated_at=%s WHERE id=%s",
                (status, self._now(), document_id))

    def update_content_workspace_document_display_name(self, document_id: str, display_name: str) -> None:
        """Called when a NEW VERSION is uploaded under a different filename than the document's
        current one (e.g. 'report.pdf' replaced by 'report_v2.docx'). complete_upload derives
        the extension it uses for magic-byte verification, and the new version's own
        original_filename, from this column — so it must reflect the most recently attempted
        upload's name, not whatever the document was originally created with, or a version's
        real extension and its verified-against signature would silently disagree."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE content_workspace_documents SET display_name=%s, updated_at=%s WHERE id=%s",
                (display_name, self._now(), document_id))

    def next_content_workspace_document_version_seq(self, document_id: str) -> int:
        """1-based (PRD §12): the first version of a document is version_seq=1, not 0."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT MAX(version_seq) AS m FROM content_workspace_document_versions "
                "WHERE document_id=%s", (document_id,))
            row = self._db.fetchone(cur)
        return (row["m"] or 0) + 1 if row else 1

    def create_content_workspace_document_version(
            self, version_id: str, *, document_id: str, version_seq: int, content_hash: str,
            mime_type: str | None = None, size_bytes: int | None = None,
            blob_path: str | None = None, original_filename: str | None = None,
            uploaded_by: str | None = None, malware_status: str | None = None,
            lifecycle_state: str | None = "ready", assessment_status: str | None = None,
            source_version_id: str | None = None, remediated_from_version_id: str | None = None,
            release_status: str | None = None, retention_date: str | None = None) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO content_workspace_document_versions"
                "(id,document_id,version_seq,content_hash,mime_type,size_bytes,blob_path,"
                "original_filename,uploaded_at,uploaded_by,malware_status,lifecycle_state,"
                "assessment_status,source_version_id,remediated_from_version_id,release_status,"
                "retention_date) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (version_id, document_id, version_seq, content_hash, mime_type, size_bytes,
                 blob_path, original_filename, self._now(), uploaded_by, malware_status,
                 lifecycle_state, assessment_status, source_version_id,
                 remediated_from_version_id, release_status, retention_date))

    def create_pending_content_workspace_document_version(
            self, version_id: str, *, document_id: str, version_seq: int,
            original_filename: str | None = None, uploaded_by: str | None = None) -> None:
        """Reserves the version row at upload-SESSION time, not completion — keyed by the
        version_id workspace_blob already minted for the SAS. Fixes two things at once:

        (1) `original_filename` here is immutable per-session data. Before this, complete_upload
        derived the extension to verify (and the eventual original_filename) from
        content_workspace_documents.display_name, which create_new_version_upload_session
        mutated at SESSION-creation time — a second session for the same document (retry,
        double-click) could race and flip which extension gets checked against which upload
        before either one completed. A pending row keyed by its own version_id has no such
        shared mutable state to race on.

        (2) it gives complete_upload a real row to test for retry-idempotency
        (lifecycle_state='pending' vs already resolved) instead of trusting a client-supplied
        version_id blindly — see complete_content_workspace_document_version.

        content_hash is NOT NULL on this table, so a placeholder empty string stands in until
        completion supplies the real, server-verified one; it can never collide with a real
        client-supplied hash in find_content_workspace_document_version_by_hash, which is only
        ever queried against a non-empty string. mime_type/size_bytes/blob_path/malware_status
        all describe bytes that have not landed yet and stay NULL until then."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO content_workspace_document_versions"
                "(id,document_id,version_seq,content_hash,original_filename,uploaded_at,"
                "uploaded_by,lifecycle_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (version_id, document_id, version_seq, "", original_filename, self._now(),
                 uploaded_by, "pending"))

    def complete_content_workspace_document_version(
            self, version_id: str, *, document_id: str, content_hash: str,
            mime_type: str | None, size_bytes: int, blob_path: str,
            uploaded_by: str | None, lifecycle_state: str, malware_status: str) -> bool:
        """Resolves a PENDING version row (create_pending_content_workspace_document_version)
        to its final state. Fenced on lifecycle_state='pending' in the WHERE clause — the same
        "was this actually the row I expected to update" guard as every other completion-path
        write in this codebase (e.g. resolve_duplicate) — so a retried completion request
        (network blip, duplicate submit) that arrives after the row already resolved is a safe
        no-op here: returns False, and the CALLER decides what a False means (the route treats
        it as "someone else's request already completed this — reconcile, don't error").

        uploaded_by uses COALESCE rather than overwriting: the pending row's own uploader
        (stamped at session-creation time) is who actually authenticated for the SAS, and
        should win even if this call somehow carried a different value."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE content_workspace_document_versions SET content_hash=%s, mime_type=%s, "
                "size_bytes=%s, blob_path=%s, uploaded_by=COALESCE(uploaded_by,%s), "
                "lifecycle_state=%s, malware_status=%s "
                "WHERE id=%s AND document_id=%s AND lifecycle_state='pending'",
                (content_hash, mime_type, size_bytes, blob_path, uploaded_by, lifecycle_state,
                 malware_status, version_id, document_id))
            return (getattr(cur, "rowcount", 0) or 0) > 0

    def list_content_workspace_document_versions(self, document_id: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspace_document_versions "
                "WHERE document_id=%s ORDER BY version_seq DESC", (document_id,))
            return self._db.fetchall(cur)

    def get_latest_content_workspace_document_version(self, document_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspace_document_versions WHERE document_id=%s "
                "ORDER BY version_seq DESC LIMIT 1", (document_id,))
            return self._db.fetchone(cur)

    def get_content_workspace_document_version(self, version_id: str, *,
                                               document_id: str) -> dict | None:
        """Scoped to `document_id` (not just the version's own primary key) so a version_id
        that's real but belongs to a DIFFERENT document — including another owner's, since the
        route checks document ownership separately — is treated as not found, the same
        "an id is never an existence oracle across owners" contract every other lookup here
        follows."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM content_workspace_document_versions WHERE id=%s AND document_id=%s",
                (version_id, document_id))
            return self._db.fetchone(cur)

    def get_content_workspace_version_scan(self, version_id: str) -> dict | None:
        """The most recent scan_runs row assessing this version (ADR 0044) — a document can be
        re-assessed (e.g. after a Discover/Assess rule set change), so this is 'the current
        answer', not 'the only one'. Returns the full scan_runs row (status, files_done/files,
        rubric_name, started_at, finalized_at, ...) so the caller can render it the same way
        every other scan-status read in this app already does, rather than a bespoke shape."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM scan_runs WHERE content_workspace_version_id=%s "
                "ORDER BY started_at DESC LIMIT 1", (version_id,))
            return self._db.fetchone(cur)

    def update_content_workspace_document_version_lifecycle_state(
            self, version_id: str, lifecycle_state: str) -> None:
        """PRD §12's 'keep as new' duplicate resolution: flip an already-created version row's
        state (e.g. duplicate -> ready) in place, rather than re-inserting a row that already
        exists under this same id."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE content_workspace_document_versions SET lifecycle_state=%s WHERE id=%s",
                (lifecycle_state, version_id))

    def find_content_workspace_document_version_by_hash(
            self, workspace_id: str, content_hash: str, *, owner_email: str) -> dict | None:
        """PRD §12 duplicate detection: is this exact content already uploaded ANYWHERE in this
        workspace? Joined through content_workspace_documents for workspace scoping (the
        version row itself carries no workspace_id — see this table's own migration comment)
        and owner-checked the same way, so a hash match in another owner's workspace of the
        same id can never leak. Returns the newest match's version row, or None."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT v.* FROM content_workspace_document_versions v "
                "JOIN content_workspace_documents d ON d.id = v.document_id "
                "WHERE d.workspace_id=%s AND d.owner_email=%s AND v.content_hash=%s "
                "ORDER BY v.uploaded_at DESC LIMIT 1",
                (workspace_id, owner_email, content_hash))
            return self._db.fetchone(cur)

    def delete_content_workspace_document(self, document_id: str, *, owner_email: str) -> bool:
        """PRD §12 duplicate resolution ('reuse existing' / 'cancel'): remove a document and all
        its versions. Owner-scoped the same way every other content_workspace_* write is —
        the WHERE clause is on the document row itself, so a foreign document_id deletes
        nothing (versions are removed via the document's own id, never independently owner-
        checked, matching reset_user_data's identical join pattern). Returns whether a document
        was actually found and removed, so the caller can 404 rather than silently no-op."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM content_workspace_document_versions WHERE document_id IN "
                "(SELECT id FROM content_workspace_documents WHERE id=%s AND owner_email=%s)",
                (document_id, owner_email))
            self._db.execute(cur,
                "DELETE FROM content_workspace_documents WHERE id=%s AND owner_email=%s",
                (document_id, owner_email))
            return (getattr(cur, "rowcount", 0) or 0) > 0

    def list_expired_content_workspace_document_versions(self, *, as_of: str | None = None) -> list[dict]:
        """PRD §28 retention: every version whose `retention_date` (an ISO-8601 string, the
        same format self._now() produces — set by whatever future work computes it from a
        workspace's retention_policy; nothing does yet, so this is a baseline that activates
        once something populates the column) is in the past and not already marked "expired".
        System-wide, not owner-scoped — this is a maintenance sweep, not a user-facing route
        (compare sweeper.py's job-queue checks, which are the same shape). Joined with
        content_workspace_documents for owner_email/workspace_id, since the version row alone
        doesn't carry either and the caller (the retention sweep) needs both to delete the
        matching blob."""
        as_of = as_of or self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT v.*, d.workspace_id, d.owner_email FROM content_workspace_document_versions v "
                "JOIN content_workspace_documents d ON d.id = v.document_id "
                "WHERE v.retention_date IS NOT NULL AND v.retention_date <= %s "
                "AND (v.lifecycle_state IS NULL OR v.lifecycle_state != 'expired')",
                (as_of,))
            return self._db.fetchall(cur)

    def get_content_workspace_storage_bytes(self, workspace_id: str, *, owner_email: str) -> int:
        """PRD §9's "quota" half of "ACP validates user, workspace, type, size, and quota" —
        current bytes actually occupying blob storage for this workspace, so the upload-session
        route can check a new file against a quota before issuing an authorization for it.
        Excludes "expired" versions (their blob is already deleted by the retention sweep, so
        they no longer occupy space) but counts everything else — quarantined and duplicate
        versions still have a real blob sitting in storage, occupying real space, whatever their
        Discovery-eligibility. A resolved duplicate/cancelled document's versions are gone
        entirely (delete_content_workspace_document removes the rows), so there's no separate
        state to exclude for those."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COALESCE(SUM(v.size_bytes), 0) AS total FROM content_workspace_document_versions v "
                "JOIN content_workspace_documents d ON d.id = v.document_id "
                "WHERE d.workspace_id=%s AND d.owner_email=%s "
                "AND (v.lifecycle_state IS NULL OR v.lifecycle_state != 'expired')",
                (workspace_id, owner_email))
            row = self._db.fetchone(cur)
            return int(row["total"]) if row and row["total"] is not None else 0

    def list_scan_severities(self, scan_id: str) -> list[dict]:
        """{file, severity} for every finding in a scan -- the input compute_batches
        (api/campaigns.py) buckets by, kept as its own narrow query like
        list_file_identities (Phase 2) rather than widening get_scan's SELECT."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT file, severity FROM issue_records WHERE scan_id=%s", (scan_id,))
            return self._db.fetchall(cur)

    # ── Accessibility Conformance Report workspace (ADR 0047) ───────────────────
    # Every read is owner-scoped IN THE QUERY, not filtered afterwards — a foreign report id must
    # come back exactly like a nonexistent one, the contract tests/test_foreign_scan_404.py already
    # fixes for scans (an id is never an existence oracle across owners).

    # The metadata fields a caller may set. `status`, `catalog_hash`, `revision`, `published_at`
    # and the ids are NOT here on purpose: they are lifecycle facts this layer owns, and letting a
    # PATCH body carry them is how a draft acquires a published_at.
    _ACR_REPORT_EDITABLE = (
        "report_title", "product_name", "product_version", "build_id", "release_date",
        "vendor_name", "vendor_contact", "product_description", "evaluation_scope",
        "excluded_functionality", "deployment_environment", "vpat_edition", "wcag_version",
        "wcag_levels", "evaluation_methods", "browsers_tested", "operating_systems_tested",
        "assistive_technologies_tested", "automated_tools", "testing_period_start",
        "testing_period_end", "evaluators", "general_notes", "known_dependencies",
        "evidence_validity_days")

    def create_acr_report(self, report_id: str, *, owner_email: str, catalog_hash: str,
                          criteria: list[dict], metadata: dict | None = None,
                          supersedes_id: str | None = None, revision: int = 1) -> None:
        """Create a draft report AND its full criteria matrix in one transaction.

        Both together, deliberately: a report row without its matrix is a report that looks
        complete and silently has nothing to evaluate, and PRD §21.2 ("the system creates the
        complete applicable criteria matrix") is not satisfied by a row that will get its criteria
        on some later request.
        """
        meta = dict(metadata or {})
        now = self._now()
        # Built as (column, value) PAIRS rather than two positional lists. The first draft of this
        # zipped _ACR_REPORT_COLS against _ACR_REPORT_EDITABLE and silently shifted every field
        # after `evaluators` by one, because `approver` sits between `evaluators` and
        # `general_notes` in the column list and is not caller-editable. A positional INSERT over
        # 35 columns has no way to report that; every value simply lands one column to the left.
        cols: list[tuple[str, object]] = [
            ("id", report_id), ("owner_email", owner_email), ("status", "draft"),
            ("catalog_hash", catalog_hash), ("supersedes_id", supersedes_id),
            ("revision", revision),
        ]
        cols += [(f, meta.get(f)) for f in self._ACR_REPORT_EDITABLE]
        # approver is stamped at sign-off, never at creation (PRD §4.2).
        cols += [("approver", None), ("created_at", now), ("updated_at", now),
                 ("published_at", None)]
        names = ",".join(c for c, _ in cols)
        placeholders = ",".join(["%s"] * len(cols))
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"INSERT INTO acr_report({names}) VALUES({placeholders})",
                tuple(v for _, v in cols))
            for row in criteria:
                self._db.execute(cur,
                    "INSERT INTO acr_criterion(report_id,criterion_num,owner_email,criterion_name,"
                    "level,principle,guideline,applicable,workflow_state,draft_status,final_status,"
                    "remarks,evaluator,reviewer,approval_state,decided_at,approved_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (report_id, row["criterion_num"], owner_email, row.get("criterion_name"),
                     row.get("level"), row.get("principle"), row.get("guideline"),
                     1 if row.get("applicable", True) else 0,
                     row.get("workflow_state", "not_evaluated"), None, None, None, None, None,
                     "unapproved", None, None, now))

    def list_acr_reports(self, owner_email: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM acr_report WHERE owner_email=%s ORDER BY created_at DESC",
                (owner_email,))
            return self._db.fetchall(cur)

    def get_acr_report(self, report_id: str, *, owner_email: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM acr_report WHERE id=%s AND owner_email=%s",
                             (report_id, owner_email))
            return self._db.fetchone(cur)

    def update_acr_report_metadata(self, report_id: str, *, owner_email: str, fields: dict) -> int:
        """Patch report metadata. Refuses once published (PRD §17: snapshots are immutable).

        Returns the number of fields written. Unknown keys are IGNORED rather than erroring — the
        allow-list is the point, and a 400 on an extra key would make the endpoint brittle to
        harmless client drift while adding no safety.
        """
        writable = {k: v for k, v in fields.items() if k in self._ACR_REPORT_EDITABLE}
        if not writable:
            return 0
        sets = ",".join(f"{k}=%s" for k in writable)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"UPDATE acr_report SET {sets},updated_at=%s "
                "WHERE id=%s AND owner_email=%s AND status='draft'",
                (*writable.values(), self._now(), report_id, owner_email))
        return len(writable)

    def list_acr_criteria(self, report_id: str, *, owner_email: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM acr_criterion WHERE report_id=%s AND owner_email=%s "
                "ORDER BY criterion_num",
                (report_id, owner_email))
            return self._db.fetchall(cur)

    def get_acr_criterion(self, report_id: str, criterion_num: str, *, owner_email: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM acr_criterion WHERE report_id=%s AND criterion_num=%s "
                "AND owner_email=%s",
                (report_id, criterion_num, owner_email))
            return self._db.fetchone(cur)

    def save_acr_decision(self, report_id: str, criterion_num: str, *, owner_email: str,
                          final_status: str, remarks: str | None, decided_by: str) -> None:
        """Record a human's final conformance decision.

        The four-value constraint is enforced HERE as well as in acr_model, and that duplication is
        deliberate. This column's values are printed verbatim into a customer's conformance table;
        a workflow state that reached it by any route at all — a future caller that skips the
        dataclass, a migration, a fixture — would be exported as if it were a VPAT conformance
        level. It is the one field in this schema where a wrong value is a false compliance claim,
        so it is checked at every layer that can write it.
        """
        from acr_catalog import FINAL_STATUSES, REMARKS_REQUIRED
        if final_status not in FINAL_STATUSES:
            raise ValueError(
                f"{final_status!r} is not a VPAT conformance level {sorted(FINAL_STATUSES)}")
        if final_status in REMARKS_REQUIRED and not (remarks or "").strip():
            raise ValueError(f"{final_status!r} requires remarks (PRD §10)")
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE acr_criterion SET final_status=%s,remarks=%s,evaluator=%s,"
                "workflow_state='decided',decided_at=%s,updated_at=%s "
                "WHERE report_id=%s AND criterion_num=%s AND owner_email=%s",
                (final_status, remarks, decided_by, self._now(), self._now(),
                 report_id, criterion_num, owner_email))

    def save_acr_draft_status(self, report_id: str, criterion_num: str, *, owner_email: str,
                              draft_status: str | None, workflow_state: str) -> None:
        """ACP's own suggestion. Never touches final_status — PRD §20 forbids the model selecting
        or approving a conformance status, and the only structural guarantee of that is that the
        code path which writes suggestions cannot write decisions."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE acr_criterion SET draft_status=%s,workflow_state=%s,updated_at=%s "
                "WHERE report_id=%s AND criterion_num=%s AND owner_email=%s",
                (draft_status, workflow_state, self._now(), report_id, criterion_num, owner_email))

    def set_acr_criterion_applicability(self, report_id: str, criterion_num: str, *,
                                        owner_email: str, applicable: bool) -> None:
        """The workspace's own triage flag (PRD §9's applicability column).

        Deliberately CANNOT write final_status. Deciding "Not Applicable" is a conformance
        judgement that a customer reads and that PRD §10 requires remarks for; this is only
        "we do not expect to evaluate this". Keeping them in separate code paths is what stops
        a triage click from becoming an exported conformance claim.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE acr_criterion SET applicable=%s,updated_at=%s "
                "WHERE report_id=%s AND criterion_num=%s AND owner_email=%s",
                (1 if applicable else 0, self._now(), report_id, criterion_num, owner_email))

    def approve_acr_criterion(self, report_id: str, criterion_num: str, *, owner_email: str,
                              reviewer: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE acr_criterion SET approval_state='approved',reviewer=%s,approved_at=%s,"
                "updated_at=%s WHERE report_id=%s AND criterion_num=%s AND owner_email=%s "
                "AND final_status IS NOT NULL",
                (reviewer, self._now(), self._now(), report_id, criterion_num, owner_email))

    def add_acr_evidence(self, row: dict, *, owner_email: str) -> None:
        """Append one evidence record. Append-only: there is no update_acr_evidence, by design."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO acr_evidence(id,report_id,criterion_num,owner_email,source_kind,"
                "result,tester,tested_at,product_version,build_id,environment,workflow,browser,"
                "assistive_tech,tool_name,tool_version,rule_id,tested_url,coverage,method,notes,"
                "attachments,related_finding_ids,stale_reason,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (row["id"], row["report_id"], row["criterion_num"], owner_email,
                 row["source_kind"], row["result"], row.get("tester"), row.get("tested_at"),
                 row.get("product_version"), row.get("build_id"), row.get("environment"),
                 row.get("workflow"), row.get("browser"), row.get("assistive_tech"),
                 row.get("tool_name"), row.get("tool_version"), row.get("rule_id"),
                 row.get("tested_url"), row.get("coverage"), row.get("method"), row.get("notes"),
                 _json.dumps(row.get("attachments") or []),
                 _json.dumps(row.get("related_finding_ids") or []),
                 None, row.get("created_at") or self._now()))

    def list_acr_evidence(self, report_id: str, *, owner_email: str,
                          criterion_num: str | None = None) -> list[dict]:
        sql = "SELECT * FROM acr_evidence WHERE report_id=%s AND owner_email=%s"
        params: tuple = (report_id, owner_email)
        if criterion_num:
            sql += " AND criterion_num=%s"
            params += (criterion_num,)
        with self._db.cursor() as cur:
            self._db.execute(cur, sql + " ORDER BY tested_at, id", params)
            return self._db.fetchall(cur)

    # ── Guided manual test runs (PRD §14, Phase 3) ────────────────────────────────────────────
    #
    # A "run" is one tester working one plan against one criterion. `acr_manual_test` holds the
    # run; `acr_manual_step` holds one row per step outcome. Neither table stores the run's
    # environment: a completed run produces an acr_evidence row, and THAT carries the browser,
    # assistive technology and environment (PRD §4.5). Keeping one home for that metadata is what
    # stops a run looking reproducible while the durable record has nothing in it.

    def start_acr_manual_run(self, report_id: str, criterion_num: str, *, owner_email: str,
                             plan_id: str, tester: str | None = None) -> str:
        """Begin a run. Returns its id. Starting twice is allowed — a plan can be re-run against a
        new product version, and acr_freshness decides which runs still count."""
        run_id = f"acrmt_{uuid.uuid4().hex[:12]}"
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO acr_manual_test(id,report_id,criterion_num,owner_email,plan_id,"
                "result,evidence_id,tester,notes,created_at,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, report_id, criterion_num, owner_email, plan_id,
                 None, None, tester, None, self._now(), self._now()))
        return run_id

    def list_acr_manual_runs(self, report_id: str, *, owner_email: str,
                             criterion_num: str | None = None) -> list[dict]:
        sql = "SELECT * FROM acr_manual_test WHERE report_id=%s AND owner_email=%s"
        params: tuple = (report_id, owner_email)
        if criterion_num:
            sql += " AND criterion_num=%s"
            params += (criterion_num,)
        with self._db.cursor() as cur:
            self._db.execute(cur, sql + " ORDER BY created_at, id", params)
            return self._db.fetchall(cur)

    def record_acr_manual_step(self, run_id: str, *, report_id: str, owner_email: str,
                               step_index: int, outcome: str, notes: str | None = None) -> None:
        """Record what the tester observed at one step. Re-recording a step REPLACES it.

        Deliberately not append-only, unlike acr_evidence. A tester correcting a mis-click during
        a run is fixing a typo, not retracting a finding — the finding is the evidence row the
        completed run produces, and that stays append-only.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM acr_manual_step WHERE run_id=%s AND step_index=%s AND owner_email=%s",
                (run_id, step_index, owner_email))
            self._db.execute(cur,
                "INSERT INTO acr_manual_step(id,run_id,report_id,owner_email,step_index,outcome,"
                "notes,recorded_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"acrms_{uuid.uuid4().hex[:12]}", run_id, report_id, owner_email,
                 int(step_index), outcome, notes, self._now()))
            self._db.execute(cur,
                "UPDATE acr_manual_test SET updated_at=%s WHERE id=%s AND owner_email=%s",
                (self._now(), run_id, owner_email))

    def list_acr_manual_steps(self, report_id: str, *, owner_email: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM acr_manual_step WHERE report_id=%s AND owner_email=%s "
                "ORDER BY run_id, step_index", (report_id, owner_email))
            return self._db.fetchall(cur)

    def complete_acr_manual_run(self, run_id: str, *, report_id: str, owner_email: str,
                                result: str, evidence_id: str, tester: str,
                                notes: str | None = None) -> None:
        """Close a run by linking the evidence row it produced.

        `result` is what the tester OBSERVED across the plan, not a conformance status — this
        method cannot reach acr_criterion.final_status, and there is no code path from here to it.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE acr_manual_test SET result=%s,evidence_id=%s,tester=%s,notes=%s,"
                "updated_at=%s WHERE id=%s AND report_id=%s AND owner_email=%s",
                (result, evidence_id, tester, notes, self._now(), run_id, report_id, owner_email))

    def append_acr_decision_log(self, report_id: str, *, owner_email: str, actor: str | None,
                                action: str, criterion_num: str | None = None,
                                detail: str | None = None) -> None:
        """Append-only audit (PRD §17). Never updated, never deleted."""
        import uuid as _uuid
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO acr_decision_log(id,ts,report_id,owner_email,actor,action,"
                "criterion_num,detail) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (_uuid.uuid4().hex, self._now(), report_id, owner_email, actor, action,
                 criterion_num, detail))

    def list_acr_decision_log(self, report_id: str, *, owner_email: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM acr_decision_log WHERE report_id=%s AND owner_email=%s "
                "ORDER BY ts, id",
                (report_id, owner_email))
            return self._db.fetchall(cur)

    def create_acr_snapshot(self, snapshot_id: str, *, report_id: str, owner_email: str,
                            revision: int, catalog_hash: str, content_json: str,
                            content_digest: str, published_by: str,
                            docx_blob_path: str | None = None) -> str:
        """Write the immutable published snapshot and flip the report to published.

        One transaction: a report marked published whose snapshot write failed would be a report
        claiming an artifact that does not exist.
        """
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO acr_snapshot(id,report_id,owner_email,revision,catalog_hash,"
                "content_json,content_digest,docx_blob_path,published_at,published_by) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (snapshot_id, report_id, owner_email, revision, catalog_hash, content_json,
                 content_digest, docx_blob_path, now, published_by))
            self._db.execute(cur,
                "UPDATE acr_report SET status='published',published_at=%s,approver=%s,updated_at=%s "
                "WHERE id=%s AND owner_email=%s",
                (now, published_by, now, report_id, owner_email))
        return now

    def get_acr_snapshot(self, report_id: str, *, owner_email: str,
                         revision: int | None = None) -> dict | None:
        sql = "SELECT * FROM acr_snapshot WHERE report_id=%s AND owner_email=%s"
        params: tuple = (report_id, owner_email)
        if revision is not None:
            sql += " AND revision=%s"
            params += (revision,)
        with self._db.cursor() as cur:
            self._db.execute(cur, sql + " ORDER BY revision DESC", params)
            return self._db.fetchone(cur)

    def carry_acr_decisions(self, report_id: str, rows: list[dict], *, owner_email: str) -> int:
        """Write decisions carried from a superseded revision into a NEW report's matrix.

        A SEPARATE method rather than a parameter on create_acr_report, because that method
        deliberately hardcodes `final_status=None` and `approval_state='unapproved'` and ignores
        whatever the caller put on the incoming rows. That is a safety property worth keeping: a
        newly created report always starts with a blank matrix, so no code path can accidentally
        create one that arrives pre-decided.

        CARRYING AN APPROVAL IS NOT POSSIBLE HERE, and that is the point. This method writes
        `final_status`, `remarks`, `evaluator` and `workflow_state`; it has no path to
        `approval_state`, `reviewer` or `approved_at`, which stay at their creation defaults. PRD
        §4.2 requires an approver to sign off every applicable criterion of THIS report, and an
        approval granted against the previous revision was granted for a different product
        version — carrying it forward would be a recorded sign-off that never happened.

        Returns the number of criteria written, so the caller can report what was carried.
        """
        written = 0
        now = self._now()
        with self._db.cursor() as cur:
            for row in rows:
                if not row.get("final_status"):
                    continue
                self._db.execute(cur,
                    "UPDATE acr_criterion SET final_status=%s,remarks=%s,evaluator=%s,"
                    "workflow_state=%s,decided_at=%s,updated_at=%s "
                    "WHERE report_id=%s AND criterion_num=%s AND owner_email=%s",
                    (row["final_status"], row.get("remarks"), row.get("evaluator"),
                     row.get("workflow_state") or "decided", row.get("decided_at") or now, now,
                     report_id, row["criterion_num"], owner_email))
                written += 1
        return written

    def list_acr_snapshots(self, report_id: str, *, owner_email: str) -> list[dict]:
        """Every published revision of this report, newest first.

        There is deliberately no update_acr_snapshot and no delete_acr_snapshot. A published ACR is
        in a customer's procurement file; the only honest way to change it is to publish a new
        revision that supersedes it, which is what create_acr_report's supersedes_id is for.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM acr_snapshot WHERE report_id=%s AND owner_email=%s "
                "ORDER BY revision DESC", (report_id, owner_email))
            return self._db.fetchall(cur)

    def list_acr_snapshots_for_lineage(self, report_ids: list[str], *,
                                       owner_email: str) -> list[dict]:
        """Snapshots across a whole supersedes chain, newest first.

        A revision is a NEW acr_report row, so "the history of this report" spans several ids. The
        caller walks the chain and passes every id in it; doing the walk here would put lineage
        logic in the store, where the route already has to know it to render the chain.
        """
        if not report_ids:
            return []
        placeholders = ",".join(["%s"] * len(report_ids))
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT * FROM acr_snapshot WHERE owner_email=%s AND report_id IN ({placeholders}) "
                "ORDER BY revision DESC", (owner_email, *report_ids))
            return self._db.fetchall(cur)

    def grant_acr_role(self, *, owner_email: str, email: str, role: str,
                       report_id: str = "*", granted_by: str | None = None) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM acr_role WHERE owner_email=%s AND report_id=%s AND email=%s "
                "AND role=%s",
                (owner_email, report_id, email.lower(), role))
            self._db.execute(cur,
                "INSERT INTO acr_role(owner_email,report_id,email,role,granted_by,granted_at) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (owner_email, report_id, email.lower(), role, granted_by, self._now()))

    def revoke_acr_role(self, *, owner_email: str, email: str, role: str,
                        report_id: str = "*") -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM acr_role WHERE owner_email=%s AND report_id=%s AND email=%s "
                "AND role=%s",
                (owner_email, report_id, email.lower(), role))

    def copy_acr_role_grants(self, *, owner_email: str, from_report_id: str,
                             to_report_id: str) -> int:
        """Carry a report's role grants into its new revision.

        A ROLE IS NOT AN APPROVAL, and the difference is the whole reason one carries and the
        other must not. A role says "this person is authorized to approve on this report"; an
        approval says "this person did approve this criterion, for this product version". Carrying
        the first is continuity — a revision is the same report, and without it every revision
        would need an admin to re-grant every role before anyone could work. Carrying the second
        would be a recorded sign-off that never happened, which is why carry_acr_decisions has no
        path to approval_state.

        Deployment-wide ('*') grants are not copied: they already apply to every report, and
        duplicating them as report-scoped rows would make a later revoke miss one.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT email,role,granted_by FROM acr_role "
                "WHERE owner_email=%s AND report_id=%s", (owner_email, from_report_id))
            rows = self._db.fetchall(cur)
            now = self._now()
            for row in rows:
                self._db.execute(cur,
                    "INSERT INTO acr_role(owner_email,report_id,email,role,granted_by,granted_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (owner_email, to_report_id, row["email"], row["role"],
                     row.get("granted_by"), now))
        return len(rows)

    def list_acr_role_holders(self, *, owner_email: str, report_id: str,
                              roles: tuple[str, ...]) -> list[str]:
        """Everyone holding one of these roles on this report, or deployment-wide.

        Needed by PRD §18's separation-of-duties advisory, which is CONDITIONED on a second
        qualified reviewer existing — the warning is silent when the approver is the only one
        available, because nagging a one-person team on every publish teaches them to ignore it.
        So this has to count real role holders rather than assume.

        `report_id='*'` rows are deployment-wide grants and count for every report, matching how
        get_acr_roles resolves them.
        """
        if not roles:
            return []
        placeholders = ",".join(["%s"] * len(roles))
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT DISTINCT email FROM acr_role WHERE owner_email=%s "
                f"AND report_id IN (%s,'*') AND role IN ({placeholders})",
                (owner_email, report_id, *roles))
            return [r["email"] for r in self._db.fetchall(cur)]

    def get_acr_roles(self, *, owner_email: str, email: str, report_id: str) -> list[str]:
        """Roles this email holds on this report — report-scoped grants plus account-wide ('*')."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT role FROM acr_role WHERE owner_email=%s AND email=%s "
                "AND report_id IN (%s, '*')",
                (owner_email, email.lower(), report_id))
            return sorted({r["role"] for r in self._db.fetchall(cur)})

    # ── workspace roles (PRD §12) ─────────────────────────────────────────────
    # The tenant identifier is the owner email, per this file's existing convention. It is passed
    # in rather than read from a module global so a test can hold two tenants at once — which is
    # what proves the isolation rather than assuming it.

    def list_workspace_roles(self, *, tenant_id: str) -> list[dict]:
        """Every role in the tenant, each carrying its permission rows.

        One query per table rather than a join: a join returns no row at all for a role with no
        permissions, and a Viewer whose every tab is Hidden is exactly that role. Losing it would
        make "this role grants nothing" indistinguishable from "this role does not exist" — the
        distinction api/workspace_rbac.py is built to preserve.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM workspace_roles WHERE tenant_id=%s ORDER BY name", (tenant_id,))
            roles = self._db.fetchall(cur)
            self._db.execute(cur,
                "SELECT role_id, capability, access_level FROM workspace_role_permissions "
                "WHERE tenant_id=%s", (tenant_id,))
            perms = self._db.fetchall(cur)
        by_role: dict[str, list[dict]] = {}
        for p in perms:
            by_role.setdefault(p["role_id"], []).append(p)
        return [{**r, "permissions": by_role.get(r["id"], [])} for r in roles]

    def get_workspace_role(self, *, tenant_id: str, role_id: str) -> dict | None:
        """One role with its permissions, or None when there is no such role.

        None means NOT FOUND. It never means "found, but empty" — see list_workspace_roles. A
        caller that cannot tell those apart will eventually treat a missing role as a role with no
        permissions, which reads as a successful deny and hides the real fault.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM workspace_roles WHERE tenant_id=%s AND id=%s", (tenant_id, role_id))
            rows = self._db.fetchall(cur)
            if not rows:
                return None
            self._db.execute(cur,
                "SELECT role_id, capability, access_level FROM workspace_role_permissions "
                "WHERE tenant_id=%s AND role_id=%s", (tenant_id, role_id))
            return {**rows[0], "permissions": self._db.fetchall(cur)}

    def upsert_workspace_role(self, *, tenant_id: str, role_id: str, name: str,
                              permissions: dict[str, str], description: str | None = None,
                              is_system: bool = False, is_protected: bool = False,
                              actor: str | None = None,
                              expected_version: int | None = None) -> dict:
        """Create or replace one role and its whole permission set.

        `expected_version` is PRD §14's concurrency check. Pass the version the caller read; a
        mismatch raises ValueError and NOTHING is written. Pass None only when creating, or when
        the caller genuinely intends a blind overwrite — a default of "no check" is how the check
        stops being applied at the one call site that forgot it.

        Permissions are REPLACED, not merged. A role edit that removed a tab must not leave the
        old row behind: merging would make revoking access the one operation the drawer cannot
        express.
        """
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT version FROM workspace_roles WHERE tenant_id=%s AND id=%s",
                (tenant_id, role_id))
            existing = self._db.fetchall(cur)
            current = existing[0]["version"] if existing else None
            if existing and expected_version is not None and int(current) != int(expected_version):
                raise ValueError(
                    f"role {role_id} is at version {current}, not {expected_version} — "
                    f"it was changed by someone else since you loaded it")
            version = (int(current) + 1) if existing else 1
            if existing:
                self._db.execute(cur,
                    "UPDATE workspace_roles SET name=%s, description=%s, is_system=%s, "
                    "is_protected=%s, updated_at=%s, version=%s WHERE tenant_id=%s AND id=%s",
                    (name, description, 1 if is_system else 0, 1 if is_protected else 0,
                     now, version, tenant_id, role_id))
            else:
                self._db.execute(cur,
                    "INSERT INTO workspace_roles(id,tenant_id,name,description,is_system,"
                    "is_protected,created_by,created_at,updated_at,version) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (role_id, tenant_id, name, description, 1 if is_system else 0,
                     1 if is_protected else 0, actor, now, now, version))
            self._db.execute(cur,
                "DELETE FROM workspace_role_permissions WHERE tenant_id=%s AND role_id=%s",
                (tenant_id, role_id))
            for capability, access_level in sorted((permissions or {}).items()):
                self._db.execute(cur,
                    "INSERT INTO workspace_role_permissions(tenant_id,role_id,capability,"
                    "access_level) VALUES(%s,%s,%s,%s)",
                    (tenant_id, role_id, capability, access_level))
        return self.get_workspace_role(tenant_id=tenant_id, role_id=role_id)

    def delete_workspace_role(self, *, tenant_id: str, role_id: str) -> None:
        """Remove a role and its permissions.

        Refusing to delete a role that still has users, and refusing to delete Owner, are ROUTE
        decisions (PRD §14) enforced there. The store deleting unconditionally is what lets a
        migration or a test tear down cleanly without going through the gate the UI does.
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "DELETE FROM workspace_role_permissions WHERE tenant_id=%s AND role_id=%s",
                (tenant_id, role_id))
            self._db.execute(cur,
                "DELETE FROM workspace_roles WHERE tenant_id=%s AND id=%s", (tenant_id, role_id))
