# Evaluated reliability for AI review

Review all AI changes remains the default. There is no default reliability percentage.
An administrator must explicitly permit each objectively checkable change family, establish
its minimum reliability, minimum independent sample count, and freshness window, and validate
its controlled writer before any run can request automatic application. Generic AI text and
subjective meaning changes always require a person.

Calibration ingestion is an operator-only action, scoped to the owning account. Each immutable
`ai-review-calibration.v1` evaluation records exact format, change family, generating and reviewing
provider/model, validator version, evaluation time, dataset/report SHA256, and unique independent
sample judgments with evidence references. Duplicate samples are rejected. Success counts and bounds
are recomputed; supplied confidence values are never trusted. An identical version replay is a no-op;
changing its content requires a new version. Synthetic fixture provenance cannot authorize application.
Operators are responsible for verifying representative evaluation provenance and independence;
labeling an uploaded file `evaluated` is not proof of a production qualification study.

The reliability measure is the lower endpoint of the two-sided 95% Wilson score interval:
`(p + z²/(2n) - z sqrt(p(1-p)/n + z²/(4n²))) / (1 + z²/n)`, with
`z = 1.959963984540054`, `n` independent samples and `p` their observed pass proportion.
This is cohort evidence, not certainty about an individual change. Equality at the approved
threshold qualifies only after every other gate passes. A perfect small sample is insufficient.

Run approval must freeze threshold, permitted families, evaluation versions, configuration, and
administrator restrictions. Later settings changes cannot broaden it. Evaluation freshness and
source/proposal identity must be rechecked immediately before controlled application. Approval is
not a verified fix: the existing writer and verification/recovery path determine completion.
No preview or ingestion operation calls a paid model. Genuine representative evaluated datasets
and an explicitly authorized budget for acquiring them are separate prerequisites.

Operator workflow:

- Validate an evaluation offline: `python scripts/ingest_ai_review_calibration.py evaluation.json`.
- Ingest a reviewed evaluation: add `--ingest --owner ACCOUNT` using the normal configured database environment.
- Validate administrator configuration: `python scripts/ingest_ai_review_calibration.py admin.json --administrator`; add `--ingest` only when ready to save.

Administrator schema is `ai-review-admin.v1`, with `families` mapping explicit family names to
`minimum_reliability` (0–100), `minimum_sample_size` (positive integer), `freshness_days`
(positive integer), and `writer_supported: true`. This declaration cannot register a writer:
only the code-owned `SUPPORTED_WRITERS` registry authorizes a complete adapter. It is empty
in production. Adapter tests register fixtures only and do not qualify any production model.

Existing writer audit: alt text, link text, accessible names, sensory rewrites, labels/titles,
and image transcription require semantic judgment or lack independent authoritative evidence.
The restricted `html-root-language` helper can verify an explicitly authoritative language
transformation, but lacks the real execution's exact structured review and source binding.
Before registering that family, connect those bindings, validate its controlled writer and
post-write artifact evidence, evaluate representative independent cases for the exact model /
reviewer / validator configuration, and set a justified administrator floor and freshness window.

The dispatch receipt is policy authorization, not a second proposal ledger. It references the
canonical immutable snapshot and source digest. A crashed or uncertain write remains awaiting
completion/recovery and is fenced against automatic replay; its existence never means verified.
