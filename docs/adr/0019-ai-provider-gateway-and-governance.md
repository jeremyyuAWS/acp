# ADR 0019 — AI provider gateway + governance (local-first, quality-verified, fully auditable)

Status: Accepted (2026-07-11). **Phase 0 shipped** (model name + 🟢/🟡 zone badge + `ai_calls` provenance row + #129 audit-trail panel). **§3a + §3b shipped** (2026-07-11): the three verifiable trust axes — Grounding / Validation / Review-requirement, each an evidence-based enum with the §3a vocabulary — now render on the review card in place of a confidence label (`reviewCard.trustStates`/`reviewRequirement`), and `ai.build_envelope()` assembles the normalized `{result, provenance, trust}` shape (pure, non-breaking — callers keep reading `result`). **§4 + §7 governance surfacing shipped** (2026-07-11): `store.ai_cost_rollup` (optionally scoped to a `scan_id`) drives a per-window governance panel in Settings (`GET /ai/costs`) and a per-scan **AI governance & provenance** block embedded in the certification report (`report._ai_governance_section`) — real counts / network-boundary / measured cost, $0 for the keyless local build, no fabricated score (ADR 0016). REMAINING (Phase 1, gated on secret-store work): the `VisionProvider` Protocol + Azure OpenAI adapter + Settings→AI-Providers page + secret-ref storage + escalation trace. The assistant never handles a key — the admin enters it in the product UI.
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

### 3a. Verifiable trust states — the display model that replaces "confidence"
The card and audit **drop the numeric/enum confidence *label* in the AI context** and show three concrete, evidence-based state axes instead (more useful than a score, and none of them a fabricated number):
- **Grounding** — `grounded_in_ocr` | `grounded_in_document_text` | `grounded_in_chart_labels` | `no_reliable_anchor` | `visual_interpretation_required`. (ACP already computes the grounded/ungrounded split in `describe_image_structured`; this names the source.)
- **Validation** — `deterministic_checks_passed` | `re_scan_passed` | `document_property_confirmed` | `validator_still_failing` | `not_yet_written`. (From the existing `verify_residual_scs` + `validated`/`applied` flags.)
- **Review requirement** — `safe_to_auto_apply` | `human_wording_review` | `manual_remediation` | `insufficient_evidence` | `provider_escalation_recommended`. (From track + subjectivity + grounding.)

ADR 0016's enum confidence is *subsumed* by these — they say the same "how much to trust this" honestly, but specifically and checkably, rather than as one opaque level. No percentage, ever.

### 3b. Normalized metadata envelope
`api/ai.py` functions return a normalized envelope so existing callers keep reading `result` unchanged while the UI + audit consume the rest (surfacing problem, not a rewrite):
```python
{
  "result": {...},                      # what callers already consume (alt text, suggestion, …)
  "provenance": {"provider", "model", "processing_zone",   # local | customer_cloud | acp_managed_cloud
                 "latency_ms", "cost_usd", "trace_id", "prompt_version"},
  "trust": {"grounded": bool, "grounding_sources": ["ocr_text", "chart_labels"],
            "validation_status": "...", "review_requirement": "..."},
}
```
Most `provenance` fields already flow through `_trace_ai`/Langfuse; this standardizes them on the return path so they persist per-finding and reach the card + certification without a new trace lookup.

### 3c. Explicit escalation path (when a cloud provider runs)
The card shows the actual numbered path, never a bare "OpenAI · 94%":
> 1. Ollama attempted → no grounded description
> 2. Escalated to OpenAI → reason: complex chart, cloud fallback permitted
> 3. Deterministic validation passed
The reviewer sees *what happened and why* — the escalation is transparent, not hidden and not dressed up as a score.

### 4. Provenance + audit (the certification-grade record)
A new append-only `ai_calls` table (additive, rule 5): `scan_id, file, rule_id, provider, model, privacy_zone, prompt_version (ADR 0102 hash), input_tokens, output_tokens, cost_usd, latency_ms, escalated_from, decision_reason, ts`. Most fields already exist in the Langfuse span — this persists them as a first-class, queryable, certification-embeddable record. The HITL card and the certification report read from it: *"Generated by llava:13b (local Ollama) · 🟢 local · prompt v7 · 1.8s · $0"*, or on an escalation, the transparent pipeline *"Ollama attempted → did not pass acceptance (complex chart, ungrounded) → escalated to Azure OpenAI (tenant) → passed · $0.03"*.

### 5. Privacy enforcement + badge
Every result carries `privacy_zone`; the card shows it as a badge (🟢 local / 🟡 cloud(provider) / 🔵 tenant(Azure)) and, when cloud, the `decision_reason` ("local below acceptance; complex financial chart; cloud escalation enabled"). Offline-only makes the badge always 🟢 by construction.

### 6. Keys as secrets, with enterprise credential controls
A Settings → **AI Providers** page (admin-gated, reusing the existing `PUT /settings` admin gate): per provider — Ollama endpoint + local model; optional OpenAI / Anthropic keys; Azure OpenAI endpoint + deployment + key; enable/disable; processing policy; fallback order; cloud permission; cost ceiling; a connectivity test; and last-successful-use. The key is written to a **secret store** (Key Vault ref / container secret / the deployment's secret manager), the DB holds only a reference + non-secret config; the key is **redacted from every trace, log, and audit row**, and **never returned to the browser after submission** (the field shows a set/not-set state, never the value). Ollama needs no key (URL + model only).

Each provider surfaces its **credential source** so an enterprise admin knows who owns the secret: `acp_managed` | `customer_managed` | `environment_managed` | `not_configured`. This is the difference between "ACP is paying/using its own key" and "this is your key in your vault" — a question enterprise procurement always asks.

### 7. Cost tracking
A per-model price table × the token counts adapters return → per-provider daily/monthly usage (Ollama = $0). Surfaced as a small "AI usage" panel and rolled into the governance story ("2,443 local requests $0 · 17 GPT-4.1 $0.89").

## Consequences

- **Enterprise governance becomes a differentiator**, answered concretely: model shown, network boundary enforced and displayed, local-only guaranteed, provider audited, cost tracked, BYO-key supported — the checklist most competitors avoid. The positioning sharpens from "local-first AI" to: **ACP uses evidence-based AI governance — it does not fabricate confidence scores; every remediation is routed on grounding, deterministic validation, content complexity, and customer policy, and every provider decision is traceable.** That is defensible against products that show a polished but meaningless AI confidence number.
- **This is productizing existing strengths, not new architecture.** The gateway seam (`api/ai.py`), provenance tracing (`_trace_ai`), grounding-based routing (`grounded`), and the no-fabricated-number philosophy (ADR 0016) already exist. The work is to normalize the metadata envelope, persist provenance per finding, surface the trust states + processing zone + real cost on the card, and carry them into certification — a surfacing problem, mostly.
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
