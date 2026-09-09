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
