# Missing corrected PDF copies: verified recovery limit

Read-only production inspection on September 12, 2026 identified two failed
SharePoint delivery records in release `4a649a68085c473a`, scan `112bbf496c9a`:
`UTSW_Inisider_July2026.pdf` and `utsw-soc-guideline.pdf`.

Both cached originals were available and readable with pikepdf. They contain one
and eight pages respectively, are unencrypted, and have no `/StructTreeRoot`.
Both have pending `1.3.1` structural findings and no remediation timestamp or
corrected SHA-256. This is unsupported untagged-PDF reconstruction, rather than
evidence of file corruption or a corrected-file storage failure.

The original automatic-release authorization is failed and expired at
`2026-09-12T17:07:32.765509+00:00`. No production document, decision, permission,
queue, or delivery record was changed. An original cannot substitute for a
corrected artifact, and the expired authorization cannot be revived implicitly.

New terminal no-copy outcomes now diagnose this case using bounded cache-only
reads, current non-superseded structural findings, and matching source checksums.
They retain the `no_corrected_copy` failure identity and require a tagged
replacement or a repaired PDF, reassessment, and explicit new plan approval.
Unavailable, oversized, unreadable, encrypted, mismatched, or already-tagged
evidence retains the generic explanation rather than guessing the cause.

Historical failed documents receive a separate `recovery_explanation` only in
the owner-scoped Release GET response. The UI can show the actionable reason
without changing stored explanations, receipts, report fingerprints or immutable
reports. This does not claim either customer PDF has been corrected. Complete
untagged-PDF reconstruction still needs a preservation-tested writer and semantic
structure evidence.

Validation: 15 diagnosis/projection fixtures plus 42 automatic-release service tests,
including a terminal outcome proving diagnosis cannot admit an upload, fabricate
an artifact digest, or change the canonical failure category.
