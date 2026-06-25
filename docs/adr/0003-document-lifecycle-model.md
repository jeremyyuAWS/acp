# ADR 0003 — Document Lifecycle Data Model

**Status:** PROPOSED
**Date:** 2026-06-25
**Authors:** ACP team

---

## Context

The PRD wishlist asks for four governance capabilities — **configurable file
disposition (1)**, **partial-remediation workflow (2)**, **intelligent triage &
prioritization (3)**, and **phased remediation campaigns (4)**. Today these exist
only as frontend demo UX (`sim.js` + React state). None are persisted or enforced
by the backend.

The single root cause: the data model has **no durable record of a document as a
governed object**. `file_records` captures only `scan_id, file, engine, status,
score, compliant, skipped_rules, drive_file_id, remediated_at, drive_write_url` —
a per-scan snapshot, not a lifecycle. There is no place to store an owner, a
department, an age, a disposition decision, a per-violation remediation state, or
a campaign membership. So every rich governance feature is necessarily faked in
the client.

This ADR defines the persistence model that makes ideals 1–4 buildable. It is the
prerequisite for any of that work; it does not implement the features themselves.

## Decision

Introduce a **document-centric** layer alongside the existing scan-centric tables.
A *scan* remains an immutable event; a *document* is the long-lived governed object
that accumulates state across scans.

### New tables

```
documents
  doc_id TEXT PRIMARY KEY          -- stable identity (source + path hash, or drive_file_id)
  source TEXT                      -- drive | sharepoint | local
  path TEXT                        -- human path/name
  content_hash TEXT                -- for duplicate / obsolete detection
  owner TEXT
  department TEXT
  created_at TEXT                  -- document age signal
  last_seen TEXT
  usage_signal INT                 -- views / opens, if the source exposes it
  regulatory_tags TEXT             -- JSON array: ["HIPAA","EAA-high-risk",...]
  business_criticality TEXT        -- critical|high|medium|low (from ontology)
  triage_score INT                 -- computed server-side (see Ideal 3)
  triage_rationale TEXT            -- why this score — white-box

remediation_state
  doc_id TEXT
  rule_id TEXT                     -- per-VIOLATION state, not just per-file
  state TEXT                       -- not_started|in_progress|partially_remediated|awaiting_review|complete
  updated_at TEXT
  last_scan_id TEXT                -- resume point
  PRIMARY KEY (doc_id, rule_id)

disposition_policy
  policy_id TEXT PRIMARY KEY
  name TEXT
  match TEXT                       -- JSON predicate (age>730 AND dept='Legal' …)
  action TEXT                      -- leave|archive|rename|move|delete
  action_config TEXT               -- JSON (target folder, naming convention, …)
  requires_approval INT
  enabled INT

disposition_audit                  -- what actually happened to each file
  id TEXT PRIMARY KEY
  ts TEXT
  doc_id TEXT
  policy_id TEXT
  action TEXT
  result TEXT                      -- applied|pending_approval|failed
  detail TEXT                      -- e.g. new path / drive url / error

campaign
  campaign_id TEXT PRIMARY KEY
  name TEXT
  status TEXT                      -- draft|active|paused|complete
  scope TEXT                       -- JSON (departments, sources, priority filter)
  created_at TEXT

campaign_batch
  batch_id TEXT PRIMARY KEY
  campaign_id TEXT
  seq INT                          -- rollout order
  status TEXT                      -- pending|active|paused|complete
  filter TEXT                      -- JSON (which docs in this batch)
  deadline TEXT
```

### Relationships & rules

- `documents` is the system of record for governance metadata. A scan **upserts**
  the document row (refresh `last_seen`, re-derive `triage_score`) but never owns
  the disposition / campaign state.
- `remediation_state` is keyed per `(doc_id, rule_id)` so "3 of 5 violations
  fixed" (Partially Remediated) and "resume from last step" are first-class. It
  supersedes the binary `file_records.remediated_at`.
- The existing `hitl_queue` becomes the **Awaiting Human Review** state of
  `remediation_state` (the queue is the work-list; the state is the truth).
- `disposition_policy` is admin-configured; `disposition_audit` is append-only
  (same posture as `decision_log` from the Tier-1 work).
- Triage scoring (`triage_score` + `triage_rationale`) is computed **server-side**
  from the document's own metadata — never in the client — so it is auditable and
  every rank is explainable (Ideal 9).

### Boundary preserved

This is additive. `scan_runs / file_records / issue_records / scan_rule_traces /
scan_file_manifests` are unchanged — scans stay immutable events. The document
layer reads from them and accumulates state. No change to the `/api/v1` scan
contract, the rubric schema, or the rule catalog.

## Consequences

**Enables, with this model in place:**
- Ideal 1 — disposition: policies + real Drive move/delete/archive + an audit row.
- Ideal 2 — partial remediation: a real per-violation state machine with resume.
- Ideal 3 — triage: a server-side scorer over `documents`, duplicate/obsolete
  detection via `content_hash` + `last_seen`/`usage_signal`.
- Ideal 4 — campaigns: persisted batches with pause/resume; HITL + triage scoped
  by campaign.

**Costs / risks:**
- Document identity (`doc_id`) across sources is non-trivial — a moved/renamed
  Drive file must map to the same document. Start with `drive_file_id` where
  available, fall back to `source + content_hash`.
- Disposition that **deletes/moves** customer files is irreversible — gate behind
  `requires_approval` + the immutable `disposition_audit`, and never act without
  an explicit policy the admin enabled.
- Migration: `sim.js`'s synthetic metadata becomes the seed shape for `documents`;
  a real Drive/SharePoint scan must extract owner/department/age (connector work).

## Implementation order (when approved)

1. `documents` table + upsert-on-scan + a server-side triage scorer (unblocks 3).
2. `remediation_state` machine + migrate `remediated_at` semantics (unblocks 2).
3. `disposition_policy/audit` + real Drive move/delete/archive (unblocks 1).
4. `campaign/campaign_batch` + scope HITL/triage by campaign (unblocks 4).

Each step is independently shippable and leaves the scan contract untouched.
