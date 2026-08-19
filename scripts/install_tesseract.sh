#!/usr/bin/env bash
# Install tesseract-ocr as reliably as a public apt mirror allows.
#
# WHAT WAS ACTUALLY FAILING, measured rather than assumed.
#
# On 2026-08-19 the OCR install failed on roughly half of all runners for over an hour, and
# `-qq` on both halves of `apt-get update && apt-get install` meant the logs never said which
# half. The timings did: every failed step took 5m30s exactly, and the retry warnings landed
# 100s and 110s apart with 10s/20s/30s backoff between them — so each attempt burned exactly
# 90 seconds, which was the `timeout 90` on `apt-get update`. 3x90 + (10+20+30) = 330s = 5m30s.
#
# So `apt-get update` was timing out and `apt-get install` NEVER RAN. That matters, because the
# two do very different amounts of work: `update` pulls the Packages indices for every
# configured source (tens of MB across main/universe/security/backports), while installing
# tesseract-ocr pulls a handful of .debs. A mirror too congested to serve the former in 90s can
# usually still serve the latter — and the runner image already ships a populated index.
#
# Hence the ladder below: try the cheap thing first, and only pay for metadata if we must.
#
#   0. already installed            -> nothing to do (some images cache it)
#   1. install with the EXISTING index, no update at all   <- skips the operation that failed
#   2. update + install, twice, against the configured mirror
#   3. update from a FALLBACK mirror only, then install
#
# Each rung falls through to the next, so a wrong guess about which rung will work costs time,
# never correctness. A global deadline bounds the total: the old code could only ever spend
# 330s achieving nothing, so spending a little more to actually succeed is the better trade,
# but not without a ceiling.
#
# NOT a softening of the OCR gate. This script makes the install more likely to succeed; it
# does not make failure acceptable. `Fail if OCR coverage was lost` in ci.yml and
# test_ocr_criteria_are_covered_in_ci still fail the build when tesseract is missing, because
# ocr.is_available() gates 1.4.5 and 1.4.9 and a green tick over a suite silently missing two
# criteria is the shape of gap this repo has been bitten by twice.
#
# Env overrides exist for the tests (tests/test_install_tesseract.py), which drive every rung
# with a stub apt-get. ACP_SUDO= runs without sudo.
set -uo pipefail

PKGS=${ACP_TESSERACT_PKGS:-tesseract-ocr}
APT=${ACP_APT_GET:-apt-get}
SUDO=${ACP_SUDO-sudo}
DEADLINE=${ACP_TESSERACT_DEADLINE:-420}
FALLBACK_MIRROR=${ACP_APT_FALLBACK_MIRROR:-http://archive.ubuntu.com/ubuntu}
FALLBACK_LIST=${ACP_APT_FALLBACK_LIST:-/etc/apt/sources.list.d/acp-tesseract-fallback.list}
BACKOFF=${ACP_APT_BACKOFF:-5}

START=$SECONDS
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

# One stalled connection must not eat the whole budget, and IPv6 that blackholes is a classic
# cause of exactly the "hangs until timeout" shape seen here. Retries are apt's own, per-file.
APT_OPTS=(
  -o Acquire::ForceIPv4=true
  -o Acquire::http::Timeout=15
  -o Acquire::https::Timeout=15
  -o Acquire::Retries=2
)

note()  { printf '%s\n' "$*"; }
warn()  { printf '::warning::%s\n' "$*"; }
fail()  { printf '::error::%s\n' "$*"; }

remaining() { echo $(( DEADLINE - (SECONDS - START) )); }

# Cap a per-command timeout at whatever is left of the global budget.
cap() {
  local want=$1 rem
  rem=$(remaining)
  (( rem < want )) && want=$rem
  echo "$want"
}

# Print what apt actually said. The whole reason today's outage needed arithmetic to diagnose
# is that this output was thrown away.
show_log() {
  if [ -s "$LOG" ]; then
    note "--- last 15 lines of apt output ---"
    tail -15 "$LOG"
    note "-----------------------------------"
  fi
}

apt_run() {  # apt_run <seconds> <apt-get args...>
  local t
  t=$(cap "$1"); shift
  if (( t <= 0 )); then
    return 124
  fi
  if [ -n "$SUDO" ]; then
    "$SUDO" env DEBIAN_FRONTEND=noninteractive timeout "$t" "$APT" "$@" >"$LOG" 2>&1
  else
    env DEBIAN_FRONTEND=noninteractive timeout "$t" "$APT" "$@" >"$LOG" 2>&1
  fi
}

# shellcheck disable=SC2086  # PKGS is a deliberate word-split list
do_install() { apt_run "$1" install -y -q "${APT_OPTS[@]}" $PKGS; }
do_update()  { apt_run "$1" update -q "${APT_OPTS[@]}"; }

# Rung 0 — already there.
if command -v tesseract >/dev/null 2>&1; then
  note "tesseract already present: $(command -v tesseract)"
  exit 0
fi

# Rung 1 — the cheap path, and the one that dodges the operation that actually failed today.
note "==> installing $PKGS from the existing package index (no apt-get update)"
if do_install 90; then
  note "installed without touching the metadata mirror"
  exit 0
fi
warn "install from the existing index failed; the index is probably stale, will update"
show_log

# Rung 2 — the conventional path, against whatever mirror the image is configured for.
for attempt in 1 2; do
  note "==> apt-get update + install (attempt $attempt of 2)"
  if do_update 75; then
    if do_install 120; then
      note "installed after refreshing the index"
      exit 0
    fi
    warn "index refreshed but install failed (attempt $attempt)"
  else
    warn "apt-get update failed or timed out (attempt $attempt)"
  fi
  show_log
  sleep $(( attempt * BACKOFF ))
done

# Rung 3 — the configured mirror is not serving us. Pull the index from a different one.
#
# Writes a dedicated list and refreshes from THAT ALONE (Dir::Etc::sourcelist plus an empty
# sourceparts), so the mirror we have already proven slow is not re-contacted. List-Cleanup=0
# keeps the indices we do have. Existing sources files are never edited: this is a throwaway
# runner, but a botched sed on sources.list breaks every later step in ways that read as
# unrelated.
note "==> falling back to $FALLBACK_MIRROR"
CODENAME=${ACP_APT_CODENAME:-$( . /etc/os-release 2>/dev/null && printf '%s' "${VERSION_CODENAME:-}" )}
if [ -z "$CODENAME" ]; then
  fail "cannot determine the Ubuntu codename, so no fallback mirror can be configured"
  exit 1
fi

if [ -n "$SUDO" ]; then
  printf 'deb %s %s main universe\n' "$FALLBACK_MIRROR" "$CODENAME" | "$SUDO" tee "$FALLBACK_LIST" >/dev/null
else
  printf 'deb %s %s main universe\n' "$FALLBACK_MIRROR" "$CODENAME" > "$FALLBACK_LIST"
fi

if apt_run 75 update -q "${APT_OPTS[@]}" \
     -o Dir::Etc::sourcelist="$FALLBACK_LIST" \
     -o Dir::Etc::sourceparts=/dev/null \
     -o APT::Get::List-Cleanup=0; then
  if do_install 120; then
    note "installed from the fallback mirror"
    exit 0
  fi
  warn "fallback index fetched but install still failed"
else
  warn "fallback mirror update failed or timed out"
fi
show_log

fail "tesseract install failed: neither the configured mirror nor $FALLBACK_MIRROR served it within ${DEADLINE}s"
note "1.4.5 and 1.4.9 cannot be exercised without it — the build will be failed by the OCR gate."
exit 1
