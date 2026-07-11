# ADR 0019 — AI provider gateway + governance (local-first, quality-verified, fully auditable)

Status: Proposed
Date: 2026-07-11
Related: [ADR 0016](0016-evidence-based-confidence.md) (no fabricated numbers — the routing must obey it), [ADR 0102 prompt-version identity](../../docs) (prompt_hash provenance), [ADR 0006](0006-pii-sensitive-data.md) (data-leaving-network is a governance concern), [ADR 0018](0018-slide-page-rasterization-and-shape-geometry.md) (a sibling seam), movate-cli `BaseLLMProvider` (the adapter-behind-Protocol precedent this mirrors)

## Context

ACP's entire AI surface is a **single module, `api/ai.py`** — every caller (remediators, HITL suggest, digest) goes through `ai.describe_image_structured` / `ai.suggest_fix` / `ai.explain_finding` / `ai.compliance_digest`; nothing else touches a model. Today that module is **Ollama-only, keyless, local-only by design** ("No commercial-LLM SDK or API key is used anywhere"), and it already:

- **returns the model name** on every result (`{"alt", "model": OLLAMA_VISION_MODEL}`),
- **traces every call** through Langfuse with model + latency + ok (`_trace_ai`),
- **routes on a deterministic quality signal, not a confidence number** — `describe_image_structured` returns `grounded` (OCR read real text from the image): grounded → auto-apply; not grounded → a human proposal. That is already "validate the result, don't trust a self-reported score."

Enterprise buyers (legal, healthcare, government, finance) increasingly ask a governance checklist ACP is well-placed to answer and most competitors dodge: *What model generated this? Did my document leave my network? Can I force local-only? Which provider was used, and can I audit it? How much did it cost? Can I bring my own key?* ACP's local-first, honesty-first DNA is the right foundation to answer all of them — but the current module is single-provider and surfaces none of the provenance it already collects.

Constraints carried in:

1. **Honesty (ADR 0016).** Routing and display must not invent a confidence %. Model self-confidence is, at most, one weak input; the primary signals are deterministic validation and grounding. A displayed number must be a real measurement (cost, tokens, latency, a passed re-scan), never a fabricated score.
2. **Local-first, not local-only-forever.** Default keyless local Ollama stays the out-of-box experience (privacy, cost, offline). Cloud is opt-in, governed, and never the default.
3. **Secrets discipline.** A bring-your-own-key model means org-admin-entered API keys. They are secrets: stored as a secret *reference* (Key Vault / container secret), never plaintext in Postgres, never logged, never in a Langfuse trace or an audit row. The assistant never handles a key; the admin enters it in the product's own Settings UI.
4. **Provider-agnostic core (rules 6–7).** The rest of ACP must keep calling `ai.*` and stay unaware of which provider ran — the gateway preserves the existing function signatures.

## Decision

**Promote `api/ai.py` into an AI Gateway: a provider-abstracted, policy-routed, fully-audited single integration point. Same call sites, same signatures; behind them, interchangeable providers, a governance policy, and a provenance record.**

### 1. Provider adapter seam
A `VisionProvider` / `TextProvider` Protocol (mirroring movate-cli `BaseLLMProvider`, per rule 7):
`describe_image(bytes, prompt) -> {alt, model, provider, grounded?, input_tokens, output_tokens, cost_usd, latency_ms, privacy_zone}`.
Adapters: **Ollama** (default, `privacy_zone=local`, cost 0), **OpenAI**, **Anthropic**, **Gemini**, **Azure OpenAI** (`privacy_zone=tenant`), **AWS Bedrock**. Each adapter is a new impl behind the Protocol — no `if provider ==` branching leaks into callers. Cloud SDKs are **opt-in `pyproject.toml` extras** (rule 8), absent by default so the keyless local build stays slim.

### 2. Policy router (governed, not static)
An **execution policy** an org admin selects, evaluated by an orchestrator inside the gateway:
- **Local-first (default)** — try the local provider; keep it if it passes the *acceptance policy* (below); escalate only if the policy permits AND local failed acceptance.
- **Offline-only** — a **hard guarantee**: any non-`local` adapter is unreachable in this mode; no key, no config, no accident sends bytes off-box.
- **Highest-quality** — go straight to the top-priority cloud provider.
- **Enterprise-governance** — an allowlist (e.g. Azure-OpenAI-only; never OpenAI, never Anthropic).
- **Cost-cap** — stop escalating once a daily spend ceiling is hit; fall back to local + human review.
Provider *priority* is an ordered list (the "drag-and-drop" UI). Per-rule preference is allowed (`1.1.1` charts → a strong vision model; `2.4.4` link text → local text model) as an override map, defaulting to the global order.

