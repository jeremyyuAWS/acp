#!/usr/bin/env bash
# Shared ACA readiness-gate installer, plus the transient-conflict retry both deploy paths use.
# The first-deploy and image-only redeploy paths both source this file; keeping the write here
# prevents the workflow from silently bypassing it. `_aca_retry` lives here for the same reason —
# this is the one file both paths already source, so it is the only place a helper can be shared
# without adding a second sourcing order to get wrong.

# ── transient ACA conflicts ────────────────────────────────────────────────────────────────
# Azure serialises modifications per container app. A second write while one is provisioning is
# refused, and the refusal is a STATE, not a fault: the same command succeeds once the in-flight
# operation settles. Two spellings, both seen in production:
#
#   (ContainerAppOperationInProgress) Cannot modify a container app 'acp-discovery' because
#   there is an active provisioning operation in progress. OperationId: '...'
#
#   ...conflicting concurrent write...
#
# ONLY THESE RETRY. Anything else — a missing image, an expired credential, a typo'd app name —
# fails on the first attempt, loudly. A retry loop that cannot tell a lock from a real error turns
# a five-second failure into a three-minute one and reports the wrong cause at the end of it.
_ACA_RETRY_ATTEMPTS="${ACP_ACA_RETRY_ATTEMPTS:-12}"
_ACA_RETRY_SLEEP="${ACP_ACA_RETRY_SLEEP:-15}"

_aca_transient() {
  case "$1" in
    *ContainerAppOperationInProgress*) return 0 ;;
    *[Cc]onflicting\ concurrent\ write*) return 0 ;;
  esac
  return 1
}

# Run an az command, retrying only while ACA says it is busy. Pass `-o none` if the command's
# stdout is noise: this deliberately does NOT redirect stdout, because the caller redirecting it
# would also swallow the progress lines below, and a deploy that appears hung for three minutes
# with nothing in the log is how a bounded wait gets mistaken for a stuck one.
_aca_retry() {
  local i err
  # A unique file, not a fixed /tmp path: two deploys running at once would otherwise read each
  # other's stderr and misclassify a real error as a lock, or the reverse.
  err="$(mktemp)"
  for (( i = 1; i <= _ACA_RETRY_ATTEMPTS; i++ )); do
    if "$@" 2>"$err"; then rm -f "$err"; return 0; fi
    if ! _aca_transient "$(cat "$err")"; then
      cat "$err" >&2; rm -f "$err"; return 1
    fi
    if [ "$i" -ge "$_ACA_RETRY_ATTEMPTS" ]; then break; fi
    echo "   ...ACA busy (${i}/${_ACA_RETRY_ATTEMPTS}), waiting ${_ACA_RETRY_SLEEP}s: $(tr -d '\n' < "$err" | head -c 140)"
    sleep "$_ACA_RETRY_SLEEP"
  done
  # Exhausted. NON-ZERO, explicitly — an earlier draft carried an `rc=0` that nothing reassigned
  # and so returned SUCCESS here, which would have let a deploy sail past an update that never
  # landed. That is strictly worse than the abort this helper exists to replace: the original bug
  # at least stopped. Caught by test_the_wait_is_bounded on its first run.
  #
  # The last error is printed rather than summarised — a bounded wait that gives up must say what
  # it was waiting for.
  echo "   ACA stayed busy for ~$(( _ACA_RETRY_ATTEMPTS * _ACA_RETRY_SLEEP ))s; giving up." >&2
  cat "$err" >&2; rm -f "$err"; return 1
}

# Kept as the readiness probe's own name, delegating, so there is ONE matcher. When this had its
# own copy it recognised "conflicting concurrent write" and not ContainerAppOperationInProgress —
# so the probe write survived a busy ACA and the image update beside it did not.
_readiness_probe_retry() {
  _aca_retry "$@"
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
