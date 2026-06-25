# PRD Conformance Roadmap

Maps the 9 ACP PRD wishlist ideals to **what exists today** (honestly: backend-real
vs. frontend-simulated demo) and the concrete work to close each gap. Audited
2026-06-25.

Legend: 🟢 backend-real · 🟡 partial · 🔴 frontend-demo only

## Status at a glance

| # | Ideal | Status | Where it lives |
|---|-------|--------|----------------|
| 1 | Configurable File Disposition | 🔴 demo | `sim.js`, `Discover.jsx`; only Drive write-to-`Remediated/` is real |
| 2 | Partial Remediation Workflow | 🔴 demo | binary `remediated_at` + `hitl_queue`; no per-violation state |
| 3 | Intelligent Triage & Prioritization | 🔴 demo | scoring in `sim.js`/`Remediate.jsx`; no backend, no metadata persisted |
| 4 | Phased Remediation Strategy | 🔴 demo | batches computed in `Monitor.jsx`; no campaigns table |
| 5 | Modular Deterministic Validation Engine | 🟡 partial | HTML = one-module-per-rule ✓; Office/PDF = opaque vendored engine |
| 6 | Deterministic-Only Operating Mode | 🟢 real | enforced backend-wide (ADR Tier-1, 2026-06-25) |
| 7 | Validation Coverage & Traceability | 🟢 real | `scan_file_manifests` + `scan_rule_traces` + Langfuse spans + `NOT_APPLICABLE` |
| 8 | Transparent Validation Specification | 🟡 partial | ADR 0002 covers transparency; remediation logic/order/extensibility under-specified |
| 9 | White-Box Controls & Explainability | 🟡 partial | backend traces + immutable `decision_log` real; UI doesn't fully surface them |

## What shipped 2026-06-25 (Tier-1 hardening)

Made the deterministic / audit / traceability ideals **backend-real**, not UI hints:

- **#6** — `app_settings.ai_enabled` (admin, persisted) hard-overrides per-scan
  `?ai=`; `/ai/explain` → 403 when off; deterministic scans **auto-route**
  ai-assisted findings to the HITL queue. `GET/PUT /settings`, `/ai/status` reports mode.
- **#7** — `get_scan_manifest` now emits explicit `NOT_APPLICABLE` for every rule
  that doesn't apply to a file's format (answers "was rule X considered?" for *all*
  rules, not just the file's format).
- **#9** — append-only `decision_log` + `GET /decisions`: scan mode, auto-routing,
  every HITL approve/reject/skip (actor + note), settings changes.

## Roadmap

### Tier 1 — remaining (cheap, high trust)
- **#7/#9 UI surfacing** — the Assess view must show `completeness_pct` + an
  errored-rule warning (backend serves `/scans/{id}/manifest`; ADR 0002 §5 promised
  it; frontend doesn't render it). A score must never appear without its completeness.
  *Note:* the deployed demo runs `SIM=true`; surfacing requires either wiring the
  real endpoint or adding manifest data to `sim.js`.
- **#9** — surface deterministic-fix **rationale** (the `fix()` change descriptions)
  and the `decision_log` as a visible audit trail in the UI.

### Tier 2 — the document-lifecycle model (unblocks #1–#4)
See **[ADR 0003](adr/0003-document-lifecycle-model.md)**. One persistence layer
(`documents` + `remediation_state` + `disposition_policy/audit` + `campaign/
campaign_batch`) is the prerequisite for all four governance ideals. Ship order:
1. `documents` + server-side triage scorer → **#3**
2. `remediation_state` machine (per-violation, resumable) → **#2**
3. `disposition_policy/audit` + real Drive move/delete/archive → **#1**
4. `campaign/campaign_batch` + campaign-scoped HITL/triage → **#4**

### Tier 3 — engine ownership & spec completion (#5, #8)
- **#5** — the modular "one module per rule, easy to edit" promise is true for HTML
  but false for ~31 Office/PDF rules (vendored DigitalA11y `.dll` / Python lib).
  Decide: (a) port Office/PDF rules into local modules under the `rules/` contract,
  or (b) formally accept them as a pinned third-party artifact. Either is fine —
  but the spec must stop implying local editability that doesn't exist.
- **#8** — extend ADR 0002 (or a new ADR) to formally specify: the remediation
  decision tree (auto / HITL / manual by `fix_mode` × ai-mode × engine-availability),
  the rule **execution order** (currently a code comment), human-review boundaries,
  and the Office/PDF extensibility contract.

## Framing for the GTM eval

This is a customer evaluation — some simulation is correct ("art of the possible").
The trap is letting #1–#4's polished UI imply backend capability that isn't there.
The wishlist's real center of gravity is the **deterministic / white-box / auditable**
story (#5–#9) — that is now largely real and is the platform's differentiator. Lead
with it; present #1–#4 as designed-and-specified (ADR 0003) rather than built.