### 3. Acceptance policy — validation-gated, never confidence-alone
The escalation trigger combines real signals (explicitly NOT a lone self-reported %):
- **deterministic validation** — does the result satisfy the WCAG check on re-scan? (the existing `verify_residual_scs` gate);
- **grounding** — is the description OCR-anchored (the existing `grounded` flag) vs a blind guess;
- **image complexity** — logo/icon vs chart/dense infographic (a cheap heuristic on size + OCR density);
- **optional model agreement** — for high-value docs, two providers must concur;
- **customer policy** — offline-only / allowlist / cost-cap gates everything above.
Model self-confidence, if a provider even returns one, is one weak input, never the gate. This keeps ADR 0016 intact and follows the caution that VLM confidence is poorly calibrated.

### 4. Provenance + audit (the certification-grade record)
A new append-only `ai_calls` table (additive, rule 5): `scan_id, file, rule_id, provider, model, privacy_zone, prompt_version (ADR 0102 hash), input_tokens, output_tokens, cost_usd, latency_ms, escalated_from, decision_reason, ts`. Most fields already exist in the Langfuse span — this persists them as a first-class, queryable, certification-embeddable record. The HITL card and the certification report read from it: *"Generated by llava:13b (local Ollama) · 🟢 local · prompt v7 · 1.8s · $0"*, or on an escalation, the transparent pipeline *"Ollama attempted → did not pass acceptance (complex chart, ungrounded) → escalated to Azure OpenAI (tenant) → passed · $0.03"*.

### 5. Privacy enforcement + badge
Every result carries `privacy_zone`; the card shows it as a badge (🟢 local / 🟡 cloud(provider) / 🔵 tenant(Azure)) and, when cloud, the `decision_reason` ("local below acceptance; complex financial chart; cloud escalation enabled"). Offline-only makes the badge always 🟢 by construction.

### 6. Keys as secrets
A Settings → **AI Providers** page (admin-gated, reusing the existing `PUT /settings` admin gate): per provider, enter the key, pick a model, enable/disable, see connection status. The key is written to a **secret store** (Key Vault ref / container secret), the DB holds only a reference + non-secret config; the key is **redacted from every trace, log, and audit row**. Ollama needs no key (URL + model only).

### 7. Cost tracking
A per-model price table × the token counts adapters return → per-provider daily/monthly usage (Ollama = $0). Surfaced as a small "AI usage" panel and rolled into the governance story ("2,443 local requests $0 · 17 GPT-4.1 $0.89").

## Consequences

- **Enterprise governance becomes a differentiator**, answered concretely: model shown, network boundary enforced and displayed, local-only guaranteed, provider audited, cost tracked, BYO-key supported — the checklist most competitors avoid.
- **Contained blast radius.** The seam already exists: the change is `api/ai.py` (orchestrator + Protocol), N provider modules, a settings page, one additive table, and card/report rendering of provenance. Callers are untouched (they already call `ai.*`).
- **Local-first preserved.** With no keys and the default policy, ACP behaves exactly as today — keyless, local, $0 — and the badge reads 🟢. Cloud is inert until an admin opts in.
- **Honesty preserved and reinforced.** Routing is validation-gated; nothing displays a fabricated confidence %. The governance rule and the ADR 0016 rule are the same rule.
- **Security surface = the keys.** The one genuinely sensitive addition; mitigated by secret-ref storage, redaction everywhere, admin-gating, and the assistant never touching a key.
- **Net-new value even at Phase 0** (below) with no new deps: the model name + 🟢 privacy badge + provenance record are all assembled from data `ai.py` already produces.

## Phasing

- **Phase 0 (no new deps, shippable now):** persist + surface what `ai.py` already returns — model name, latency, prompt version — as an `ai_calls` provenance row and a card line "Generated by {model} · 🟢 Local only". Immediately answers "don't hide the model" and "did it leave my network" (no, it's local) for the current all-local product.
- **Phase 1:** the `VisionProvider` Protocol + one cloud adapter (Azure OpenAI — the enterprise-safe first choice, `privacy_zone=tenant`) behind the acceptance policy + the Settings page + secret storage + the escalation trace. Proves the governance loop end-to-end.
- **Phase 2:** remaining adapters (OpenAI, Anthropic, Gemini, Bedrock), per-rule preference, drag-and-drop priority, the cost dashboard, optional model-agreement for high-value docs.

## Non-goals

- Building or fine-tuning a model — ACP orchestrates providers, it doesn't train.
- Routing on model self-confidence alone (ADR 0016 + the calibration caution).
- Making cloud the default, or ever bypassing offline-only.
- Storing API keys in Postgres/plaintext, logging them, or putting them in traces.
- The assistant entering, reading, or handling any key — the admin does, in the product UI.
- Replacing the enum confidence with a number anywhere (geometry and cost are precise because measured; confidence stays an enum because it isn't).
