# CPU vs GPU vision models for document remediation — findings

For a spreadsheet chart or a diagram, the **vision model is the line between AI-assisted remediation
and AI-in-name-only.** Everything else ACP fixes — language, titles, contrast, headers — is
deterministic. The images are the one place where model quality decides the outcome.

The measured task is alt text for content images (**WCAG 1.1.1**). A description only counts when it
is *grounded* — anchored in what the image actually shows, usable as-is rather than a rewrite. That
single property is what lets ACP **auto-apply** a fix instead of handing a blank box to a person.

Sources: `scripts/vision_eval.py` (bake-off) · `remediate_e2e.py` (end-to-end) · this session's live
qwen2.5-VL runs. Related: [ADR 0016](adr/0016-evidence-based-confidence.md) (honest confidence),
[ADR 0019](adr/0019-ai-provider-gateway-and-governance.md) (provider gateway),
[ADR 0022](adr/0022-gpu-vision-default-runpod-serverless.md) (GPU as default).

## The one-number story

| Metric | CPU (moondream) | GPU (qwen2.5-VL) |
| --- | --- | --- |
| Content images that get a usable, grounded draft | **14%** | **91%** (~6.5× more) |
| WCAG criteria auto-cleared end-to-end (showcase deck) | **2 / 8** — 1.1.1 still fails | **3 / 8** — 1.1.1 fully cleared |
| 1.1.1 outcome | images punted to a human | alt auto-written + re-scan-verified, 0 deferred |

## Model bake-off — 7-image showcase corpus, avg of 3 runs

Run through the app's real `describe_image_structured` path. "Grounded pass" = anchored in the image's
actual content (chart type, subject, trend), not a guess.

| Model | Tier | Grounded pass | Latency | Verdict |
| --- | --- | --- | --- | --- |
| `moondream` | CPU · 1.7 GB | **0.14** | ~1.4 s | The default floor. Charts → nothing back, or it echoes the garbled title. |
| `bakllava` | GPU | 0.43 | fast | Fast, weak — generic descriptions. |
| `llava:7b` | GPU | 0.76 | ~3.3 s | Worse *and* slower than 13b — no reason to run it. |
| `llava:13b` | GPU | 0.91 | ~2 s | Names chart type, flowchart steps, trends. **But invents bar values** — confidently wrong figures. |
| **`qwen2.5-VL:7b`** *(chosen · vision)* | GPU | ~0.90 | ~2–6 s | **Reads the actual chart numbers** ($15.1M, 658 FTE) where llava hallucinated. Grounded and accurate. |
| **`minicpm-v`** *(consensus validator)* | GPU | ≈0.9 | ~2 s | Comparable strength — and the **only** model that *refused to fabricate* on a blank placeholder. Second opinion. |
| `llama3.2-vision:11b` | GPU | 0.00 | — | Returns nothing usable *through this path* — a call-format issue to fix, not a verdict on the model. |

**In the review queue:** on CPU, ~86% of content images (charts, diagrams, screenshots) come back with
no usable draft — the reviewer authors alt text from scratch. On GPU, ~91% arrive with a correct,
grounded draft — a one-click approve, or silently auto-applied when the description is anchored in the
image's own text. Same pipeline; the model is the only variable.

## End-to-end remediation — real scan → remediate → re-scan

The showcase deck through the full pipeline, swapping only the vision model.

| | CPU · moondream (🟢 in-network) | GPU · qwen2.5-VL (🟡 cloud) |
| --- | --- | --- |
| WCAG criteria auto-cleared | 2 / 8 | 3 / 8 |
| 1.1.1 | still failing — images punted to a human | fully cleared — alt auto-written + re-scan-verified, 0 deferred |
| Cost | $0 marginal, always on | ~$0.45/hr, on-demand (RunPod burst pod) |

## Where the GPU can run — cost, latency, privacy

| Path | Model | Cost | Latency | Data | Status |
| --- | --- | --- | --- | --- | --- |
| CPU · ACA (8 GiB cap) | moondream | ~$0 · always-on | ~1.4 s | 🟢 in-network | Default floor. A real 7B VLM OOMs the 8 GiB cap — the downgrade is forced. |
| RunPod burst pod | qwen2.5-VL | ~$0.45–0.47/hr | ~2–6 s | 🟡 cloud | The working GPU path today. On-demand; ~40 s cold-start, fast after. |
| RunPod serverless | qwen2.5-VL · vLLM | scale-to-zero | — | 🟡 cloud | Endpoint scales 0→N cleanly, but the vLLM-VL worker's serving hung. Needs worker-log debug or an Ollama worker. |
| Azure-native GPU | any VLM | scale-to-zero T4 | — | 🟢 in-network | The private path. GPU quota has never been granted — gated on Azure approval. |

## The honesty guardrail (ADR 0016) — where even the GPU stops

No model reliably maps exact bar **values** to their categories — llava invents them, qwen is much
better but not perfect. So the GPU's real win is **structure + subject + grounding**, not figures. The
prompt forbids stating specific chart numbers; those route to a human. Every alt text records its
provenance — which model, 🟢/🟡 zone, and whether it was *grounded* or a visual guess — and never a
fabricated confidence %.

## Bottom line

CPU keeps AI switched on for nearly free, but produces almost no usable chart descriptions — it's AI
in name. A GPU VLM (`qwen2.5-VL`, cross-checked by `minicpm-v`) is what turns WCAG 1.1.1 from "a person
writes it" into "auto-applied and verified." The price is ~$0.45/hr on-demand and a 🟡-cloud data trade
— until Azure GPU quota lands for a 🟢 in-network model. The CPU floor stays wired as the
always-available fallback, so AI never goes fully down.
