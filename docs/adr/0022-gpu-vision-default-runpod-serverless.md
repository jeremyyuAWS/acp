# ADR 0022 — GPU vision as the default, via a scale-to-zero RunPod Serverless endpoint

Status: **Proposed** (2026-07-13) — **Stages 1–3 shipped (code)**; **Stage 4 blocked** on the serverless worker. Stage 1: the `RunPodServerlessVisionProvider` adapter + selection + CPU fallback (`c257111`). Stage 2: `deploy/gpu/serverless_up.sh`/`serverless_down.sh` provision + tear down the endpoint via the RunPod API. Stage 3: `deploy.sh` passes `RUNPOD_ENDPOINT_ID` + the `RUNPOD_API_KEY` secret + flips `ACP_VISION_PROVIDER` to serverless when `ACP_RUNPOD_ENDPOINT_ID` is supplied at deploy time (opt-in; a normal deploy is unchanged). **Stage 4 finding (2026-07-13):** endpoint creation + autoscale WORK (a `RTX-24GB`-pool endpoint went from throttled → 2 ready workers once the GPU pool list was broadened past the supply-constrained 24GB pools), but the vLLM worker's OpenAI-compatible route did not return — jobs sat `inQueue`/`inProgress` and both an image AND a text-only call hung (10 min, then 3 min), 0 `failed`. That points at the vLLM-worker OpenAI serving config (model-load vs. sync-route behaviour), not the ACP adapter — which is why the adapter's **CPU fallback keeps production safe regardless**. Endpoint torn down (cost). Next: debug via the RunPod worker *logs*, or use the console's validated vLLM quick-deploy for a VL model and pass its endpoint id to the deploy. The burst-pod path (`deploy/gpu/up.sh`, Ollama) remains the working GPU option meanwhile.
Date: 2026-07-13
Related: [ADR 0019](0019-ai-provider-gateway-and-governance.md) (the vision provider seam this adds an adapter to), [ADR 0016](0016-evidence-based-confidence.md) (honesty — provenance zone stays truthful; no fabricated cost), [ADR 0020](0020-discover-assess-phase-separation.md) (batch vision runs at Assess, the load this must serve)

## Context

The vision model is the difference between AI-assisted and AI-in-name-only remediation. Measured on the demo corpus (ADR 0019 notes; `scripts/vision_eval.py`): a **GPU** vision model (`qwen2.5vl:7b`) grounds ~0.9 of chart/diagram descriptions and reads chart values correctly, so a 1.1.1 finding **auto-applies a grounded alt** and never reaches a human. The **CPU** fallback (`moondream`, forced by the 8Gi ACA Consumption ceiling) grounds ~0.14 — most content images get no usable draft, so the reviewer authors from scratch.

So the customer wants the **GPU to be the default**, with **workers spun up on demand** and no standing cost.

Today it is not the default, for a concrete operational reason. The GPU is a **RunPod on-demand pod** (`deploy/gpu/up.sh`): a fresh pod id every time, a Cloudflare-proxied URL, terminated by an idle watchdog after ~15 min or by any crash. The app is pointed at it **at runtime** through the ADR 0019 endpoint override (Settings → AI endpoint, stored in the app DB). The deploy **default** is the always-available CPU Ollama (`acp-ollama.internal…`, `moondream`), because:

- **A pod URL is not a durable default.** Baking `OLLAMA_BASE_URL=https://{pod}…proxy.runpod.net` into the deploy would point production at a **dead endpoint** the moment that pod is reaped — all AI down, not degraded. The CPU floor is the safe default precisely because it is always up.
- **The runtime override does not survive a redeploy.** Every redeploy comes up on the env default (CPU moondream), so an operator must re-apply the GPU endpoint in Settings after each deploy — observed repeatedly this session. The override is a *demo* affordance, not a durable default.

The counter-pressures that must be respected:

1. **Never let AI fully go down.** Whatever becomes the default, the always-available CPU Ollama must remain the fallback floor, so a GPU cold-start timeout or a serverless outage degrades quality — it does not break remediation.
2. **No fabricated numbers (ADR 0016).** The provenance zone and per-call cost must stay real. A third-party GPU host is honestly `cloud` (🟡, bytes leave the network), not `local` (🟢).
3. **The assistant never handles the API key.** The RunPod key is provisioned by an admin as a container secret (secret-ref, ADR 0019 §6) and read at call time; it never enters the DB, a request, a log, a trace, or the browser.

## Decision

**Make the default vision path a RunPod *Serverless* endpoint** — a stable endpoint URL whose GPU workers auto-scale 0→N on demand and **scale to zero when idle** — wired as a new provider behind the ADR 0019 seam, with the CPU Ollama floor as the automatic fallback.

Serverless (not an on-demand pod) is the whole point: it gives the three properties a durable default needs that a pod cannot.

