#!/usr/bin/env bash
# Drive step 9b/9c of deploy/public/redeploy.sh across a SEQUENCE of /readyz payloads.
#
# WHY A SHELL HARNESS. The embedded python is unit-tested directly (it is extracted and run), but
# the defect this exists for lives in the SHELL around it: the retry loop used to break on the
# first clean poll, so a value that alternated between polls passed. A per-payload unit test
# cannot express "poll 1 dirty, poll 2 clean, poll 3 dirty" — only a sequence can, and only the
# real loop consumes a sequence.
#
# Usage: redeploy_step9b_harness.sh <redeploy.sh> <build-version> <payload.json>...
#   Payloads are consumed in order; the last one repeats for every further poll.
#   AZ_REVS  — what the stubbed `az revision list` count returns (default 1).
#   Writes the poll count to $COUNTER_FILE and the simulated clock to $CLOCK_FILE.
set -euo pipefail

SCRIPT="$1"; shift
BUILD_VERSION="$1"; shift
_PAYLOADS=("$@")

COUNTER_FILE="${COUNTER_FILE:-/tmp/step9b.counter}"
CLOCK_FILE="${CLOCK_FILE:-/tmp/step9b.clock}"

# THE COUNTER MUST LIVE IN A FILE. `curl` is called inside $(...), which is a subshell, so a
# shell variable incremented there never reaches the parent — every poll would get payload[0]
# and the sequence would silently never advance. The first version of this harness did exactly
# that and reported a bite it had not performed: both the fixed and the broken script were fed
# the same payload five times, and the difference between them was invisible.
echo 0 > "$COUNTER_FILE"
echo 0 > "$CLOCK_FILE"

# CYCLE=1 wraps around instead of repeating the last payload. Needed to express a run that never
# settles AND happens to end on a clean poll — the case where `_STALE` (the last poll's result)
# is empty at exhaustion, which is a pass only if the verdict is read from the wrong variable.
curl() {
  local i last
  i="$(cat "$COUNTER_FILE")"
  echo $(( i + 1 )) > "$COUNTER_FILE"
  last=$(( ${#_PAYLOADS[@]} - 1 ))
  if [ "${CYCLE:-0}" = 1 ]; then
    i=$(( i % ${#_PAYLOADS[@]} ))
  else
    [ "$i" -gt "$last" ] && i=$last
  fi
  cat "${_PAYLOADS[$i]}"
}

# Each simulated poll advances the clock by 5s, matching the real `sleep 5`, so the streak span
# accumulates without the test taking two minutes of wall clock.
sleep() { echo $(( $(cat "$CLOCK_FILE") + 5 )) > "$CLOCK_FILE"; SECONDS="$(cat "$CLOCK_FILE")"; }
SECONDS=0

az() { echo "${AZ_REVS-1}"; }
say() { printf '\n> %s\n' "$*"; }

RG=mdk-accessibility
APP=acp-app
FQDN=example.invalid
AZ=(--subscription stub)
DISCOVERY_WORKER=acp-discovery
ASSESS_WORKER=acp-assess
REMEDIATE_WORKER=acp-remediate
LANE_WORKERS=("$DISCOVERY_WORKER" "$ASSESS_WORKER" "$REMEDIATE_WORKER")
LANE_ROLES=("discovery" "assess" "remediate")

# Lift the block out of the shipped script rather than retyping it — a retyped copy is how a
# broken block passes its own test.
_BLOCK="$(mktemp)"
python3 - "$SCRIPT" > "$_BLOCK" <<'PY'
import sys
src = open(sys.argv[1]).read()
start = src.index('say "verifying worker services')
end = src.index("# WARNS, IT DOES NOT DIE")
sys.stdout.write(src[start:end])
PY

# shellcheck disable=SC1090
source "$_BLOCK"
rm -f "$_BLOCK"
