# Dedicated production Discovery service

Target: `acp-discovery` in `mdk-accessibility`, same Container Apps environment and private database/Redis as `acp-worker`. No ingress. One minimum and maximum replica, 2 vCPU / 4 GiB; three worker threads, all restricted by `ACP_WORKER_ROLE=discovery`. Metadata-only, four-format scope remains enabled. This is three concurrent jobs, not three CPUs. A single replica can still fail; durable leases/retries recover work.

`ACP_WORKER_ROLE=processing` on the existing worker excludes `scan_discover` using the registered handler types. Default `mixed` preserves the existing topology. Invalid roles fail closed. Role selection applies at startup and live pool resizing. A processing pool with no eligible handlers claims nothing.

The normal production redeploy updates `acp-app`, `acp-worker`, and `acp-discovery` to the same
version-stamped application image. The container app's `command: acp-worker` and
`ACP_WORKER_ROLE=discovery` retain the dedicated role. This lockstep update is required: lifecycle
evaluation schemas live in the shared handler/store code, and a stale Discovery image can write
candidate statuses without the evidence ledger a newer API expects. The Dockerfile here remains
for initial provisioning and explicit engine experiments, not routine releases.

Cutover: create Discovery first with existing database/Redis credentials in secret references, no public ingress and no AI credentials; verify readiness and filtered claims. Wait until existing running jobs are idle before switching the old service to the role-aware image and `processing` role. Then reduce processing to one minimum replica, retaining its existing CPU autoscaling ceiling initially. Do not kill active scans to perform this step.

Rollback: restore the existing worker's previous image/settings while retaining Discovery until mixed workers are healthy. Do not delete the dedicated service or change its image while it has an active job. Never delete source documents or scan history during topology changes.

Current shared worker heartbeat describes the last reporting replica, not aggregate capacity by role. Do not present that number as total Discovery capacity. Queue-based autoscaling and role-aware aggregate monitoring are separate follow-up work.
