# Sourced by redeploy.sh. Called only after its normal CI/queue/dependency gates.
_prepare_remediation_worker_patch() {
  local live
  # Files inherit mktemp's 0600 permissions; never log the template (env may be
  # sensitive). Keep them under WORK so the existing EXIT trap removes failures.
  live="$(mktemp "$WORK/remediation-live-XXXXXX")"
  REMEDIATION_PATCH="$(mktemp "$WORK/remediation-patch-XXXXXX")"
  _aca_retry az containerapp show "${AZ[@]}" -g "$RG" -n "$REMEDIATE_WORKER" \
    --query '{id:id,properties:{template:properties.template}}' -o json > "$live"
  python3 "$SRC_ROOT/deploy/public/remediation_scaler.py" "$live" "$REMEDIATION_PATCH" "$IMG" \
    "$WORKER_TERMINATION_GRACE_SECONDS" "$WORKER_DRAIN_SECONDS"
  REMEDIATION_RESOURCE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$live")"
  rm -f "$live"
}

_update_lane_worker() {
  local app="$1"
  if [ "$app" != "$REMEDIATE_WORKER" ]; then
    _aca_retry az containerapp update "${AZ[@]}" -g "$RG" -n "$app" --image "$IMG" \
      --termination-grace-period "$WORKER_TERMINATION_GRACE_SECONDS" \
      --set-env-vars "ACP_SHUTDOWN_DRAIN_SECONDS=$WORKER_DRAIN_SECONDS" --no-wait -o none
    return
  fi
  # One PATCH preserves the full scale configuration and worker settings.
  _aca_retry az rest --method patch --url "https://management.azure.com${REMEDIATION_RESOURCE_ID}?api-version=2025-07-01" \
    --body "@$REMEDIATION_PATCH" -o none
}

_verify_remediation_scaler() {
  local live
  live="$(mktemp "$WORK/remediation-verify-XXXXXX")"
  _aca_retry az containerapp show "${AZ[@]}" -g "$RG" -n "$REMEDIATE_WORKER" \
    --query properties.template.scale -o json > "$live"
  python3 - "$REMEDIATION_PATCH" "$live" <<'PYVERIFY'
import json, sys
expected = json.load(open(sys.argv[1]))['properties']['template']['scale']
actual = json.load(open(sys.argv[2]))
if actual != expected:
    raise SystemExit('remediation scaler verification failed: live scale differs from preserved target')
print('  remediation queue query and existing scale settings verified')
PYVERIFY
  rm -f "$live" "$REMEDIATION_PATCH"
}
