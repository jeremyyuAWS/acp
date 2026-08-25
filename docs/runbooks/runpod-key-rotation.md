# Runbook — Rotate the RunPod API key (R2 / R3)

**Status:** action pending. The `runpod-api-key` Azure secret is empty on both `acp-app` and
`acp-worker`, causing `serverless_vision_provider()` to return `None` and vision to silently fall
back to the local CPU floor (R2). The key was also exposed in an ops chat and must be revoked (R3).
Both fixes happen in one pass here.

**Endpoint in use:** `er7oqd0gq6ulsb` (verified 2026-08-14 on `acp-app`).

---

## Step 1 — Revoke and reissue the key (RunPod console, ~2 min)

1. Sign in to [app.runpod.io](https://app.runpod.io) → **Settings** → **API Keys**.
2. Find the key that was shared in chat. Revoke it.
3. Click **+ API Key** → give it a name like `acp-prod-2026-08` → **Create**.
4. Copy the new key — it is shown exactly once.

---

## Step 2 — Update the Azure Container Apps secrets (your machine, ~3 min)

Run from the repo root with `az login` active (or CI credentials in scope):

```bash
RUNPOD_ENDPOINT_ID=er7oqd0gq6ulsb \
RUNPOD_API_KEY=<paste-new-key-here> \
bash deploy/public/set_integration_env.sh
```

The script will:
- Set the `runpod-api-key` secret on both `acp-app` and `acp-worker`.
- Set env vars `ACP_VISION_PROVIDER=runpod_serverless`, `RUNPOD_ENDPOINT_ID`, `RUNPOD_API_KEY=secretref:runpod-api-key`, `RUNPOD_VISION_MODEL` on both apps.
- Refuse if the worker can't be updated (keeps the pair in sync — see script header).

The script is idempotent. Langfuse and SharePoint sections prompt for their own keys if not exported;
press Enter to skip those if you only want the RunPod update.

---

## Step 3 — Update `~/.zshrc` (your machine, ~1 min)

Replace the old key in `~/.zshrc`:

```
export RUNPOD_API_KEY="<new-key>"
```

Then `source ~/.zshrc` (or open a new shell). This keeps the burst-pod scripts
(`deploy/gpu/up.sh`, `serverless_up.sh`, `serverless_down.sh`) working.

---

## Step 4 — Verify (live app, ~5 min)

1. Open the live app, sign in, trigger a scan that contains an image-heavy document with a missing
   alt-text criterion (1.1.1).
2. Open **Settings → AI** and confirm **AI endpoint** shows the RunPod serverless endpoint, not
   the local Ollama default.
3. After drafting, open **Admin → AI cost** (or the Langfuse trace if wired): the processing
   zone for the 1.1.1 call must show **`cloud`**, not `local`.
4. The draft itself must be image-derived — it should describe what is actually in the image, not
   the filename-guess template ("this text model cannot see the image…").

That closes R2 and R12.

---

## What `serverless_vision_provider()` does (code reference)

```python
# api/providers.py:596
def serverless_vision_provider() -> VisionProvider | None:
    eid = os.environ.get("RUNPOD_ENDPOINT_ID")
    key = os.environ.get("RUNPOD_API_KEY")
    if not (eid and key):   # ← returns None when secret is empty → silent CPU fallback
        return None
    ...
```

The env var `RUNPOD_API_KEY` is a `secretref:runpod-api-key` in Azure Container Apps. If the
secret is empty, the env var is an empty string at runtime, `not (eid and key)` is `True`, and
every scan silently falls back to local CPU Ollama without logging a warning. The code is correct;
the only gap is the empty secret.
