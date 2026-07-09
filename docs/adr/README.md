# Architecture Decision Records — acp

Accepted architectural decisions for the Accessibility Compliance Platform.
Numbered sequentially; newest decisions may supersede older ones (noted in the
header). Match the structure of the latest ADR when adding a new one.

- [0001 — Read-only assessment spine on MDK; engines harvested behind the `A11yIssue` contract](0001-read-only-assessment-spine-on-mdk.md) — **Accepted** (2026-06-16)
- [0002 — Assessment transparency specification](0002-assessment-transparency-spec.md) — **Accepted** (2026-06-24)
- [0003 — Document lifecycle data model](0003-document-lifecycle-model.md) — **Proposed** (2026-06-25)
- [0004 — Durable orchestration via a Postgres job queue](0004-postgres-job-queue.md) — **Proposed** (2026-06-25)
- [0005 — Server-side remediation engine](0005-server-side-remediation.md) — **Accepted** (2026-06-25)
- [0010 — Azure Blob as the remediated-output store (Drive write becomes opt-in)](0010-remediated-output-object-store.md) — **Proposed** (2026-06-30)
- [0011 — Incremental scans: skip unchanged files across scan runs](0011-incremental-scan-fingerprinting.md) — **Proposed** (2026-06-30)
- [0012 — Own the Office analysers; fix the language rules](0012-own-office-analysers.md) — **Accepted** (2026-07-08)
- [0013 — Worker durability hardening: idempotent finalize + worker-process isolation](0013-worker-durability-hardening.md) — **Proposed** (2026-07-08)

- [0014 — Keep long-running scans authenticated (Drive token refresh)](0014-drive-token-refresh.md) — **Accepted** (Tier 1) / **Proposed** (Tier 2) (2026-07-09)
- [0016 — Evidence-based confidence signal (derived, never a fabricated %)](0016-evidence-based-confidence.md) — **Accepted** (2026-07-09)
