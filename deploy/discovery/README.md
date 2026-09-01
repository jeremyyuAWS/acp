# Dedicated production Discovery service

Target: `acp-discovery` in `mdk-accessibility`, alongside `acp-assess` and `acp-remediate` in the same Container Apps environment and private database/Redis. The retired generic `acp-worker` no longer exists in production. No ingress. One minimum and maximum replica, 2 vCPU / 4 GiB; three worker threads, all restricted by `ACP_WORKER_ROLE=discovery`. Metadata-only, four-format scope remains enabled. This is three concurrent jobs, not three CPUs. A single replica can still fail; durable leases/retries recover work.

Production uses three disjoint roles: `discovery`, `assess`, and `remediate`. Tests sweep the registered handlers and fail if any job type is missing from those lanes or appears in more than one. Default `mixed` remains available for local and staging topologies. Invalid roles fail closed.

The normal production redeploy updates `acp-app`, `acp-discovery`, `acp-assess`, and
`acp-remediate` to the same version-stamped application image. Each container app keeps its
`command: acp-worker` and dedicated `ACP_WORKER_ROLE`. This lockstep update is required: lifecycle
evaluation schemas live in the shared handler/store code, and a stale Discovery image can write
candidate statuses without the evidence ledger a newer API expects. The Dockerfile here remains
for initial provisioning and explicit engine experiments, not routine releases.

Cutover: create Discovery first with existing database/Redis credentials in secret references, no public ingress and no AI credentials; verify readiness and filtered claims. Wait until existing running jobs are idle before switching the old service to the role-aware image and `processing` role. Then reduce processing to one minimum replica, retaining its existing CPU autoscaling ceiling initially. Do not kill active scans to perform this step.

Rollback: restore the existing worker's previous image/settings while retaining Discovery until mixed workers are healthy. Do not delete the dedicated service or change its image while it has an active job. Never delete source documents or scan history during topology changes.

Current shared worker heartbeat describes the last reporting replica, not aggregate capacity by role. Do not present that number as total Discovery capacity. Queue-based autoscaling and role-aware aggregate monitoring are separate follow-up work.
