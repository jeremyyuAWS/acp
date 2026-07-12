#!/usr/bin/env bash
# Pull the bake-off vision models onto the GPU pod (streamed → dodges Cloudflare 524).
set -uo pipefail
PID=$(cat /tmp/acp_runpod_pod_id); BASE="https://$PID-11434.proxy.runpod.net"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
for M in "llava:7b" "llama3.2-vision:11b" "bakllava:latest"; do
  echo ">> pulling $M ..."
  curl -s -N -H 'content-type: application/json' -H "User-Agent: $UA" "$BASE/api/pull" \
    -d "{\"name\":\"$M\",\"stream\":true}" \
    | python3 -c "
import sys,json
last=''
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: d=json.loads(line)
    except: continue
    s=d.get('status','')
    if s!=last and 'pulling' not in s.lower(): print('  ',s); last=s
    if d.get('error'): print('  ERROR',d['error'])
"
done
echo ">> models now on pod:"
curl -s -m 20 -H "User-Agent: $UA" "$BASE/api/tags" | python3 -c "import sys,json;print('  ',[m['name'] for m in json.load(sys.stdin).get('models',[])])"
