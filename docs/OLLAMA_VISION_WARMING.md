# Ollama vision residency and runtime benchmark

The existing app startup daemon keeps the text model warm every ten minutes. It does not warm the vision model. This change adds a one-time, bounded GPU-container startup preload for the existing baked `llava:13b`, and requests finite residency after each actual Ollama vision call.

No model, GPU profile, replica count, worker capacity, or cloud budget changes. The model bake precedes the new residency environment layer, so rebuilding the image can reuse its existing model-pull cache. The authenticated ingress gate and loopback Ollama binding remain unchanged.

## Runtime controls

- `ACP_OLLAMA_KEEP_ALIVE`: finite per-request residency, default `30m`. Invalid or indefinite values fall back to `30m`; explicit `0` requests unloading.
- `ACP_OLLAMA_WARM_MODELS`: comma-separated, already-installed GPU model names; default `llava:13b`. Missing models are reported, never pulled.
- `ACP_OLLAMA_WARM_TIMEOUT`: one total startup-preload deadline, default 120 seconds, capped at 300.
- Existing `ACP_OLLAMA_KEEPALIVE=0`: also disables startup preload.

The GPU entrypoint starts the authenticated gate while a background preload sends an empty-prompt generation request to its loopback Ollama process. A successful `done` response is a recorded preload result. Gate reachability or a populated model inventory alone does not prove models are resident or that inference succeeds. A failed preload does not remove the gate or trigger model downloads. After an idle interval longer than residency, a later real request can still incur model loading.

Every real vision call still has its original total request timeout. There is no additional in-request warmup or extra retry. Existing failure reason codes, temperature and token limit remain unchanged.

## Measured timing

Ollama provider results carry a content-free `timing` object when the server returns durations: `model_load_ms`, `prompt_eval_ms`, `inference_ms`, `total_ms`, and observed `output_tokens_per_second`. Missing, invalid or negative durations are omitted. Loading and token inference remain separate; elapsed time is not automatically labelled a cold start.

These fields come from the [Ollama generate API](https://docs.ollama.com/api/generate). The [Ollama FAQ](https://docs.ollama.com/faq) explains residency and checking whether a loaded model uses GPU or CPU.

## Repeatable benchmark

The default command performs zero network calls:

```sh
python scripts/benchmark_ollama_vision.py --output /tmp/ollama-replay.json
```

It replays a labelled synthetic fixture. The checked-in result under `docs/evidence/ollama-runtime-2026-09-12/synthetic-replay.json` proves arithmetic and report structure, not live performance.

For an explicitly approved measurement against an already-running local server:

```sh
python scripts/benchmark_ollama_vision.py --live-local http://127.0.0.1:11434 --model llava:13b --repetitions 3 --timeout 120 --output /tmp/ollama-local.json
```

Live mode rejects external endpoints, uses only the embedded valid synthetic PNG, caps repetitions at ten, and applies one total deadline. It never restarts/unloads a model, pulls models, contacts paid cloud providers, or sends customer documents. The first observation is not asserted to be a forced cold start. Reports record completion, empty-response and truncation checks, but do not infer remediation quality or an accessibility pass.

No live inference, model restart, cloud call, or GPU configuration mutation was performed for this implementation. Root deployment validation must verify actual container preload logs and measured timings before claiming a live latency improvement.
