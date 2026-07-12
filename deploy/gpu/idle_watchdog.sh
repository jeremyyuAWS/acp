#!/usr/bin/env bash
# Idle watchdog: terminate the burst GPU pod after ~15 minutes without inference.
# Ollama unloads idle models (keep_alive default 5m), so an empty /api/ps for three
# consecutive 5-minute checks means nothing has inferred for >=15 minutes. A forgotten
# 4090 is ~$10/day; this makes "forgot to tear it down" impossible. Run it right after
# up.sh:   nohup deploy/gpu/idle_watchdog.sh >/tmp/gpu_watchdog.log 2>&1 &
set -uo pipefail
PID="${1:-$(cat /tmp/acp_runpod_pod_id 2>/dev/null || true)}"
[ -n "$PID" ] || { echo "no pod id"; exit 1; }
BASE="https://$PID-11434.proxy.runpod.net"
UA="Mozilla/5.0"
idle=0
while true; do
  sleep 300
  models=$(curl -s -m 10 -H "User-Agent: $UA" "$BASE/api/ps" \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("models",[])))' 2>/dev/null || echo "?")
  if [ "$models" = "0" ]; then idle=$((idle+1)); else idle=0; fi
  echo "$(date -u +%H:%M) loaded_models=$models idle_checks=$idle"
  if [ "$idle" -ge 3 ]; then
    echo "idle >=15min — terminating pod $PID"
    "$(dirname "$0")/down.sh" "$PID"
    exit 0
  fi
done
