#!/usr/bin/env bash
# Drive _aca_retry from deploy/public/readiness_probe.sh against a scripted `az`.
#
# WHY A SHELL HARNESS, and not a source-level assertion. The property under test is a LOOP: how
# many times the command runs, and whether it stops. "Retries on a lock" and "gives up after N"
# and "does not retry a real error" are all statements about a sequence of calls, and only the
# real loop consumes a sequence. A test that greps for the word `retry` would pass on a loop that
# retried forever, or once, or on the wrong errors.
#
# Usage: aca_retry_harness.sh <readiness_probe.sh> <fail-count> <error-text>
#   The stub `az` fails the first <fail-count> calls with <error-text> on stderr, then succeeds.
#   Use a huge fail-count to test exhaustion.
#   Prints "calls=<n> exit=<rc>".
set -uo pipefail

PROBE="$1"; shift
FAIL_COUNT="$1"; shift
ERR_TEXT="$1"; shift

COUNTER_FILE="${COUNTER_FILE:-$(mktemp)}"
echo 0 > "$COUNTER_FILE"

# THE COUNTER MUST LIVE IN A FILE. `_aca_retry` runs the command with its stderr redirected but
# in the same shell, yet `$(cat ...)` subshells elsewhere make an in-memory counter fragile; a
# file is unambiguous and is what tests/redeploy_step9b_harness.sh settled on for the same reason.
az() {
  local i
  i="$(cat "$COUNTER_FILE")"
  i=$(( i + 1 ))
  echo "$i" > "$COUNTER_FILE"
  if [ "$i" -le "$FAIL_COUNT" ]; then
    printf 'ERROR: %s\n' "$ERR_TEXT" >&2
    return 1
  fi
  return 0
}

# No real waiting: the property is the number of attempts, not the wall clock.
sleep() { :; }

RG=mdk-accessibility
APP=acp-app
AZ=(--subscription stub)

# Lift the real functions out of the shipped file rather than retyping them — a retyped copy is
# how a broken helper passes its own test.
# shellcheck disable=SC1090
source "$PROBE"

set +e
_aca_retry az containerapp update "${AZ[@]}" -g "$RG" -n "$APP" --image img -o none >/dev/null 2>"${STDERR_FILE:-/dev/null}"
rc=$?
set -e

echo "calls=$(cat "$COUNTER_FILE") exit=$rc"
