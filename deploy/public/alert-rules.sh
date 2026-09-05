#!/usr/bin/env bash
# Create the Azure Monitor metric alert rules that Live Operations reads back.
#
# WHY THIS EXISTS AS A SCRIPT. Until it is run, every worker service shows "Not monitored" in the
# drawer's alerts panel — deliberately, because an empty firing list over a service no rule covers
# is not a healthy service, it is an unwatched one. This is what turns that warning into a real
# answer. GET /control/workers/capacity reads the rules back through metric_alerts /
# metric_alerts_status, so the panel needs nothing else once these exist.
#
# NO ACTION GROUP IS REQUIRED. A rule with no action still evaluates, still records Fired/Resolved,
# and is therefore still visible in the drawer and in the portal — it just does not page anyone.
# Pass --action-group <id-or-name> to attach one. Notification routing is a decision about who
# gets woken at 3am, which is not a decision this script should make for an operator.
#
# WHAT IS DELIBERATELY NOT CREATED HERE, and why it would be dishonest to:
#
#   · queue stalled            · no worker heartbeat        · excessive job retries
#
# Those are ACP-internal conditions. They live in ACP's own database, not in any metric Azure
# collects about a Container App, so no metric alert can watch them — and a rule NAMED after one
# of them, thresholded on some Container Apps metric that merely correlates, would be worse than
# no rule at all: the drawer would report the queue as monitored, and it would not be. They need
# either a custom metric published to Azure Monitor or a log alert over Application Insights, and
# neither exists yet. `ResiliencyRequestRetries` below is the HTTP-level retry count between
# replicas, which is a real Azure metric and a different thing from a job retry.
#
# UNVERIFIED against a live subscription, like the rest of this repo's Azure code. Run with
# --dry-run first; it prints the exact az invocations without sending them.
set -euo pipefail

SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-8fab0f8f-b577-45d7-a485-ec32f73b22be}"
RESOURCE_GROUP="${ACP_RESOURCE_GROUP:-mdk-accessibility}"
# The same list the API reads. Keep these in step with WORKER_APP_NAMES: a rule is matched to a
# service in the drawer by RESOURCE ID, so an app missing here shows as unmonitored, correctly.
read -r -a APPS <<< "${WORKER_APP_NAMES_SPACED:-acp-assess acp-remediate acp-discovery}"

DRY_RUN=false
ACTION_GROUP=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --action-group) ACTION_GROUP="${2:?--action-group needs a value}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

scope_of() {
  printf '/subscriptions/%s/resourceGroups/%s/providers/Microsoft.App/containerApps/%s' \
    "$SUBSCRIPTION" "$RESOURCE_GROUP" "$1"
}

# create_rule <app> <suffix> <severity> <condition> <window> <frequency> <description>
#
# Idempotent by design: `az monitor metrics alert create` updates a rule of the same name in the
# same group rather than failing, so re-running after a threshold change is the intended way to
# edit one. The name carries the app, because a rule's name is what an operator reads first in a
# 3am page and "cpu-high" across three worker apps is three identical pages.
create_rule() {
  local app="$1" suffix="$2" severity="$3" condition="$4" window="$5" frequency="$6" description="$7"
  local args=(monitor metrics alert create
    --name "${app}-${suffix}"
    --subscription "$SUBSCRIPTION"
    --resource-group "$RESOURCE_GROUP"
    --scopes "$(scope_of "$app")"
    --condition "$condition"
    --window-size "$window"
    --evaluation-frequency "$frequency"
    --severity "$severity"
    --description "$description")
  [[ -n "$ACTION_GROUP" ]] && args+=(--action "$ACTION_GROUP")
  if $DRY_RUN; then
    printf 'az'; printf ' %q' "${args[@]}"; printf '\n'
  else
    echo "  ${app}-${suffix} (severity $severity)"
    az "${args[@]}" --output none
  fi
}

for app in "${APPS[@]}"; do
  echo "$app:"

  # Severity 1 (Error), not 0. A crash loop degrades throughput and is worth waking someone for;
  # it is not the whole product being down, and reserving 0 for that keeps 0 meaningful.
  create_rule "$app" crash-loop 1 \
    "total RestartCount > 3" PT15M PT5M \
    "Replicas restarted more than 3 times in 15 minutes — a crash loop, not a single restart."

  # Zero replicas on an app whose minimum is above zero means Azure could not place any. This is
  # the one that is genuinely critical: no replica is no work, silently.
  create_rule "$app" no-replicas 0 \
    "average Replicas < 1" PT5M PT1M \
    "No replicas running. Work queued for this service is not being processed at all."

  # Severity 2 (Warning) and a FIFTEEN minute window on both saturation rules. A worker at 90% CPU
  # for one minute is a worker doing its job; the alert is for saturation that is sustained enough
  # that the scale rule has had time to answer it and has not.
  create_rule "$app" cpu-saturated 2 \
    "average CpuPercentage > 85" PT15M PT5M \
    "CPU above 85% for 15 minutes — sustained past the point autoscale should have relieved it."

  create_rule "$app" memory-saturated 2 \
    "average MemoryPercentage > 85" PT15M PT5M \
    "Memory above 85% for 15 minutes. Sustained memory pressure precedes OOM restarts."

  # HTTP-level retries between replicas — NOT job retries, which Azure does not see. Rising values
  # mean replicas are failing to reach each other or a dependency, which shows up as slow work
  # long before it shows up as a failure.
  create_rule "$app" connection-retries 2 \
    "total ResiliencyRequestRetries > 50" PT15M PT5M \
    "More than 50 connection retries in 15 minutes — replicas are struggling to reach a dependency."
done

if $DRY_RUN; then
  echo
  echo "Dry run: nothing was sent. Re-run without --dry-run to create these rules."
else
  echo
  echo "Done. Live Operations will show these under Alerts on each worker service."
  echo "No action group is attached, so nothing pages anyone — pass --action-group to add one."
fi
