# ADR 0019 — AI provider gateway + governance (local-first, quality-verified, fully auditable)

Status: Accepted (2026-07-11), implementation reconciled 2026-09-07. **Phases 0–2
shipped:** model/zone/cost provenance, evidence-based trust states, the append-only
`ai_calls` ledger, secret-reference configuration, owner-governed routing and budgets, and
Settings → **AI Governance**. `api/providers.py` now implements the local Ollama vision
floor plus six governed cloud vision adapters — Azure OpenAI, OpenAI, Anthropic, Gemini,
Bedrock and Hugging Face — and a separate RunPod Serverless GPU adapter. The text path can
use Claude through Anthropic's Messages API for governed remediation pilots. Cloud use remains
opt-in: without an enabled provider and a resolved secret, ACP uses the keyless local floor;
an explicit stored administrator choice overrides the deployment environment. Offline/local-only
policy remains the hard boundary described below. **Still prospective:** the complete Phase 3
packaging (all three modes as one first-class selector, full capability-routing editor and
model-agreement controls). The sections below retain the original decision language; the Phasing
section distinguishes shipped implementation from that remaining product surface.
Date: 2026-07-11
Related: [ADR 0016](0016-evidence-based-confidence.md) (no fabricated numbers — the routing must obey it), [ADR 0102 prompt-version identity](../../docs) (prompt_hash provenance), [ADR 0006](0006-pii-detection-dimension.md) (data-leaving-network is a governance concern), [ADR 0018](0018-slide-page-rasterization-and-shape-geometry.md) (a sibling seam), movate-cli `BaseLLMProvider` (the adapter-behind-Protocol precedent this mirrors)

## Context

ACP's callers still enter through the **single gateway module, `api/ai.py`** — remediators,
HITL suggestions and digests do not choose vendors themselves. Transport adapters live behind
that gateway in `api/providers.py`. The original implementation was Ollama-only; the shipped
implementation also supports the six governed cloud vision adapters named in the status above,
RunPod Serverless vision, and opt-in Claude text generation. The default configuration remains
keyless and local-only, and it:

- **returns the model name** on every result (`{"alt", "model": OLLAMA_VISION_MODEL}`),
- **traces every call** through Langfuse with model + latency + ok (`_trace_ai`),
- **routes on a deterministic quality signal, not a confidence number** — `describe_image_structured` returns `grounded` (OCR read real text from the image): grounded → auto-apply; not grounded → a human proposal. That is already "validate the result, don't trust a self-reported score."

Enterprise buyers (legal, healthcare, government, finance) increasingly ask a governance checklist ACP is well-placed to answer and most competitors dodge: *What model generated this? Did my document leave my network? Can I force local-only? Which provider was used, and can I audit it? How much did it cost? Can I bring my own key?* ACP's local-first, honesty-first DNA is the foundation for the now-shipped multi-provider gateway and its recorded provenance.

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

## 8. Enterprise packaging — deployment modes, capability routing, residency (2026-07-13 governance reframe)

The gateway (§1–§7) is the mechanism; this section is the **enterprise-facing packaging** of it. The
insight: don't sell "we support OpenAI" — sell *AI governance*. Reposition the whole surface from
**Settings → AI Governance**, and ask the buyer "what are your organization's AI governance
requirements?" rather than "which model do you want?", then configure ACP around the answer. Most of
this reuses shipped primitives (the policy router §2, credential_source §6, provenance §4); the new
material is the framing + three additive dimensions.

### 8.1 Three deployment modes (the customer-facing wrapper over the §2 execution policies)
A single top-level choice, each a preset over the existing policy router + credential_source:

| Mode | Providers | Key owner | Who pays the provider | `processing_zone` | Target |
|---|---|---|---|---|---|
| 🟢 **Local-Only** (default) | Ollama (qwen2.5-vl, minicpm-v, llama) | none | n/a ($0) | `local` | gov / healthcare / air-gapped |
| 🔵 **Customer-Cloud (BYOAI)** | customer's OpenAI / Anthropic / Azure OpenAI / Gemini / Bedrock | **customer** (`customer_managed`) | **customer, directly** | `customer_cloud` | large enterprise |
| 🟣 **ACP-Managed** | ACP-provisioned provider + credits/caps | ACP (`acp_managed`) | ACP (metered) | `acp_managed_cloud` | trials / SMB / demos |

