# Splitting the worker off the API container (#113)

> Production topology (2026-09-01): the generic `acp-worker` has been retired. Production runs
> `acp-discovery`, `acp-assess`, and `acp-remediate`, each restricted by `ACP_WORKER_ROLE`, while
> `acp-app` runs with `ACP_WORKERS=0`. The generic topology below remains relevant to local and
> staging deployments only. Production configuration changes must include all three stage workers.

**Why.** A UI/API deploy swaps the API container. When the worker pool runs *inside* that
container, the swap restarts running scans — the incident of 2026-07-11 (a scan wedged
mid-swap). The self-heal + sweeper-finalize + Stop button landed since make this survivable,
but the real fix is to stop the API deploy from touching the workers at all.

**The split is now a deploy-config change, not a code change.** `api/worker_main.py` runs the
durable pool + sweeper + scheduler with no HTTP server, reusing `core.start_workers` /
`stop_workers` (same graceful SIGTERM drain as the API container). Nothing else changed:
`app.py` still starts the pool in-process when `ACP_WORKERS>0`, so the single-container deploy
is byte-for-byte as today until you flip the config below.

## To split (one daylight deploy window)

1. **Add a second Container App** (or a second container in the same app) from the *same image*,
   with the command overridden to run the worker entrypoint:

       command: ["python", "worker_main.py"]      # working dir already /app/api in the image

   Give it the same env/secrets as the API container (`DATABASE_URL`, `ACP_BLOB_ACCOUNT`,
   `OLLAMA_BASE_URL`, Langfuse, Google ADC, etc.) and `ACP_WORKERS=4` (or size to load).
   `minReplicas: 1` — the pool must always be draining the queue.

2. **Turn the API container into API-only:** set `ACP_WORKERS=0` on the API app. It keeps
   serving HTTP and (harmlessly) still runs the sweeper thread; with 0 workers it claims no
   jobs. Deploys of the API container now never touch a running scan.

3. **Verify:** start a scan, deploy the API container mid-scan — the worker container keeps
   draining the queue, the scan finishes, and the source-bytes cache + HITL queue fill as
   normal. (Pre-split, this restarted the scan; that's the whole point.)

## Rollback

Set `ACP_WORKERS>0` on the API container again and scale the worker container to 0 — the pool
returns to the API process with zero code change. Fully reversible.

## Scaling / burst-GPU note

The worker container is also the natural home for the GPU-worker profile (KEDA scale-to-zero
on queue depth) once you want auto-burst — see `deploy/gpu/README.md`. That's a follow-on, not
part of this split.
