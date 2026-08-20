#!/usr/bin/env bash
# All FOUR checks the "Backend suite" job runs — because `pytest tests/` is not that job.
#
# CLAUDE.md is explicit about this and about what it has already cost: on 2026-08-06 #141 was
# verified with the full suite green (2112 passed) and merged during a GitHub Actions outage.
# When Actions recovered, the suite passed and the third guard failed — the squash commit
# carried no `Matrix-Note:` trailer. The message was published by then and could not be fixed,
# so that change has no PROGRESS_LOG entry and never will. The guard was not wrong; the wrong
# thing was verified.
#
# So this runs all four, and it runs them ALL rather than short-circuiting on the first red.
# `pytest && guard && guard && guard` would hide three answers behind one failure, and the
# guards are the ones nothing else prompts you for.
#
# Mirrors .github/workflows/ci.yml, job `backend`. When a step is added there, add it here.
set -uo pipefail

declare -a NAMES=() STATUS=()
failed=0

run() {  # run <label> <cmd...>
  local label=$1; shift
  printf '\n\033[1m==> %s\033[0m\n' "$label"
  if "$@"; then
    NAMES+=("$label"); STATUS+=("PASS")
  else
    NAMES+=("$label"); STATUS+=("FAIL (exit $?)"); failed=1
  fi
}

run "pytest tests/"                    python -m pytest tests/ -q "$@"
run "gen_matrix_coverage.py --check"   python scripts/gen_matrix_coverage.py --check
run "gen_todo_status.py --check"       python scripts/gen_todo_status.py --check

# The trailer guard, with ci.yml's own BASE_REF branch. Unset, `--check` inspects HEAD~1..HEAD;
# set (e.g. BASE_REF=main), it inspects every commit the branch adds on top of origin/$BASE_REF,
# which is what the workflow does on a PR. Use the second form before you push a branch — the
# first only ever looks at your most recent commit.
if [ -n "${BASE_REF:-}" ]; then
  run "gen_progress_log.py --check --since origin/$BASE_REF" \
      python scripts/gen_progress_log.py --check --since "origin/$BASE_REF"
else
  run "gen_progress_log.py --check" python scripts/gen_progress_log.py --check
fi

printf '\n\033[1m==== backend checks ====\033[0m\n'
for i in "${!NAMES[@]}"; do printf '  %-46s %s\n' "${NAMES[$i]}" "${STATUS[$i]}"; done

if [ "$failed" -ne 0 ]; then
  printf '\nAt least one check failed — this is the job, not just the suite.\n'
  exit 1
fi
printf '\nAll four green.\n'
