# Representative AI impact estimates

The read-only Plan estimate projects **additional usable suggestions after rules** from independent evaluated finding outcomes. It does not predict verified fixes, savings, compliance, or authorization to apply changes. The existing rules-only start path remains independent of this disclosure. No preview performs paid inference.

## Implemented contract

`api/remediation_cohort_estimates.py` consumes optional `impact_evidence` in the shared owner-scoped immutable calibration registry. It creates no second evaluation store. Ingestion calls `normalize_impact_evidence`; source text, prompts and extra fields are discarded. The registry owner remains responsible for access control, immutable versions and independent evaluation provenance.

An impact bundle has schema version `ai-impact-cohort.v1`, `representative`, `population_size`, `expires_at`, `charges_complete`, `samples`, and `charges`. Samples contain canonical `finding_id`, `source_revision`, `operation_id`, `evidence_id`, `observed_at`, `rules_unresolved: true`, and an independently labelled `usable` boolean. One source finding counts once; retries/revisions are reconciled upstream to a canonical label. Identical replays deduplicate and conflicting labels fail closed.

Charges contain stable `charge_id`, attributed `operation_id`, `purpose` (generation/review/adjudication), `status` (settled/held/unknown), and `amount_usd`. Retry charges with distinct provider charges remain real costs; replayed charge IDs do not double count. Unknown amounts remain null. Held reservations are not settled spend. `charges_complete` is an ingestion assertion backed by reconciled provider billing, not a browser input. Missing operation charges, unknown charges, or reservations suppress cost projections. Generation/review/final-step totals remain separate.

A matching calibration record supplies format, change family, exact configuration ID, immutable evaluation version, evaluated date, and evaluated (never synthetic) dataset/report provenance. At least 30 independent labelled finding cases within 30 days and before expiry are required. The default is conservative availability, not an administrator policy floor or application decision.

For N matching eligible findings, the expected-count interval is the 95% Wilson interval on unique usable outcomes multiplied by N, rounded outward. This describes uncertainty about the expected count, not a predictive guarantee for a particular run. Provider cost bounds are the observed min/max attributed cost per evaluated finding multiplied by N. They include failed attempts and reviews; they are not statistical confidence bounds. Costs for shared operations are allocated once across mapped findings. Observed cost per usable outcome uses total settled cost divided by usable findings, and is unavailable if there are no usable findings.

`estimate_plan` accepts only a **server-produced** complete population with immutable scope and assessment revisions, a configuration revision equal to the registry-computed configuration digest, and exact eligible finding/source identities, format, family, and configuration. Mixed configurations/populations are unavailable pending stratified support. It selects the newest matching evaluation without searching older records for a better rate. The read-only `POST /scans/{sid}/remediation/impact-estimate` reuses the existing routing preview's owner, scope and policy checks and no-store response. Plan preview embeds the same `estimated_impact` result. Neither route accepts evaluation evidence or caller-supplied eligible finding counts.

## Production prerequisites

No representative production cohort was supplied or seeded by this change. Fixture cases exist only in tests.

Before real Plan estimates can appear, operators must ingest an independently evaluated, representative production cohort in the shared calibration registry, including exact model/reviewer configuration, current dataset/report provenance, canonical finding outcomes, and complete attributed provider billing if cost estimates are wanted. Separately, the execution/assessment evidence producer must supply audited `estimate_population` mapping current selected scope findings to the same format/family/configuration, bind the immutable assessment and scope revisions, and provide current revision refreshes to the caller. Current rule-level aggregate ordinals are insufficient and intentionally do not populate that field. The live disclosure consequently reports insufficient applicable evidence.

Tests cover complete, sparse, stale, synthetic, mixed and out-of-population evidence; historical missing lineage; deduplicated outcomes and charge replays; held/unknown/missing charges; private content stripping; and stale UI scope refreshes.
