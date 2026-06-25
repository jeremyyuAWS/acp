# ADR 0002 — Assessment Transparency Specification

**Status:** ACCEPTED  
**Date:** 2026-06-24  
**Authors:** ACP team  

---

## Context

ACP scans documents for WCAG 2.1 AA violations and produces a compliance score.
Customers (Deva, legal teams, procurement reviewers) need to know *which* rules
ran, *which* rules failed to run (engine error, unsupported format, skipped due
to rubric), and *why* a file received a particular score — before they act on
that score or include it in a formal report.

Without a transparency layer:

- A score of 100 could mean "zero violations found" or "the engine crashed and
  found nothing." These are very different situations.
- There is no machine-readable way to detect a partial scan.
- A customer cannot independently verify that every rule in the catalog was
  exercised.

ADR 0001 defined the scan engine seam. This ADR defines the **assessment
transparency contract**: what every rule must produce, and how the platform
surfaces that information.

---

## Decision

Every rule in `config/rule-catalog.json` must satisfy all of the following
requirements. Compliance with this spec is verified in CI by the rule integration
test suite (`tests/test_rule_contract.py`).

### 1 — Rule registry contract

Every rule entry in `config/rule-catalog.json` must have:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | ✅ | Unique across the whole catalog (not just the format) |
| `title` | string | ✅ | ≤ 80 chars, sentence case |
| `description` | string | ✅ | What the rule checks, in plain English. ≤ 300 chars |
| `wcag` | string | ✅ | Rubric key, e.g. `SC_1_1_1` |
| `wcag_sc` | string | ✅ | Dotted SC number, e.g. `1.1.1` |
| `wcag_display` | string | ✅ | Short SC label, e.g. `Non-text Content` |
| `wcag_level` | `"A"` \| `"AA"` | ✅ | WCAG conformance level |
| `severity` | `CRITICAL` \| `SERIOUS` \| `MODERATE` \| `MINOR` | ✅ | Drives scoring weight |
| `fix_mode` | `auto` \| `ai-assisted` \| `human-only` | ✅ | Drives HITL queue population |
| `source` | string | ✅ | Relative path to the implementing file |

A `docs/rules/RULE-ID.md` file must exist for every rule. See [docs/rules/README.md](../rules/README.md) for the required structure.

### 2 — Rule execution manifest

After every scan, the platform computes a **RuleCheckManifest** per file. It is
stored in the `scan_file_manifests` table and exposed at:

```
GET /scans/{scan_id}/manifest
```

#### Manifest statuses

| Status | Meaning |
|--------|---------|
| `PASS` | Rule ran; no findings. |
| `FAIL` | Rule ran; one or more findings. |
| `ERROR` | Rule could not be assessed (engine error, unsupported sub-format, etc.). |

A scan is **COMPLETE** when `rules_errored_total == 0` across all files.  
A scan is **INCOMPLETE** when any rule returned `ERROR` for any file.

#### Manifest schema (response shape)

```json
{
  "scan_id": "abc123",
  "files_total": 5,
  "rules_expected_total": 43,
  "rules_checked_total": 43,
  "rules_errored_total": 0,
  "completeness_pct": 100,
  "complete": true,
  "files": [
    {
      "file": "annual-report.pdf",
      "rules_expected": 7,
      "rules_checked": 7,
      "rules_errored": 0,
      "completeness_pct": 100,
      "complete": true,
      "rules": [
        { "rule_id": "pdf.missing-alt-text", "status": "FAIL", "finding_count": 3 },
        { "rule_id": "pdf.tagged",           "status": "PASS", "finding_count": 0 }
      ]
    }
  ]
}
```

### 3 — Langfuse span contract

Every rule execution must emit a Langfuse span with the following attributes:

| Attribute | Value |
|-----------|-------|
| `rule_id` | The catalog rule ID |
| `file` | The file being scanned |
| `outcome` | `PASS`, `FAIL`, or `ERROR` |
| `finding_count` | Integer ≥ 0 |
| `fix_mode` | From the catalog entry |
| `wcag_sc` | Dotted SC number |

This is already handled by `api/lf.py::rule_spans()` for the WCAG SC-level
traces. When the manifest is promoted to be the primary trace, `lf.py` must be
updated to emit per-`rule_id` spans using the catalog rule IDs.

### 4 — Rule documentation

Every rule must have a `docs/rules/RULE-ID.md` file containing:

1. **What it checks** — the exact condition that triggers a finding, including what is NOT checked.
2. **Why it matters** — the user impact on people with disabilities.
3. **Fix mode rationale** — why the fix mode is what it is.
4. **Unit test recipe** — a minimal code snippet demonstrating how to write a test.
5. **Failure modes** — known false positives and false negatives.

### 5 — Incomplete scan handling

The platform MUST NOT include a scan in a customer-facing compliance report if
`complete == false` in the manifest. The SPA should surface the manifest status
on the scan detail page with a warning when any file has errored rules.

---

## Alternatives considered

**A — Rely on the score alone.** A score of 100 is ambiguous (perfect vs.
engine crash). Rejected: unacceptable for legal/procurement use cases.

**B — Add an `error` status to `file_records`.** Already exists. But it is per-
file, not per-rule, and does not tell the caller which specific rules errored.
Rejected as insufficient.

**C — Embed manifest in the scan response.** Would bloat `GET /scans/{id}` for
large corpora. Rejected: separate endpoint keeps the scan summary lean.

---

## Consequences

- `config/rule-catalog.json` is now a first-class contract document. Schema
  changes require an ADR update or a new ADR.
- New rules require: catalog entry (with all required fields), rule doc, unit
  test, and Langfuse span wiring.
- The `scan_file_manifests` table is an append-only log. Old rows are never
  updated after the scan is committed.
- `GET /scans/{scan_id}/manifest` returns `{"complete": false, "files": []}` for
  scans run before this ADR was implemented (no manifest rows in the table).
  Those scans should be re-run to get full transparency.
