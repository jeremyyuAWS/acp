"""SQLite (local / test) + Postgres (deploy) persistence for scan results.

Set DATABASE_URL=postgresql://user:pass@host:5432/dbname to use Postgres.
Without it, falls back to a local SQLite file — convenient for local dev.

Postgres is the target for the live demo: it handles concurrent scans without
serializing writes and survives container restarts across all replicas.
"""
from __future__ import annotations
import contextlib
import json
import os
import re
import time
import sqlite3
import uuid
from pathlib import Path

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
    # What the job is doing RIGHT NOW, written by the handler as it works. The queue panel
    # used to render a hardcoded list of WCAG criteria cycled by a timer, which had nothing
    # to do with the running job. Nullable: a handler that reports nothing shows nothing.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS phase TEXT",
    # Column order matches the claim ORDER BY (priority, run_after) so Postgres reads the
    # top queued job index-only instead of sorting all queued rows every poll (audit P2).
    # New name + drop-old so this migrates once, not a rebuild every boot.
    "DROP INDEX IF EXISTS idx_jobs_claim",
    "CREATE INDEX IF NOT EXISTS idx_jobs_claim2 ON jobs(status, priority, run_after)",
    # Inspectable lease expiry: set at claim time to now + ACP_JOB_LEASE_S, refreshed by
    # touch_job heartbeat. reclaim_stuck_jobs uses this instead of the opaque locked_at
    # arithmetic so operators can see exactly when a lease will expire.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lease_expires_at TEXT",
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

    Sized from the concurrency that actually exists: every scan/remediate worker thread can
    hold a connection while it works, and every in-flight HTTP handler needs one on top of
    that. The old fixed 5, against ACP_WORKERS=4, meant a dashboard poll landing while the
    workers were busy raised `PoolError: connection pool exhausted` — /hitl/auto-queue 500'd
    and the reviewer saw an empty review queue while items were waiting to be queued.

    Still bounded well under Azure Postgres' max_connections (~50 on small SKUs); override
    with ACP_DB_MAX_CONN if the worker count or replica count grows.
    """
    e = os.environ if env is None else env
    explicit = e.get("ACP_DB_MAX_CONN")
    if explicit:
        return max(2, int(explicit))
    try:
        workers = int(e.get("ACP_WORKERS") or 4)
    except ValueError:
        workers = 4
    return max(2, workers) + _API_HEADROOM_CONN


# Concurrent HTTP handlers that may need a connection while every worker holds one.
# The dashboard alone polls /jobs, /hitl/queue and /scans/{id}/remediation-status together.
_API_HEADROOM_CONN = 8


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

    def init_schema(self) -> None:
        import psycopg2
        conn = psycopg2.connect(self._url, **self._ssl_kwargs)
        try:
            cur = conn.cursor()
            for stmt in _SCHEMA:
                cur.execute(stmt)
            for stmt in _PG_VIEWS:
                cur.execute(stmt)
            conn.commit()
        finally:
            conn.close()

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


# ── Store ────────────────────────────────────────────────────────────────────

class Store:
    def __init__(self) -> None:
        self._db: _SQLiteAdapter | _PgAdapter = (
            _PgAdapter(_DATABASE_URL) if _DATABASE_URL else _SQLiteAdapter(str(_SQLITE_PATH))
        )
        self._db.init_schema()
        self._scope_cache: dict = {}
        self._scope_rules_cache: dict = {}
        self._inventory_cache: dict = {}

    def _save_file_manifest(self, cur, sid: str, f: dict, catalog: dict) -> None:
        """Compute and persist the per-rule execution manifest for one file."""
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
        manifest_rows = []
        for rule in rules:
            rid = rule["id"]
            if rid in error_ids:
                status = "ERROR"
            elif rid in fail_ids:
                status = "FAIL"
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
            pass
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
                     priority: int = 100, max_attempts: int = 5,
                     run_after: str | None = None) -> tuple[str, str]:
        """Create a scan_runs stub and its initial job in a single atomic transaction.

        Returns (scan_id, job_id). All rows are committed together; a failure at any point
        rolls back everything, leaving no orphan stubs. If idempotency_key is provided and a
        scan with that key already exists for the same owner, returns the original
        (scan_id, job_id) without inserting new rows.

        `inputs` is the immutable input snapshot (Stage 1 item 3). When provided it is
        inserted into scan_inputs in the same transaction. SECURITY: inputs must not contain
        access tokens, credentials, or secrets — callers are responsible for omitting them.
        """
        import json as _json
        now = self._now()
        job_id = uuid.uuid4().hex[:16]
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
                "INSERT INTO scan_runs(id,source,status,owner_email,started_at,idempotency_key) "
                "VALUES(%s,%s,'queued',%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (scan_id, source, owner, now, idempotency_key))
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
                "  status=EXCLUDED.status, scope=EXCLUDED.scope",
                (scan_id, started_at, source, rubric_name, rubric_hash, total, status, owner,
                 _json.dumps(scope) if scope else None))

    def set_scan_status(self, scan_id: str, status: str) -> None:
        """Move a scan between phases — e.g. 'discovered' → 'running' when Assess begins."""
        with self._db.cursor() as cur:
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
        per-column comparison; "failed" counts items where the INSERT raised an exception."""
        if not items:
            return {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
        now = self._now()
        failed = 0
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COUNT(*) AS cnt FROM scan_inventory WHERE scan_id=%s", (scan_id,))
            before = (self._db.fetchone(cur) or {}).get("cnt", 0)
            for it in items:
                try:
                    self._db.execute(cur,
                        "INSERT INTO scan_inventory(scan_id,file,drive_file_id,mime,size_kb,doc_class,"
                        "checksum,path,created_at,source_modified,owner,parent_folder,discovered_at,drive_id,"
                        "content_type) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file) DO UPDATE SET "
                        "drive_file_id=EXCLUDED.drive_file_id, mime=EXCLUDED.mime, size_kb=EXCLUDED.size_kb, "
                        "doc_class=EXCLUDED.doc_class, checksum=EXCLUDED.checksum, path=EXCLUDED.path, "
                        "created_at=EXCLUDED.created_at, source_modified=EXCLUDED.source_modified, "
                        "owner=EXCLUDED.owner, parent_folder=EXCLUDED.parent_folder, drive_id=EXCLUDED.drive_id, "
                        # COALESCE, not overwrite: a re-list that got no content type this time (a
                        # transient enrichment failure) must not blank out one recorded on a PRIOR
                        # list of the same file — that would be a real answer thrown away for a gap.
                        "content_type=COALESCE(EXCLUDED.content_type, scan_inventory.content_type)",
                        (scan_id, it.get("file"), it.get("drive_file_id"), it.get("mime"),
                         it.get("size_kb"), it.get("doc_class"), it.get("checksum"), it.get("path"),
                         it.get("created_at"), it.get("source_modified"), it.get("owner"),
                         it.get("parent_folder"), it.get("discovered_at") or now, it.get("drive_id"),
                         it.get("content_type")))
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
        return (row or {}).get("n", 0) or 0

    def list_inventory_page(self, scan_id: str, *, limit: int, offset: int = 0) -> list[dict]:
        """One page of the per-file discover inventory, ORDER BY file (stable paging). The
        whole-estate list/export API runs off this + count_inventory so a 30k-file estate is paged
        from the DB, never pulled whole into memory."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT {self._INV_COLS} FROM scan_inventory WHERE scan_id=%s "
                "ORDER BY file LIMIT %s OFFSET %s", (scan_id, int(limit), int(offset)))
            return self._db.fetchall(cur)

    # ── Lifecycle status (Discover-completeness PRD §4.3 / §4.5) ─────────────────
    # The 7 statuses a discovered file can hold. Active is the default; a rule run or a manual
    # action moves it. Kept here (not an enum type) so the sqlite/postgres split needs no DDL.
    LIFECYCLE_STATUSES = ("Active", "Archive Candidate", "Archived", "Delete Candidate",
                          "Deleted", "Failed", "Exempted")
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

    def save_file_result(self, scan_id: str, f: dict, completed_at: str) -> None:
        """Persist one assessed file (same shape save_scan writes). Idempotent so a
        retried scan_file job doesn't double-insert."""
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
            self._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id,acp_stamped,checksum,size_kb,pages,sheets,source_modified) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file) DO UPDATE SET "
                "engine=EXCLUDED.engine,status=EXCLUDED.status,score=EXCLUDED.score,"
                "compliant=EXCLUDED.compliant,skipped_rules=EXCLUDED.skipped_rules,"
                "drive_file_id=EXCLUDED.drive_file_id,acp_stamped=EXCLUDED.acp_stamped,checksum=EXCLUDED.checksum,"
                "size_kb=EXCLUDED.size_kb,pages=EXCLUDED.pages,sheets=EXCLUDED.sheets,source_modified=EXCLUDED.source_modified",
                (scan_id, f["file"], f["engine"], f["status"], f["score"],
                 int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id"), f.get("acp_stamped"),
                 f.get("checksum"), f.get("size_kb"), f.get("pages"), f.get("sheets"), f.get("source_modified")))
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
        avg=mean of scored). 'files' becomes the count actually analysed."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET status='done', completed_at=%s, "
                "files=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s), "
                "certifiable=(SELECT COALESCE(SUM(compliant),0) FROM file_records WHERE scan_id=%s), "
                "uncertain=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s AND status='uncertain'), "
                "error=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s AND status='error'), "
                "avg_score=(SELECT ROUND(AVG(score)) FROM file_records WHERE scan_id=%s AND score IS NOT NULL) "
                "WHERE id=%s",
                (completed_at, scan_id, scan_id, scan_id, scan_id, scan_id, scan_id))
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
                         "org_memory", "remediation_state", "remediation_diff", "applied_fixes",
                         "ai_calls", "finding_comments",
                         "scan_inputs"]  # Stage 1 item 3: per-scan enqueue snapshots are customer data

    def reset_analytics(self) -> list[str]:
        """Clear all scan results / activity so the Grafana + in-app charts start
        fresh. Keeps settings + schedule. Returns the cleared table names."""
        with self._db.cursor() as cur:
            for t in self._ANALYTICS_TABLES:
                self._db.execute(cur, f"DELETE FROM {t}")
        return list(self._ANALYTICS_TABLES)

    # Tables in _ANALYTICS_TABLES that key on scan_id, scoped via a scan_runs.owner_email join.
    _RESET_USER_SCAN_TABLES = ["file_records", "issue_records", "scan_rule_traces",
                               "file_stage_timings", "scan_file_manifests", "scan_inventory",
                               "file_tags", "pii_findings", "hitl_queue", "hitl_events",
                               "remediation_diff", "applied_fixes", "ai_calls", "finding_comments",
                               "jobs"]
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
          - owns owner_email directly: scan_decisions, documents, scan_runs (WHERE owner_email=%s);
            org_memory (WHERE org=%s — every call site sets `org` to the signed-in user's own
            email, so it is already per-user despite the name).

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
            for t in self._RESET_USER_DOC_TABLES:
                self._db.execute(cur,
                    f"DELETE FROM {t} WHERE doc_id IN (SELECT doc_id FROM documents WHERE owner_email=%s)",
                    (owner_email,))
                cleared.append(t)
            self._db.execute(cur, "DELETE FROM scan_decisions WHERE owner_email=%s", (owner_email,))
            cleared.append("scan_decisions")
            self._db.execute(cur, "DELETE FROM documents WHERE owner_email=%s", (owner_email,))
            cleared.append("documents")
            self._db.execute(cur, "DELETE FROM org_memory WHERE org=%s", (owner_email,))
            cleared.append("org_memory")
            # scan_runs last — every scan_id-scoped subquery above depends on these rows existing.
            self._db.execute(cur, "DELETE FROM scan_runs WHERE owner_email=%s", (owner_email,))
            cleared.append("scan_runs")
        return {"owner": owner_email, "cleared_tables": cleared}

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
          - Blob storage bytes — call blob.purge_scan(owner, scan_id) separately (the route
            does this).  Kept separate so a DB-only operation never blocks on a slow storage
            call and the two failure modes surface independently.
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
        # Scoped to the signed-in user (per-user isolation): a user sees only their scans.
        where, params = "completed_at IS NOT NULL", ()
        if owner:
            where += " AND owner_email=%s"; params = (owner,)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score,assessed_at,scope "
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
                "avg_score,assessed_at,scope,owner_email "
                "FROM scan_runs WHERE completed_at IS NOT NULL ORDER BY completed_at DESC", ())
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
        """
        with self._db.cursor() as cur:
            where, params = "1=1", ()
            if owner:
                where = "owner_email=%s"; params = (owner,)
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score,assessed_at,scope "
                f"FROM scan_runs WHERE {where} "
                "ORDER BY COALESCE(completed_at, discovered_at, started_at) DESC", params)
            rows = self._db.fetchall(cur)
            return [self._fill_run_aggregate(cur, r) for r in rows]

    def mark_assessed(self, scan_id: str, when: str) -> None:
        """Stamp the scan as assessed (the user ran Assess). Results views gate on this."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE scan_runs SET assessed_at=%s WHERE id=%s AND assessed_at IS NULL",
                             (when, scan_id))

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

    def delete_decision(self, scan_id: str, file: str, kind: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM scan_decisions WHERE scan_id=%s AND file=%s AND kind=%s",
                             (scan_id, file, kind))

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
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND status IN ('queued','running')",
                (row["id"],))
            outstanding = (self._db.fetchone(cur) or {}).get("n", 0)
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

    def rescue_unfinalized_scans(self) -> int:
        """Deploy-safety net (found live 2026-07-11): a revision swap can kill the worker
        AFTER the last scan_file persisted its row but BEFORE the count trigger enqueued
        scan_finalize — the scan stays 'running' forever with nothing left to do. For any
        such scan (running, zero outstanding jobs, every enqueued file persisted), enqueue
        the finalize job. Safe by construction: scan_finalize is idempotent and
        mark_finalized claims exactly-once, so a duplicate enqueue no-ops. Called from the
        stuck-job sweeper each tick. Returns how many scans were rescued."""
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
        return len(rows)

    def cancel_scan(self, sid: str, owner: str | None = None) -> bool:
        """Stop an in-flight fan-out scan: kill its outstanding jobs and close the run as
        'cancelled'. Owner-scoped like get_scan. Files already analysed keep their records —
        history stays honest about what ran before the stop. False when the scan doesn't
        exist, belongs to someone else, or isn't running (nothing to cancel)."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT owner_email, status FROM scan_runs WHERE id=%s", (sid,))
            row = self._db.fetchone(cur)
            if not row or (owner is not None and row.get("owner_email") != owner):
                return False
            if row.get("status") != "running":
                return False
            self._db.execute(cur,
                "UPDATE jobs SET status='dead', updated_at=%s "
                "WHERE scan_id=%s AND status IN ('queued','running')", (self._now(), sid))
            self._db.execute(cur,
                "UPDATE scan_runs SET status='cancelled', completed_at=%s "
                "WHERE id=%s AND status='running'", (self._now(), sid))
            # A cancelled ASSESS fan-out has already assessed some documents (their file_records
            # exist); stamp assessed_at so the run's PARTIAL results are reachable — the results
            # views gate on assessed_at, and without this a stopped run showed nothing at all. Only
            # when something ran: a discover-only cancel has no file_records and stays unassessed,
            # which is correct — it is not a partial assessment. COALESCE so a run that had already
            # finalized keeps its original stamp rather than being back-dated to the cancel.
            self._stamp_assessed_if_ran(cur, sid)
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
        unset; only finalize_scan_run fills them. Two paths close a scan WITHOUT finalizing —
        cancel_scan ('cancelled') and the lost-worker sweeper ('interrupted') — and both stamp
        completed_at, so the scan then passes list_scans' `completed_at IS NOT NULL` filter and
        loads into the dashboard with those counters still NULL.

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
            for f in files:
                f["sourceName"] = src_label
                self._db.execute(cur,
                    "SELECT rule_id,wcag,severity,detail,page,location FROM issue_records WHERE scan_id=%s AND file=%s",
                    (sid, f["file"]))
                f["issues"] = self._db.fetchall(cur)
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
            if run.get("status") in ("cancelled", "interrupted"):
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
            where, params = "source=%s AND COALESCE(completed_at, started_at) < %s", (me["source"], me["at"])
            if owner:
                where += " AND owner_email=%s"; params = params + (owner,)
            self._db.execute(cur,
                "SELECT id FROM scan_runs WHERE " + where
                + " ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 1", params)
            row = self._db.fetchone(cur)
            return row["id"] if row else None

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
            return (s.get("kind"), s.get("folder"), s.get("site"))
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
        """Live progress for an in-flight remediation batch: how many remediate_file
        jobs are still queued/running for this scan, plus the most recently fixed file."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type='remediate_file' "
                "AND status IN ('queued','running')", (scan_id,))
            in_flight = self._db.fetchone(cur)["n"]
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type='remediate_file' "
                "AND status='dead'", (scan_id,))
            failed = self._db.fetchone(cur)["n"]
            self._db.execute(cur,
                "SELECT file,drive_write_url FROM file_records WHERE scan_id=%s "
                "AND remediated_at IS NOT NULL ORDER BY remediated_at DESC LIMIT 1", (scan_id,))
            latest = self._db.fetchone(cur)
        return {"in_flight": in_flight, "failed": failed,
                "latest_file": latest["file"] if latest else None,
                "latest_url": latest["drive_write_url"] if latest else None}

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
          PASS / FAIL / ERROR  — the rule applies to this file's format and ran
          NOT_APPLICABLE       — the rule belongs to a different format (e.g. a
                                 PPTX rule against a .docx). Recorded explicitly so
                                 an auditor can see a rule was *considered*, not
                                 silently omitted. N/A does not count against
                                 completeness (completeness = checked / applicable).
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, rule_id, status, finding_count "
                "FROM scan_file_manifests WHERE scan_id=%s ORDER BY file, rule_id",
                (scan_id,))
            rows = self._db.fetchall(cur)
            # File extensions in this scan (to know each file's applicable rule set).
            self._db.execute(cur,
                "SELECT DISTINCT file FROM scan_file_manifests WHERE scan_id=%s", (scan_id,))
            scan_files = [r["file"] for r in self._db.fetchall(cur)]

        catalog = self._full_catalog_rules()
        # Map every engine rule_id → its engine, for NOT_APPLICABLE derivation.
        all_rule_ids = {r["id"]: eng for eng, rules in catalog.items() for r in rules}

        by_file: dict[str, list[dict]] = {}
        for r in rows:
            by_file.setdefault(r["file"], []).append({
                "rule_id": r["rule_id"],
                "status": r["status"],
                "finding_count": r["finding_count"],
            })
        files = []
        total_expected = total_checked = total_errored = total_na = 0
        for fname in sorted(scan_files):
            rules = by_file.get(fname, [])
            applied_ids = {r["rule_id"] for r in rules}
            # Rules from other formats → explicit NOT_APPLICABLE.
            na = [{"rule_id": rid, "status": "NOT_APPLICABLE", "finding_count": 0}
                  for rid in sorted(all_rule_ids) if rid not in applied_ids]
            expected = len(rules)
            errored = sum(1 for r in rules if r["status"] == "ERROR")
            checked = expected - errored
            total_expected += expected
            total_checked += checked
            total_errored += errored
            total_na += len(na)
            files.append({
                "file": fname,
                "rules_expected": expected,
                "rules_checked": checked,
                "rules_errored": errored,
                "rules_not_applicable": len(na),
                "completeness_pct": round(checked / expected * 100) if expected else 100,
                "complete": errored == 0,
                "rules": rules + na,
            })
        return {
            "scan_id": scan_id,
            "files_total": len(files),
            "rules_expected_total": total_expected,
            "rules_checked_total": total_checked,
            "rules_errored_total": total_errored,
            "rules_not_applicable_total": total_na,
            "completeness_pct": (
                round(total_checked / total_expected * 100) if total_expected else 100
            ),
            "complete": total_errored == 0,
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
                self._db.execute(cur,
                    "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status,page,pages) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
                    (item_id, now, scan_id, c["file"], c["rule_id"], c["rule_name"], c["finding_count"],
                     pages[0] if pages else None, _pages_csv(pages)))
            created.append({"id": item_id, "scan_id": scan_id, "file": c["file"],
                             "rule_id": c["rule_id"], "rule_name": c["rule_name"],
                             "finding_count": c["finding_count"], "status": "pending", "created_at": now,
                             "page": pages[0] if pages else None, "pages": _pages_csv(pages)})
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
            if p.get("explain_only"):
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
            owes_nothing = self._row_is_resolved(row) or self._row_is_explain_only(row)
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
                owes_nothing = self._row_is_resolved(row) or self._row_is_explain_only(row)
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
            pass   # certification itself must not fail on a logging error
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
                             error: str | None = None) -> None:
        """Persist the most recent scheduled sweep's outcome. Best-effort: a sweep must not fail
        because its bookkeeping did."""
        import json as _json
        try:
            self.set_setting(self._SWEEP_KEY, _json.dumps({
                "ok": bool(ok), "at": when, "source": source,
                "scan_id": scan_id, "files": files,
                # Truncated: this reaches the browser, and a Google HttpError repr carries the
                # full request URL. Enough to recognise the failure, not a wall of query string.
                "error": (error or None) and str(error)[:400],
            }))
        except Exception:
            pass

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

    def worker_tier_status(self, window_s: int = 120) -> dict:
        """The heartbeat with its AGE, not just a boolean.

        `worker_tier_alive` answers the scan-start guard's yes/no question, which is all that
        guard needs. It is useless for alerting: "false" cannot distinguish a worker that died
        thirty seconds ago from one that has been gone for a fortnight, and those want different
        responses. This returns the timestamp and its age so a monitor can say which.

        Age is None when no worker has EVER beaten — a fresh deploy that never started its
        worker tier, which is a different failure from one that stopped, and reads differently
        in an alert.
        """
        from datetime import datetime, timezone
        raw = self.get_setting("worker_tier_heartbeat")
        out = {"alive": False, "heartbeat_at": raw or None, "age_s": None,
               "window_s": window_s, "ever_seen": bool(raw)}
        if not raw:
            return out
        try:
            beat = datetime.fromisoformat(raw)
        except ValueError:
            # A malformed timestamp is a real fault, not "no heartbeat" — say so rather than
            # letting it read identically to a tier that never started.
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
        try:
            beat = datetime.fromisoformat(raw)
        except ValueError:
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

    def memory_guidance(self, org: str, rule_id: str | None, format: str | None) -> list[str]:
        """The ACTIVE guidance fragments that apply to a (org, rule, format) draft, ordered
        most-specific-first (rule+format > rule > format > org-wide). Only 'active' rules —
        'proposed'/'derived' never influence a draft until accepted (ADR 0021 §D). Returns
        the raw guidance strings; the caller composes them into the prompt."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id,format,guidance FROM org_memory "
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
        out: list[str] = []
        for r in keep:
            g = (r.get("guidance") or "").strip()
            if g and g not in seen:
                seen.add(g)
                out.append(g)
        return out

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
                    priority: int = 100, max_attempts: int = 5,
                    run_after: str | None = None, scan_id: str | None = None,
                    campaign_id: str | None = None, batch_id: str | None = None) -> str:
        import json as _json
        now = self._now()
        job_id = uuid.uuid4().hex[:16]
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
                pass
        return row

    @staticmethod
    def _lease_expiry(lease_seconds: int | None = None) -> str:
        from datetime import datetime, timezone, timedelta
        secs = lease_seconds if lease_seconds is not None else int(
            os.environ.get("ACP_JOB_LEASE_S", "600"))
        return (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()

    def claim_job(self, worker_id: str) -> dict | None:
        """Atomically claim the next eligible job. Returns the claimed job (with
        attempts already incremented), or None if the queue is empty.

        Postgres: single-statement UPDATE...WHERE id=(SELECT...FOR UPDATE SKIP LOCKED)
        RETURNING * — each worker atomically grabs a distinct row with no round-trip race.
        SQLite: two-step optimistic CAS — SELECT then conditional UPDATE on status='queued'
        (SQLite serialises writers, so the window between the two is closed in practice)."""
        now = self._now()
        expires = self._lease_expiry()
        if self._db.supports_skip_locked:
            # Postgres path: atomic single-statement claim with SKIP LOCKED.
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "UPDATE jobs SET status='running', locked_at=%s, locked_by=%s, "
                    "attempts=attempts+1, updated_at=%s, lease_expires_at=%s, phase=NULL "
                    "WHERE id = ("
                    "  SELECT id FROM jobs "
                    "  WHERE status='queued' AND run_after<=%s "
                    "  ORDER BY priority, run_after "
                    "  FOR UPDATE SKIP LOCKED LIMIT 1"
                    ") RETURNING id",
                    (now, worker_id, now, expires, now))
                row = self._db.fetchone(cur)
            if not row:
                return None
            return self.get_job(row["id"])
        else:
            # SQLite path: optimistic two-step CAS.
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "SELECT id FROM jobs WHERE status='queued' AND run_after<=%s "
                    "ORDER BY priority, run_after LIMIT 1", (now,))
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

    def complete_job(self, job_id: str) -> None:
        scrubbed = self._scrub_payload_secrets(job_id)
        with self._db.cursor() as cur:
            if scrubbed is not None:
                self._db.execute(cur,
                    "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL, payload=%s WHERE id=%s",
                    (self._now(), scrubbed, job_id))
            else:
                self._db.execute(cur,
                    "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL WHERE id=%s",
                    (self._now(), job_id))

    def dead_letter_breakdown(self, owner: str | None = None) -> dict:
        """Diagnostic: dead-lettered jobs grouped by type + the most common errors.
        owner scopes to the caller's own jobs so error text (which can name a file)
        never leaks across tenants."""
        scope = " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        sp = (owner,) if owner else ()
        out: dict = {}
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT type, COUNT(*) AS n FROM jobs WHERE status='dead'" + scope + " GROUP BY type", sp)
            out["by_type"] = {r["type"]: r["n"] for r in self._db.fetchall(cur)}
            self._db.execute(cur,
                "SELECT type, SUBSTR(last_error,1,200) AS err, COUNT(*) AS n FROM jobs "
                "WHERE status='dead'" + scope + " GROUP BY type, SUBSTR(last_error,1,200) ORDER BY n DESC LIMIT 15", sp)
            out["top_errors"] = [{"type": r["type"], "n": r["n"], "error": r["err"]}
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

    def touch_job(self, job_id: str) -> None:
        """Heartbeat: extend a running job's lease so the stuck-job sweeper won't
        reclaim a slow-but-alive job (e.g. a long PII scan). Called periodically by
        the worker while the handler runs."""
        now = self._now()
        expires = self._lease_expiry()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET locked_at=%s, updated_at=%s, lease_expires_at=%s "
                "WHERE id=%s AND status='running'",
                (now, now, expires, job_id))

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
                self.save_file_result(scan_id, {
                    "file": r["file"], "engine": "n/a", "status": "error", "score": None,
                    "compliant": 0, "skipped_rules": 0, "issues": [],
                    "drive_file_id": r.get("drive_file_id")}, now_iso)
            except Exception:
                pass
            # The REASON, in the one place the UI already looks for it: fileErrorReason.js reads
            # `scan.file_error` rows to say why a document has no findings, and refuses to invent a
            # reason when none was recorded. Without this the drawer would say the reason was not
            # recorded — which would be true, and useless, when the queue knew it all along.
            try:
                self.log_decision("system", "scan.file_error", scan_id=scan_id, file=r["file"],
                                  detail=f"job dead-lettered: {error}"[:200])
            except Exception:
                pass

    def fail_job(self, job_id: str, error: str, backoff_seconds: float = 0.0,
                 force_dead: bool = False) -> str:
        """Requeue a failed job with backoff, or dead-letter it once attempts are
        exhausted (or immediately when force_dead). Returns 'queued' or 'dead'."""
        from datetime import datetime, timezone, timedelta
        job = self.get_job(job_id)
        if job is None:
            return "missing"
        now = datetime.now(timezone.utc)
        if force_dead or job["attempts"] >= job["max_attempts"]:
            # BEFORE the payload is scrubbed — scrubbing is what removes the file names this needs.
            self._record_dead_scan_files(job, error, now.isoformat())
            scrubbed = self._scrub_payload_secrets(job_id)
            with self._db.cursor() as cur:
                if scrubbed is not None:
                    self._db.execute(cur,
                        "UPDATE jobs SET status='dead', last_error=%s, updated_at=%s, payload=%s WHERE id=%s",
                        (error[:2000], now.isoformat(), scrubbed, job_id))
                else:
                    self._db.execute(cur,
                        "UPDATE jobs SET status='dead', last_error=%s, updated_at=%s WHERE id=%s",
                        (error[:2000], now.isoformat(), job_id))
            # One greppable stdout line per dead-letter — the platform alert
            # (Log Analytics scheduled query) keys on 'job dead-lettered'.
            print(f"[acp] job dead-lettered: id={job_id} type={job.get('type')} error={error[:160]}", flush=True)
            return "dead"
        run_after = (now + timedelta(seconds=backoff_seconds)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='queued', run_after=%s, locked_at=NULL, "
                "locked_by=NULL, last_error=%s, updated_at=%s WHERE id=%s",
                (run_after, error[:2000], now.isoformat(), job_id))
        return "queued"

    def reclaim_stuck_jobs(self, lease_seconds: int = 600) -> int:
        """Requeue jobs stuck in 'running' past their lease (worker died mid-job).

        Uses lease_expires_at < now() when the column is set (all jobs claimed after the
        migration), falling back to the locked_at+lease_seconds arithmetic for rows that
        pre-date the column (no lease_expires_at) — so the sweeper is correct across a
        rolling deploy."""
        from datetime import datetime, timezone, timedelta
        now = self._now()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='queued', locked_at=NULL, locked_by=NULL, "
                "lease_expires_at=NULL, updated_at=%s "
                "WHERE status='running' AND ("
                "  (lease_expires_at IS NOT NULL AND lease_expires_at<%s)"
                "  OR"
                "  (lease_expires_at IS NULL AND locked_at<%s)"
                ")",
                (now, now, cutoff))
            return getattr(cur, "rowcount", 0) or 0

    def job_stats(self, owner: str | None = None) -> dict:
        # owner → only this user's jobs (scoped via their scans), so the queue view
        # doesn't leak other tenants' activity. None = global (operator/admin context).
        scope = " WHERE scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT status, COUNT(*) AS n FROM jobs" + scope + " GROUP BY status",
                             (owner,) if owner else ())
            return {r["status"]: r["n"] for r in self._db.fetchall(cur)}

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
                "owner_email) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (audit_id, self._now(), doc_id, policy_id, action, result, detail, owner_email))

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

    def list_scan_severities(self, scan_id: str) -> list[dict]:
        """{file, severity} for every finding in a scan -- the input compute_batches
        (api/campaigns.py) buckets by, kept as its own narrow query like
        list_file_identities (Phase 2) rather than widening get_scan's SELECT."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT file, severity FROM issue_records WHERE scan_id=%s", (scan_id,))
            return self._db.fetchall(cur)
