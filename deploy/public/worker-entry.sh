#!/bin/sh
# Worker-tier entrypoint (#113). Exists so `az containerapp --command acp-worker` is a SINGLE
# dash-free token: az's --command neither parses a JSON array string (it becomes one literal
# token → exec of a binary named '["/bin/sh",…' → CrashLoopBackOff, seen live) nor accepts a
# bare "-c" (argparse eats it as an unknown flag). Same ADC bootstrap as the API's CMD.
set -e
if [ -n "$ACP_GOOGLE_ADC" ]; then
  printf '%s' "$ACP_GOOGLE_ADC" > /tmp/adc.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/adc.json
fi
cd /app/api
exec python -m worker_main
