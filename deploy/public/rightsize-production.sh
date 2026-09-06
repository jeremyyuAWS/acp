#!/usr/bin/env bash
# Apply the reviewed production capacity baseline without changing images or secrets.
set -euo pipefail

SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-8fab0f8f-b577-45d7-a485-ec32f73b22be}"
RESOURCE_GROUP="${ACP_RESOURCE_GROUP:-mdk-accessibility}"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# A worker replica that is removed mid-job must DRAIN, not die, and scale-in is the path this
# script owns. deploy/public/redeploy.sh sets the two settings that make that happen — the ACA
# termination grace period and the application's own shutdown drain — but it sets them on a
# ROLLOUT. Scale-in has no rollout: the queue scaler removes a replica, ACA sends SIGTERM, and
# whatever grace period the app happens to carry is what the in-flight remediation gets. On an app
# created by deploy.sh and never redeployed, that is ACA's 30-second default, which is not enough
# for a document-sized job.
#
# So the capacity script sets them too, from the SAME environment variables with the SAME defaults
# as redeploy.sh, so the two scripts cannot disagree about what a drain is. Applied to the worker
# apps only: $db_pool is set on exactly those, and they are exactly the apps that hold
# partially-processed documents. acp-app serves HTTP and acp-ollama holds no ACP job.
WORKER_TERMINATION_GRACE_SECONDS="${ACP_WORKER_TERMINATION_GRACE_SECONDS:-600}"
WORKER_DRAIN_SECONDS="${ACP_WORKER_DRAIN_SECONDS:-540}"

update_app() {
  local name="$1" cpu="$2" memory="$3" min="$4" max="$5" db_pool="${6:-}"
  local args=(containerapp update --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP"
    --name "$name" --cpu "$cpu" --memory "$memory" --min-replicas "$min" --max-replicas "$max")
  if [[ -n "$db_pool" ]]; then
    args+=(--set-env-vars "ACP_DB_MAX_CONN=$db_pool" "ACP_SHUTDOWN_DRAIN_SECONDS=$WORKER_DRAIN_SECONDS")
    args+=(--termination-grace-period "$WORKER_TERMINATION_GRACE_SECONDS")
  fi
  if $DRY_RUN; then
    printf 'az'
    printf ' %q' "${args[@]}"
    printf '\n'
  else
    echo "Right-sizing $name ($cpu CPU, $memory, replicas $min-$max)"
    az "${args[@]}" --output none
  fi
}

# WHY THE QUERY CARRIES MORE THAN `status='queued'`. KEDA divides this count by
# targetQueryValue and asks Azure for that many replicas, so it has to count work a worker can
# actually CLAIM. store.claim_job claims a row only when status='queued' AND run_after <= now AND
# attempts < max_attempts; this rule tested the first of the three until 2026-09-06.
#
# Both missing terms count rows no replica is allowed to take. `run_after` is how retry backoff is
# expressed (store.fail_job writes now + backoff, up to 600s), and an `attempts >= max_attempts`
# row stays at status='queued' until the reaper marks it dead. The tier scaled up for neither.
#
# The query is GENERATED, not typed: api/queue_scaler.py owns the predicate and the lane list, and
# `python scripts/gen_queue_scalers.py --check` fails the build if this line drifts from it.
apply_remediation_autoscale() {
  local args=(containerapp update --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP"
    --name acp-remediate --scale-rule-name remediation-queue
    --scale-rule-type postgresql
    --scale-rule-metadata
      "query=SELECT count(*) FROM jobs WHERE status='queued' AND type IN ('remediate_file', 'deliver_corrected_copy', 'rescore_file', 'apply_approved_values', 'publish_file') AND run_after::timestamptz <= now() AND attempts < max_attempts"
      "targetQueryValue=4"
    --scale-rule-auth "connection=database-url")
  if $DRY_RUN; then
    printf 'az'
    printf ' %q' "${args[@]}"
    printf '\n'
  else
    echo "Enabling Remediation queue autoscale (4 queued jobs per replica)"
    az "${args[@]}" --output none
  fi
}

apply_assess_autoscale() {
  # ASSESS HAS NO QUEUE SCALER TODAY, AND ATTACHING ONE WOULD NOT GIVE IT AUTOSCALING. The tier
  # runs 5-5 below: floor equals ceiling, so a scaler on it can compute any replica count it
  # likes and Azure cannot act on it. That is why this is guarded rather than simply added — an
  # `az containerapp update --scale-rule-*` creates a REVISION, and paying a worker restart for a
  # rule that provably cannot fire is worse than not having the rule.
  #
  # WHAT IS BLOCKING THE CEILING IS THE CONNECTION BUDGET, NOT AN OVERSIGHT.
  # tests/test_capacity_budget.py computes it: at assess 5-10 the fleet wants 136 connections
  # during a revision overlap plus the 15-connection reserve, against a server that has 150 — and
  # that is before discovery's own range is settled. Raising this ceiling is a decision about
  # where those connections come from (a larger Postgres SKU, a smaller acp-app pool, or lower
  # business-hours floors), not a line to edit here.
  #
  # DEFINED AFTER apply_remediation_autoscale DELIBERATELY.
  # tests/test_packaging_chart.py finds the remediate rule by name now rather than by taking the
  # first `type IN (...)` in the file, so the order is no longer load-bearing — but the rule that
  # a second lane's query must not be mistaken for the first one's is worth keeping visible.
  local floor="$1" ceiling="$2"
  if [[ "$floor" == "$ceiling" ]]; then
    echo "Skipping Assess queue autoscale: acp-assess is pinned at $floor (floor == ceiling)."
    echo "  A scale rule cannot add a replica to a pinned tier. Raise the ceiling first — see"
    echo "  tests/test_capacity_budget.py for what the connection budget allows."
    return 0
  fi
  local args=(containerapp update --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP"
    --name acp-assess --scale-rule-name assess-queue
    --scale-rule-type postgresql
    --scale-rule-metadata
      "query=SELECT count(*) FROM jobs WHERE status='queued' AND type IN ('scan', 'scan_assess', 'scan_batch', 'scan_file', 'workspace_scan_file', 'workspace_scan_discover', 'scan_finalize', 'assess_trace') AND run_after::timestamptz <= now() AND attempts < max_attempts"
      "targetQueryValue=8"
    --scale-rule-auth "connection=database-url")
  if $DRY_RUN; then
    printf 'az'
    printf ' %q' "${args[@]}"
    printf '\n'
  else
    echo "Enabling Assess queue autoscale (8 queued jobs per replica)"
    az "${args[@]}" --output none
  fi
}

# The web tier retains burst headroom. Discovery can use its existing CPU scale
# rule. Assessment and Remediation are throughput-sensitive batch stages: keep
# five replicas warm so large runs retain the production performance baseline.
update_app acp-app       1.0 2Gi 1 3
# Dedicated worker replicas serve no HTTP traffic. Their two job threads share a two-connection
# pool; scheduler/heartbeat operations wait briefly for a slot instead of reserving idle
# connections. This keeps the full fleet beneath Postgres's measured 150-connection ceiling,
# including old+new revision overlap during deploy.
update_app acp-discovery 1.0 2Gi 1 2  2
update_app acp-assess    2.0 4Gi 5 5  2
update_app acp-remediate 2.0 4Gi 5 10 2
apply_remediation_autoscale
apply_assess_autoscale 5 5

# Production and staging point at acp-ollama-gpu. Keep this legacy fallback
# available but cold until explicitly addressed through its internal ingress.
update_app acp-ollama    4.0 8Gi 0 1

if ! $DRY_RUN; then
  echo "Production capacity baseline applied."
fi
