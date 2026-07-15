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

- [0014 — Keep long-running scans authenticated (Drive token refresh)](0014-drive-token-refresh.md) — **Accepted** (Tier 1); Tier 2 superseded by 0017 (2026-07-09)
- [0015 — Page-render / thumbnail seam (lazy PDF→PNG, blob-cached)](0015-page-render-thumbnail-seam.md) — **Accepted** (PDF) / **Proposed** (Office) (2026-07-09)
- [0016 — Evidence-based confidence signal (derived, never a fabricated %)](0016-evidence-based-confidence.md) — **Accepted** (2026-07-09)
- [0017 — Server-side Drive refresh via the OAuth authorization-code flow](0017-drive-offline-refresh-auth-code-flow.md) — **Proposed** (2026-07-09)
- [0018 — Slide/page rasterization + per-shape geometry (the visual-evidence seam)](0018-slide-page-rasterization-and-shape-geometry.md) — **Proposed** (2026-07-11)
- [0019 — AI provider gateway + governance (local-first, quality-verified, auditable)](0019-ai-provider-gateway-and-governance.md) — **Proposed** (2026-07-11)
- [0020 — Separating Discover (inventory) from Assess (conformance)](0020-discover-assess-phase-separation.md) — **Accepted** (2026-07-12)
- [0021 — Enterprise review memory (org style + derived preferences → curated draft guidance)](0021-enterprise-review-memory.md) — **Accepted** (2026-07-12)
- [0022 — GPU vision as the default via a scale-to-zero RunPod Serverless endpoint](0022-gpu-vision-default-runpod-serverless.md) — **Proposed** (2026-07-13)
