# Approved findings, verification, and Release

Investigated September 8, 2026 against fetched `origin/main` at `9999371b`.
MVP deadline supplied by the coordinating task: September 9, 2026, 10 a.m. Pacific.

## Finding

The supported approved-value path can reach Release eligibility. Approval alone
correctly does not do so. Two reproducible defects existed at the durable storage
boundary: verification credit preceded upload, and successful approved-value
uploads left artifact provenance stale. This change corrects both in
`api/handlers.py`; it does not relax compliance or Release eligibility.

The supplied production counts do **not** establish that these defects caused
those scans to stall. They mix finding dispositions with document eligibility;
a corrected document may still have legitimate human review or unwritten values.
No production data was changed, no model calls were purchased, and no provider
settings were changed during this investigation.

## Reproduction before correction

`tests/test_approved_release_progression.py` constructs a one-slide PPTX with an
empty title placeholder. A reviewer supplies a title. It runs the real title
writer and the first-party `PPTX_TITLE_EMPTY` detector, with local SQLite and an
in-memory blob provider. The full assessment verifier is replaced with the
result of that detector, so this fixture establishes an objectively measurable
title-presence fix, **not** the title's semantic quality or full WCAG compliance.
No automatic semantic approval is demonstrated or claimed.

The initial run produced five passing controls and two strict expected failures:

| Case | Before correction |
| --- | --- |
| Approval without application | Non-compliant; one unapplied approved value |
| Supported title write and successful verification/upload | Applied, finding resolved, eligible for Release |
| Criterion still failing | No upload or approval credit |
| Verification engine unavailable | No upload or approval credit |
| Unrelated pending human review | Corrected title persisted; file remained non-compliant |
| Upload raises after verification | Old bytes remain, but `applied=1`, unapplied count zero, finding `resolved_verified`; retry uploads nothing and file stays non-compliant |
| Successful approved-value upload | New bytes persisted, but `corrected_sha256`, byte count, and blob URL still described the earlier artifact |

The upload failure is a broken reconciliation, with falsely advanced finding
credit. It can strand a retry because `_approved_unapplied_rows` excludes applied
rows and `_apply_approved_values` returns when no values remain. The existing
review-certification gate could also accept that applied flag on a subsequent
review action; the fix prevents creating it before durable storage.

## Implemented correction

Each successful lane now accumulates its credit operation in memory. It still
verifies the written bytes and advances the next lane's regression baseline.
Failed verification retains the existing fail-closed behavior.

After all lanes finish, the handler requires a successful durable upload and a
nonempty blob URL. It then uses the existing `Store.transaction()` to commit:

1. The corrected artifact's URL, SHA-256, byte count, and remediation timestamp.
2. Verified remediation diffs, finding evidence, applied approval flags, and
   successful validation outcomes.
3. The existing `mark_file_compliant_if_reviewed` decision and certification log.

Credit uses the review item IDs captured before writing, rather than discovering
newly approved items after the upload. A storage failure commits none of these
facts; a database failure rolls them back together. The existing Drive copy link
is preserved. No store schema, route, frontend, or provider code was modified.

The added tests also exercise storage returning no URL and injected failures
after artifact metadata, approval credit, and certification writes. All eleven
progression cases pass after the correction, including a successful retry after
each injected failure. The two initial expected-failure markers were removed.

## Production evidence and remaining diagnosis

The coordinating task supplied these read-only observations:

| Scan | Corrected artifacts | Compliant documents | Approved pending verification | Resolved verified | Awaiting review |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2ae13a3abcab` | 22 | 0 | 486 | 352 | 14 |
| `afa80fd4e37a` | 4 | 0 | 13 | 13 | 5 |

The first scan also had one null disposition. Corrected artifact evidence
included `remediated_at`, `corrected_sha256`, and `blob_url`. Release GET requests
returned HTTP 200; successful retrieval does not establish release eligibility.

The current code explains several distinct states:

- `sync_hitl_finding_dispositions` projects approval to
  `approved_pending_verification`. Approval is a recorded decision, not proof of
  a persisted fix.
- Verified remediation diffs project evidence to `resolved_verified` in the
  canonical current remediation execution. Historical batches are not a valid
  source for current reconciliation.
- `mark_file_compliant_if_reviewed` requires a remediated file, all review items
  approved, no approved content awaiting application, and no unresolved
  regression. Pending/rejected/skipped items legitimately block it.
- An approved legacy value without a writable locator cannot be safely applied.
  Missing source bytes, unsupported lanes, unresolved locators, residual failing
  criteria, and unavailable verifiers also legitimately retain pending work.
- Explain-only confirmations and approved exception judgments can owe no content
  to the document. Their review decision must not be relabeled as an objectively
  verified document repair merely to make the finding totals look complete.
- `frontend/src/Remediate.jsx` computes a `complete` verification state from any
  revalidated document, written count, or reverified count once its queue is
  empty. This can describe progress even when no whole document is compliant.
  Release backend selection still requires `compliant AND remediated_at`.

To attribute the production scans, inspect each file's current execution,
non-approved review rows, approved/unapplied rows and their locators/resolutions,
application job failures, `apply.unverified`/`apply.unresolved`/regression events,
and the actual persisted artifact hash. Compare these with current-batch finding
evidence before proposing reconciliation. Do not bulk-flip dispositions,
`applied`, or `compliant` from aggregate counts.

## Limits and integration

The UI completion wording remains a separate correction for the coordinating
task. The backend's ability to certify an explicitly reviewed exception is not
evidence that an LLM may automatically approve it. Semantic judgments and
unsupported transformations remain human review work.

Blob storage and SQL do not share a transaction. If upload succeeds and SQL
fails, the database remains uncredited while storage may contain the new bytes.
The title fixture proves replay for an idempotent writer; this is not a claim
that every destructive transformation can rediscover its old locator after such
a failure. An immutable artifact/outbox recovery design and per-document
concurrency/review-revision protection remain broader integration concerns.
Existing production rows already credited before a failed upload are not
repaired automatically by this patch; recovery requires artifact evidence.

Open PRs checked before taking handler ownership: #1827 touches packaging and
`api/routes/scans.py`; #1814 touches evaluation documentation. Neither touched
`api/handlers.py`. Handler ownership was explicitly coordinated with the parent.

## Validation

Using the existing local Python virtual environment:

```sh
python -m pytest tests/test_approved_release_progression.py \
  tests/test_apply_approved_values.py tests/test_regression_blocks_certification.py \
  tests/test_ai_validation_outcomes.py tests/test_ai_validation_linkage.py \
  tests/test_finding_disposition_ledger.py tests/test_verification_fail_closed.py -q
```

Result: **93 passed**, including all eleven new regression cases.

A broader run including all `test_remediation_verified_*.py`, both described-image
round-trip modules, and PDF approved-value writeback produced **395 passed,
18 failed**. Every failing test was reproduced on an independent clean checkout
of `9999371b`: the same three image-of-text/description modules produced
**22 passed, 18 failed** there. Their failures include missing expected OCR
`1.4.5` findings; the local Office CLI build artifact is also absent. They are
baseline failures in this environment, not a clean full-suite result or newly
introduced regressions. No tests were skipped or weakened to hide them.

`git diff --check` passed. No merge or deployment was performed.
