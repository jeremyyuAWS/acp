#!/usr/bin/env bash
# Roll the ACP container app back to a previous image — the 60-second answer to
# a bad deploy. Single-revision mode means we can't traffic-shift between
# revisions; instead we re-point the app at a previous image tag (every deploy
# pushes an immutable acp-app:<sha>-<epoch> tag to ACR, so old images are
# always still there).
#
#   ./rollback.sh              # roll back to the image before the current one
#   ./rollback.sh <image-tag>  # roll back to a specific tag (e.g. acp-app:7af44dd-1783035766)
#   ./rollback.sh --list       # show recent revisions + their images, change nothing
#
# Verifies the new revision reaches Running and /healthz returns 200 before
# declaring success. Idempotent and safe to re-run.
set -euo pipefail

RG="${ACP_RG:-mdk-accessibility}"
APP="${ACP_APP:-acp-app}"

# Resolve the subscription ONCE and scope every `az` call to it (see deploy.sh's preflight and
# tests/test_deploy_subscription_scope.py). This replaces:
#
#     SUB_ARG=()
#     [ -n "${ACP_SUBSCRIPTION:-}" ] && SUB_ARG=(--subscription "$ACP_SUBSCRIPTION")
#
# which left SUB_ARG EMPTY whenever ACP_SUBSCRIPTION was unset — the normal case, since nobody
# exports it before an emergency rollback. That was wrong in two different ways depending on the
# shell `#!/usr/bin/env bash` happens to find:
#   * bash 3.2 (still /bin/bash on macOS): "${SUB_ARG[@]}" on an empty array is an UNBOUND
#     variable under `set -u`, so even `rollback.sh --list` died at the first az call;
#   * bash >= 4.4: it expands to nothing, so every call silently followed the machine-global
#     default subscription in ~/.azure/azureProfile.json — which any concurrent process can
#     change with `az account set`. A rollback is what you run when a deploy already went
#     wrong; it must never guess which subscription it is repointing.
# Pinning the immutable ID (not the name) also means a rename cannot retarget a rollback midway.
if [ -n "${ACP_SUBSCRIPTION:-}" ]; then
  SUB="$(az account show --subscription "$ACP_SUBSCRIPTION" --query id -o tsv 2>/dev/null || true)"
  [ -n "$SUB" ] || { echo "refusing to roll back: ACP_SUBSCRIPTION='$ACP_SUBSCRIPTION' does not resolve to a subscription you can see (az login?)" >&2; exit 1; }
else
  SUB="$(az account show --query id -o tsv 2>/dev/null || true)"
  [ -n "$SUB" ] || { echo "refusing to roll back: no active Azure subscription -- run 'az login', or set ACP_SUBSCRIPTION" >&2; exit 1; }
fi
AZ=(--subscription "$SUB")   # always non-empty; splice into EVERY az call
echo "subscription: $(az account show "${AZ[@]}" --query name -o tsv 2>/dev/null || echo '?') ($SUB)"
echo "target:       $APP in $RG"

revisions() {
  # --all includes deactivated revisions (single-revision mode deactivates the
  # old one on every deploy) — without it there is nothing to roll back to.
  az containerapp revision list -n "$APP" -g "$RG" "${AZ[@]}" --all \
    --query "reverse(sort_by([].{rev:name, img:properties.template.containers[0].image, created:properties.createdTime, traffic:properties.trafficWeight, state:properties.runningState}, &created))" -o json
}

REVS=$(revisions)

if [ "${1:-}" = "--list" ]; then
  echo "$REVS" | python3 -c "import json,sys; [print(f\"{r['rev']}  {r['img'].split('/')[-1]:45} traffic={r['traffic']} {r['state']}\") for r in json.load(sys.stdin)[:8]]"
  exit 0
fi

CURRENT=$(echo "$REVS" | python3 -c "import json,sys; rs=json.load(sys.stdin); print(next(r['img'] for r in rs if r['traffic']==100))")
echo "current image: ${CURRENT##*/}"

if [ -n "${1:-}" ]; then
  ACR="${CURRENT%%/*}"
  TARGET="$ACR/${1#"$ACR"/}"
else
  # previous = newest image that differs from the one serving traffic
  TARGET=$(echo "$REVS" | python3 -c "
import json,sys
rs = json.load(sys.stdin)
cur = next(r['img'] for r in rs if r['traffic']==100)
print(next(r['img'] for r in rs if r['img'] != cur))")
fi
echo "rolling back to: ${TARGET##*/}"

az containerapp update -n "$APP" -g "$RG" "${AZ[@]}" --image "$TARGET" --output none

echo -n "waiting for the new revision to reach Running "
for _ in $(seq 1 60); do
  STATE=$(az containerapp revision list -n "$APP" -g "$RG" "${AZ[@]}" \
    --query "[?properties.trafficWeight==\`100\`] | [0].properties.runningState" -o tsv)
  [ "$STATE" = "Running" ] && break
  echo -n "."; sleep 5
done
echo " $STATE"
[ "$STATE" = "Running" ] || { echo "✗ revision never reached Running — check the portal"; exit 1; }

FQDN=$(az containerapp show -n "$APP" -g "$RG" "${AZ[@]}" --query properties.configuration.ingress.fqdn -o tsv)
CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$FQDN/healthz")
LIVE=$(az containerapp revision list -n "$APP" -g "$RG" "${AZ[@]}" \
  --query "[?properties.trafficWeight==\`100\`] | [0].properties.template.containers[0].image" -o tsv)
echo "healthz: $CODE · serving: ${LIVE##*/}"
[ "$CODE" = "200" ] && [ "$LIVE" = "$TARGET" ] && echo "✓ rollback complete" || { echo "✗ verification failed"; exit 1; }
