#!/usr/bin/env bash
# Shared ACA readiness-gate installer. The first-deploy and image-only redeploy paths both
# source this file; keeping the write here prevents the workflow from silently bypassing it.

_readiness_probe_retry() {
  local i
  for i in 1 2 3 4 5 6; do
    if "$@" 2>/tmp/acp_az_err; then return 0; fi
    grep -qi "conflicting concurrent write" /tmp/acp_az_err || { cat /tmp/acp_az_err >&2; return 1; }
    echo "   ...ACA busy, readiness probe retry $i"; sleep 12
  done
  cat /tmp/acp_az_err >&2; return 1
}

_apply_readiness_probe() {
  if [ "${ACP_SKIP_READINESS_PROBE:-0}" = "1" ]; then
    echo "   readiness probe: skipped (ACP_SKIP_READINESS_PROBE=1)"
    return 0
  fi
  local tmpl patch rc=0
  if ! tmpl="$(az containerapp show "${AZ[@]}" -g "$RG" -n "$APP" \
                 --query properties.template -o json 2>/tmp/acp_probe_err)"; then
    echo "   NOTE: could not read $APP's template — readiness probe not applied." >&2
    echo "   $(grep -oE '\([A-Za-z]+\)' /tmp/acp_probe_err | head -1 || echo '(unknown)')" >&2
    return 0
  fi
  # The template includes literal environment values, so use a unique temporary file and
  # remove it on every path without printing its contents.
  patch="$(mktemp)"
  printf '%s' "$tmpl" | python3 scripts/aca_readiness_probe.py \
    --container "$APP" --path /probe/readyz --port 8077 >"$patch" 2>/tmp/acp_probe_err || rc=$?
  case "$rc" in
    3) echo "   readiness probe: already gating on /probe/readyz — nothing to do"
       rm -f "$patch"; return 0 ;;
    0) ;;
    *) echo "   NOTE: readiness probe not applied — $(head -c 300 /tmp/acp_probe_err)" >&2
       rm -f "$patch"; return 0 ;;
  esac
  if _readiness_probe_retry az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" \
       --yaml "$patch" -o none; then
    echo "   readiness probe: ACA now holds ingress until GET /probe/readyz answers"
  else
    echo "   NOTE: could not write the readiness probe; the deployed image remains live and ungated." >&2
  fi
  rm -f "$patch"
  return 0
}
