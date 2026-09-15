# PRDs 7–8 and 9: assessment routing and saved progress evidence

Scope: reject known unavailable assessment vision models before dispatch; retain measured cloud admission timing when assessment enrichment cannot start; prevent partial runner completion from presenting a complete assessment. Preserve accepted local, legacy and Quality-first modes, permissions, originals, verification and delivery contracts. No paid evaluation or deployment.

The earlier scan 48ca3807fc5c reported 14 minicpm model_not_installed, eight moondream empty_response, one timeout, 75 shared_capacity_busy not-dispatched and 15 assessment_vision_budget_exhausted. These are historical assessment failures, preceding cloud-only remediation; they do not establish remediation routing or accessibility success.

Requirements:
- Installed-model evidence gates primary and override Ollama models; an unavailable tags probe does not falsely establish model absence.
- Quality-first cloud-only selection cannot dispatch legacy local calls on unavailable configuration, capacity or budget exhaustion. Legacy any-zone behavior remains compatible.
- Admission failures preserve measured queue wait and explicit not-dispatched evidence; optional AI failure is not corruption, a completed fix, a verified fix or a publication receipt.
- Assessment progress distinguishes queued, running, blocked and completed. A runner done callback with unfinished eligible documents cannot claim completion. Completion means saved assessment results, never full accessibility.
- Structural/readability assessment blocking remains separate from optional enrichment. Existing verification and matching artifact-digest receipts remain authoritative for fixing and publishing.

Validation: offline provider/clock/gate fixtures for unavailable models, failed cloud admission, exhausted budget, no local fallback, partial completion and finite timing. Record a repeatable offline timing benchmark; run scoped suites and required PR CI. Coordinate shared generation symbols with the quality task; leave handlers, store, review and Release ownership unchanged.

Offline benchmark (2026-09-15, Node v24.19.0, local machine): `node scripts/benchmark_assessment_progress.mjs` consumes 100,000 progress/view-line pairs across queued, running, blocked and done phases in each of seven trials. Median 5.891 ms; samples 15.450, 7.197, 7.094, 5.764, 5.882, 5.891, 5.869 ms. This measures presentation calculation only, not provider throughput, network performance or production capacity. Clock fixtures separately assert 250 ms capacity wait and 500 ms deadline exhaustion with zero dispatch.

Validation results: 55 scoped routing/generation/timing tests passed (one guarded PostgreSQL integration skip); 90 wider assessment/readability/recovery tests passed (one absent Office engine skip); 41 assessment UI tests passed; frontend production build passed. Matrix coverage, queue scaler, TODO coverage and fixture coverage guards passed. Quality task confirmed no generation symbol overlap before edits. Existing Quality-first no-local guard was already correct; regression coverage protects it. The missing-primary-model gap is reproduced independently and is not asserted to have caused the historical scan failures.