**Why BYOAI matters strategically (the reframe's core):** large enterprises already hold Azure
OpenAI / OpenAI-Enterprise / Anthropic-Enterprise / Bedrock contracts and frequently *cannot* run a
vendor's key — procurement says "use ours." Supporting `customer_managed` credentials makes ACP pass
that gate: the customer owns the provider relationship, controls its data-retention policy, and pays
the provider directly — **ACP never resells AI usage.** This is a procurement-unblocker, not a feature.

### 8.2 Per-capability routing (a coarser, more enterprise grain than §2's per-rule preference)
Route by **capability**, not one global model — each capability maps to a provider, and §2's per-rule
map is the finer override beneath it:

```
OCR        → Azure Vision       Vision     → Ollama qwen2.5-vl
Reasoning  → GPT-4.1            Writing    → Claude
```

Capability pipelines compose the acceptance policy (§3): e.g. `Alt-text → qwen → consensus(minicpm-v)
→ escalate → Claude`, while `Language detection → deterministic` (no model at all). This makes ACP an
**orchestrator**, not a single-model app.

### 8.3 Data residency (a NEW governance dimension — additive to the policy)
A per-provider / per-mode **region constraint**: `US | EU | customer-managed`. A cloud provider is
only reachable if its region satisfies the org's residency policy; the chosen region is recorded in
the §4 `ai_calls` provenance row (`region`). Critical for EU/GDPR and public-sector buyers. Local-Only
trivially satisfies any residency ($0, on-box).

### 8.4 The AI Governance surface (rename + budget UX)
`Settings → AI Providers` becomes **AI Governance** with tabs: **Providers · Policies · Privacy ·
Escalation · Routing · Budgets · Audit** — provider status cards (Connected / Configured / Not
configured, never the key), drag-drop **provider priority**, the §8.1 mode selector + §8.2 capability
routing, and a **Budget** panel: monthly ceiling + live spend + escalation count + average cost
(`$250 budget · $81 spent · 47 escalations · $0.011 avg`), driving the §2 cost-cap policy from real
`ai_cost_rollup` numbers ($0 on the keyless local build — no fabricated figure, ADR 0016).

### 8.5 Reviewer-behavior signal feeds routing maturity (ties to the automation-mode model)
The provenance row (§4) plus HITL telemetry (`hitl_events.edited`) already capture **AI acceptance /
edit rate / rejection** per rule. Low edit-distance on a criterion's proposals is the evidence that it
is ready to migrate Human-Assisted → AI-Assisted → (grounded) Automatic — the same evidence-first
progression as the criterion automation-mode model. Governance and the automation maturity funnel are
the two halves of one story: *which criterion, run by which provider, under which policy, with what
provenance.*

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
- **Phase 2 — shipped:** OpenAI, Anthropic, Gemini, Bedrock and Hugging Face joined Azure
  OpenAI behind the governed vision selector; RunPod Serverless is the separately configured GPU
  route. The cost dashboard, provider/model/zone evidence, per-rule governance and guarded Claude
  text pilots are also live. An administrator's stored provider choice takes precedence over an
  environment default, so a credential alone cannot opt the tenant into cloud processing.
- **Phase 3 (§8 enterprise packaging) — partial:** Settings is now **AI Governance**, with
  owner-only providers, policy, privacy/region, routing, budget, audit and measured-quality
  controls. The complete three-mode selector, general capability-routing editor and optional
  model-agreement controls remain prospective; do not read their detailed design above as a claim
  that every control is already mounted.

## Non-goals

- Building or fine-tuning a model — ACP orchestrates providers, it doesn't train.
- Routing on model self-confidence alone (ADR 0016 + the calibration caution).
- Making cloud the default, or ever bypassing offline-only.
- Storing API keys in Postgres/plaintext, logging them, or putting them in traces.
- The assistant entering, reading, or handling any key — the admin does, in the product UI.
- Replacing the enum confidence with a number anywhere (geometry and cost are precise because measured; confidence stays an enum because it isn't).
