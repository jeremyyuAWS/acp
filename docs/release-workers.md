# Dedicated Release capacity

Release can run independently from remediation using the same application image and durable job store. Existing installations retain their current routing until `ACP_DEDICATED_RELEASE_WORKERS=1` is explicitly enabled.

## Initial capacity

One private Container App, one replica maximum, 1 CPU and 2 GiB memory. `ACP_WORKERS=2` reserves one slot for reports and one for publishing, packaging and release continuation. The database pool is capped at two connections. Reports cannot take the publishing slot. There are no additional model calls. This adds Azure compute cost; the model-evaluation spending limit does not act as an Azure billing cap.

Existing admission checks, source hashes, receipts, retry limits and graceful shutdown remain in force. `deliver_corrected_copy` stays with remediation because it completes remediation's own saved-copy delivery. Only explicit Release jobs move.

## Safe rollout

1. Merge and deploy the tested image with dedicated routing still off. This is also the first deployment that understands the Release heartbeat.
2. Run `deploy/public/release_worker.py` with explicit subscription, resource group, source remediation worker, new Release name, tested image and environment. Without `--apply` it only validates. Stage names must end in `-staging`; production names must not.
3. Apply in staging first. Provisioning uses the source worker's environment, secret references and registry settings. Secret values never enter logs or command arguments. The app starts without ingress or an active queue scaler; exact existing Blob Data Contributor scopes are copied to its new identity before activation. System-identity Key Vault references require explicit provisioning rather than guessing access.
4. Confirm the Release heartbeat in `/readyz`, matching image version, successful storage access, and a small publishing/report smoke test. Confirm delivery receipts and no duplicate copies after an interrupted-job retry.
5. Set GitHub variable `STAGING_RELEASE_WORKER` to the new app name. The normal deployment path includes that worker in image updates, environment isolation, graceful drain and role-version verification. It activates dedicated routing and removes Release types from the remediation scaler. Repeat for production using `PRODUCTION_RELEASE_WORKER` only after staging passes.
6. Observe queue waits, failed retries, memory and provider throttling. The initial replica maximum stays one. Increase it only after measuring demand and reviewing resource/billing headroom. Azure may briefly overlap revisions during rollout.

Example validation (replace IMAGE with the CI-verified image):

```sh
python3 deploy/public/release_worker.py \
  --subscription 8fab0f8f-b577-45d7-a485-ec32f73b22be \
  --resource-group mdk-accessibility \
  --source acp-remediate --name acp-release \
  --image IMAGE --environment production
```

For dry-run capacity scripts, set `ACP_DEDICATED_RELEASE_WORKERS=1` to preview the isolated remediation query. Live right-sizing reads the deployed worker flag.

## Recovery

If provisioning fails after creation, leave dedicated routing off. The existing remediation fleet continues to handle Release. Inspect the new app and its identity grants before retrying; provisioning refuses to overwrite an existing app.

To return to shared processing, clear the environment's Release-worker workflow variable and deploy with dedicated routing off. Verify the remediation queue includes Release jobs and the fleet is healthy before stopping the dedicated worker. Do not remove the worker or its code while jobs remain active. A stale Release heartbeat marks readiness degraded once dedicated routing is active.
