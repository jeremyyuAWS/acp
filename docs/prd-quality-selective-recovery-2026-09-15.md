# PRDs 4–6 and quality portion of 9: selective quality recovery

## Problem and evidence

PR #2077 (dbf2a2a4) added source image review, chart relationship guards and saved Office caption verification. Current vision recovery nevertheless regenerates all images and replaces every matching pending proposal. A retry for one missing image can therefore spend on, or change, a usable author caption or previously grounded draft. Document-wide persistence also counts resolved findings and can replay obsolete finding IDs if dispositions change during generation.

## Requirements

Recover missing, template and explicitly blocked image drafts only. Keep usable pending drafts byte-for-byte and exclude their locators before paid inference. Preserve source hashes, exact figure associations, immutable run consent, two-attempt limit, shared ledger and existing automatic approval/writer/publishing policies. Recheck current remaining finding identities at persistence and omit resolved/excluded/superseded targets. Model agreement and saved text presence do not prove semantic compliance. Ambiguous charts remain exceptions; independently canonical-validated PDF captions remain eligible for existing automatic approval. No model evaluations or production deployment in this task.

## Acceptance

Offline fixtures demonstrate that recovery cannot replace usable drafts or dispatch their image inference, and that terminal finding dispositions cannot be reintroduced from cached or fresh document replies. UI distinguishes source comparison and unresolved meaning from saved verification without granting approval from display evidence. Existing cancellation, budget, exact-source, chart mismatch and saved-package regression checks pass. Submit a scoped PR; parent coordinates green CI and release readiness.
