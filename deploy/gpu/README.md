# Burst GPU for vision drafting (llava:13b)

> ⚠️ **DEPRECATED — RunPod is dormant.** This whole flow (`up.sh`, `pull_models.sh`, `down.sh`,
> `idle_watchdog.sh`) targets a RunPod pod that is no longer used. The GPU vision lane now runs on
> **Azure Container Apps** — see [`docs/runbooks/gpu-eastus-colocation.md`](../../docs/runbooks/gpu-eastus-colocation.md)
> and ADR 0027/0039. **Do not run these scripts**, and do not cite `pull_models.sh` for the deployed
> model set — the authoritative source is the live `/config` `ai` block. The scripts are kept only as
> historical reference pending a deliberate RunPod decommission (which is coupled to rotating the
> exposed `RUNPOD_API_KEY` — do those together, not piecemeal). The steps below are the old RunPod
> procedure, retained for that decommission.

The platform runs keyless local Ollama (CPU `moondream`) by default. For heavy batches —
estate onboarding, big review pushes — attach a burst GPU for ~$0.44/hr and 6.5× more
usable alt-text drafts (measured, 2026-07-11):

    bash deploy/gpu/up.sh                                   # RunPod 4090, prints POD_ID + proxy URL
    bash deploy/gpu/pull_models.sh                          # llava:13b + llama3.2 (~5 min)
    nohup deploy/gpu/idle_watchdog.sh >/tmp/gpu_watchdog.log 2>&1 &   # auto-terminate after ~15 min idle

Then switch the platform to it **at runtime — no restart, running scans undisturbed**:
Settings → AI endpoint → paste the proxy URL, vision model `llava:13b` → Apply.
(Or `PUT /settings {"ai_base_url": "...", "ai_vision_model": "llava:13b"}` as admin.)
Every replica follows within ~30s; the switch is audited and the 🟢/🟡 provenance badge
follows the endpoint truthfully. To detach: clear both fields (empty = deploy default) —
the watchdog then reaps the idle pod, or run `deploy/gpu/down.sh` immediately.

The RUNPOD_API_KEY is read from ~/.zshrc by the scripts and never printed or committed.
