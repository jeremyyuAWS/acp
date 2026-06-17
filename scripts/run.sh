#!/usr/bin/env bash
# One-command local demo: starts the control-plane API (:8077) and the
# React UI (:5173), tails both, and shuts both down on Ctrl-C.
#
#   ./scripts/run.sh
#
# Prereqs (one-time):
#   python -m venv .venv-drive && .venv-drive/bin/pip install -r api/requirements.txt
#   (cd frontend && npm install)
#   the .NET Office CLI built at spike/dotnet/.../Release, and the PDF engine
#   checkout at ~/projects/_review-digital-accessibility/worker-python
#   Drive scans also need keyless ADC:  gcloud auth application-default login
set -euo pipefail
ACP="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ACP/.venv-drive/bin/python"
PORT_API=8077
PORT_UI=5173

[ -x "$PY" ] || { echo "missing venv at $PY — see prereqs in this script's header"; exit 1; }
[ -d "$ACP/frontend/node_modules" ] || { echo "run: (cd frontend && npm install)"; exit 1; }

echo "→ API  http://localhost:$PORT_API   (uvicorn)"
( cd "$ACP/api" && exec "$PY" -m uvicorn app:app --host 0.0.0.0 --port "$PORT_API" ) &
API_PID=$!

echo "→ UI   http://localhost:$PORT_UI    (vite)"
( cd "$ACP/frontend" && exec npm run dev ) &
UI_PID=$!

cleanup() { echo; echo "stopping…"; kill "$API_PID" "$UI_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "ready — open http://localhost:$PORT_UI   (Ctrl-C to stop)"
wait