| Property | On-demand pod (today) | **RunPod Serverless (this ADR)** |
| --- | --- | --- |
| Endpoint URL | ephemeral (`{pod-id}` churns) | **stable** (`{endpoint-id}`, set once) |
| Survives redeploy | no (reverts to CPU) | **yes** (baked as deploy default) |
| Idle cost | full pod $/hr until reaped | **$0** (scales to zero) |
| On-demand workers | manual `up.sh` | **automatic** (queue-driven autoscale) |
| Failure mode | dead URL → AI down | cold-start / outage → **CPU fallback** |

### Architecture

1. **Serverless endpoint.** A RunPod Serverless endpoint runs an **OpenAI-compatible vLLM worker** serving `qwen2.5-vl`. It exposes `https://api.runpod.ai/v2/{endpoint_id}/openai/v1/chat/completions`, auth `Authorization: Bearer $RUNPOD_API_KEY`. Min workers = 0 (scale-to-zero), max workers = N (burst). Provisioned by ops (`deploy/gpu/serverless_up.sh`, RunPod API, key from `~/.zshrc`, never printed) or the RunPod console; the endpoint id is a non-secret config value.

2. **Adapter (`providers.RunPodServerlessVisionProvider`).** Slots beside `OllamaVisionProvider` / `AzureOpenAIVisionProvider`. Because the endpoint is OpenAI-compatible, `generate()` sends the same chat-completions image body the Azure adapter sends, to the serverless URL, with the Bearer key. `zone = "cloud"` (honest). `cost_usd` = GPU-seconds (from the response's `executionTime`) × the endpoint's per-second rate — a real measured cost, 0 when the rate is unknown (never invented). Never raises → `ok=False` on any failure.

3. **Selection + fallback (`active_vision_provider` / `ai._vision_generate`).** The `ai_vision_provider` selector gains `runpod_serverless`; the **deploy default** sets it (env → setting) so GPU is the default with no manual step. On an `ok=False` result (cold-start over the timeout, endpoint down), the gateway **falls back to the CPU Ollama floor** for that call, so a finding still gets *a* draft. The fallback is recorded in the ai_calls provenance row (which provider actually served the call), so the audit trail never claims GPU when CPU ran.

4. **Secret + config.** `RUNPOD_ENDPOINT_ID` (non-secret) + `RUNPOD_API_KEY` (secret-ref) provisioned on both `acp-app` and `acp-worker` (batch vision runs on the worker, ADR 0020). The deploy sets the vision selector to `runpod_serverless` **only when the endpoint id + key secret are both present**, else it stays on the CPU default — so a deploy without the serverless config is exactly today's keyless local build.

### Cold-start & latency

Scale-to-zero means the **first** request after idle cold-starts a worker (model load): ~10–30s for a 7B VLM, longer on a cold image pull. This is acceptable because vision runs at **Assess** (a batch, background job — ADR 0020), not in an interactive path, and the per-image budget already tolerates a 120s timeout. To trade a little cost for latency, `min_workers=1` keeps one warm; the default is 0 (no idle cost) per the customer's ask.

## Consequences

- **GPU is the default and survives redeploys** — the endpoint id is a stable deploy env value, so a redeploy comes up on GPU, not CPU. No more re-applying in Settings.
- **No idle cost** — workers scale to zero; the idle watchdog + manual teardown (`deploy/gpu/down.sh`) become unnecessary for the default path.
- **On-demand workers** — RunPod queues and autoscales; a burst of Assess images spins up multiple workers, then releases them.
- **Never fully down** — the CPU Ollama floor remains the automatic fallback; quality degrades on a serverless miss, remediation does not stop.
- **Privacy tradeoff, stated honestly** — RunPod is a third-party host, so the provenance badge is 🟡 **cloud** (bytes leave the network). A customer who requires 🟢 **in-network** vision needs the model on their own infra (Azure-native GPU, still quota-gated) — deferred, and the reason this ADR does not claim "private."
- **The runtime override still works** — Settings → AI endpoint can still repoint to a burst pod for a one-off; it just isn't needed for the steady state.

## Rollout

1. **Adapter + selection (code, no live endpoint):** `RunPodServerlessVisionProvider`, wire `runpod_serverless` into `active_vision_provider`, and the CPU fallback in `ai._vision_generate`. Unit-tested against a mocked serverless response. Behaviour unchanged until the endpoint is configured.
2. **Provision the endpoint:** `deploy/gpu/serverless_up.sh` (or console) → OpenAI-compatible vLLM worker on `qwen2.5-vl`, min=0; capture `RUNPOD_ENDPOINT_ID`.
3. **Deploy wiring:** pass `RUNPOD_ENDPOINT_ID` + the `RUNPOD_API_KEY` secret to `acp-app` + `acp-worker`; the deploy flips the vision selector to `runpod_serverless` when both are present.
4. **Verify live:** a real Assess run grounds charts on the serverless GPU; kill the endpoint and confirm the call falls back to CPU (degraded, not broken).
