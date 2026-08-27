#!/usr/bin/env bash
# Backend for the Playwright E2E suite (frontend/e2e). Playwright starts this via its
# `webServer` config; you can also run it by hand to poke at the same stack with curl.
#
#   ./scripts/e2e-api.sh                  # :8078, fresh store, oracle HTML+PDF corpus
#   ACP_E2E_API_PORT=9000 ./scripts/e2e-api.sh
#
# Three things make this different from ./scripts/run.sh, and all three are what make the
# suite deterministic:
#
#   1. A FRESH STORE. api/store.py hardcodes the sqlite file at <repo>/acp.db with no env
#      override, and a scan left in `running` there blocks every later local scan with
#      "Discovery already active for source 'local'" — the new scan then reports
#      phase=discovered, files_found=0 and done=true, which reads as an empty corpus rather
#      than as a rejection. So the store is moved aside per run.
#   2. IN-PROCESS WORKERS. Assess fans out to the job queue (ADR 0007). With the default
#      ACP_RUNTIME_MODE the API runs zero workers, POST /scans/{id}/assess returns
#      worker_tier_alive=false, and the scan never finalizes. single-node runs 4 in-process.
#   3. A FROZEN CORPUS. ACP_LOCAL_CORPUS points local scans at a fixed set of oracle
#      fixtures instead of test-corpus/files, which tracks the demo's needs and changes.
set -euo pipefail

ACP="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${ACP_E2E_API_PORT:-8078}"
PY="${ACP_E2E_PYTHON:-$ACP/.venv-e2e/bin/python}"
CORPUS="$ACP/.e2e/corpus"
STORE="$ACP/acp.db"

[ -x "$PY" ] || {
  echo "e2e: no interpreter at $PY" >&2
  echo "  python -m venv .venv-e2e && .venv-e2e/bin/pip install -r api/requirements.txt" >&2
  echo "  (or set ACP_E2E_PYTHON to an interpreter that already has them)" >&2
  exit 1
}

# PDF only, and both halves of that are deliberate.
#
# Not Office: the docx/pptx/xlsx oracle fixtures need the .NET CLI built (spike/dotnet).
# Including them would score them None and turn a missing optional build into a failure that
# reads as a scoring regression. The PDF analyser is pure Python and vendored in-repo
# (ADR 0029), so it scores on a clean checkout.
#
# Not HTML either, which is less obvious: html IS analysed by POST /scans/{id}/assess, but it
# is not in the format list of any WCAG code in the app's default criteria, so the Assess
# screen counts HTML files as excluded ("not a document type ACP can assess"). Any exclusion
# sets needsAck, which disables the run button until the operator confirms — so an HTML fixture
# here does not add coverage, it just parks the suite on a disabled button. Keeping the corpus
# uniformly eligible is what makes the happy path a happy path.
FIXTURES=(
  pdf-untagged.pdf
  pdf-clean-accessible.pdf
  pdf-titled-lang.pdf
)

rm -rf "$CORPUS"
mkdir -p "$CORPUS"
for f in "${FIXTURES[@]}"; do
  src="$ACP/test-corpus/oracle/$f"
  [ -f "$src" ] || { echo "e2e: missing oracle fixture $src" >&2; exit 1; }
  cp "$src" "$CORPUS/$f"
done
echo "e2e: corpus = $CORPUS (${#FIXTURES[@]} files)"

# Moved aside rather than deleted so a failed run's data is still there to inspect.
[ -e "$STORE" ] && mv -f "$STORE" "$STORE.prev-e2e"

echo "e2e: API on http://127.0.0.1:$PORT"
cd "$ACP/api"
exec env \
  ACP_RUNTIME_MODE=single-node \
  ACP_LOCAL_CORPUS="$CORPUS" \
  "$PY" -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
