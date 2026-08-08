#!/usr/bin/env bash
# Register this container as an Azure Pipelines agent, run ONE job, and exit.
#
# The download URL is asked for rather than pinned. Agent versions roll forward and the
# server rejects an agent it considers too old, so a hardcoded tarball URL is a build that
# works until the day it does not — with a failure that looks like a network problem.
# `_apis/distributedtask/packages/agent` answers with what THIS org currently serves.
set -euo pipefail

if [ -z "${AZP_URL:-}" ] || [ -z "${AZP_TOKEN:-}" ]; then
  echo "AZP_URL and AZP_TOKEN are both required." >&2
  echo "Set them in deploy/compose/.env — never in the compose file, which is committed." >&2
  exit 1
fi

export AGENT_ALLOW_RUNASROOT=0
pool="${AZP_POOL:-acp-local}"
name="${AZP_AGENT_NAME:-$(hostname)}"
arch="$(cat /azp/.tool_arch)"

echo "Fetching the agent package the server expects (linux-${arch})…"
url="$(curl -fsSL -u "user:${AZP_TOKEN}" \
  "${AZP_URL%/}/_apis/distributedtask/packages/agent?platform=linux-${arch}&top=1" \
  | jq -r '.value[0].downloadUrl')"

if [ -z "${url}" ] || [ "${url}" = "null" ]; then
  # Almost always the token, and almost always its SCOPE rather than its validity: the
  # packages endpoint needs Agent Pools (read), which a token minted for code access does
  # not carry. It answers 200 with an empty list rather than 403, so this reads as "no
  # package for this platform" when it means "not allowed to see one".
  echo "Could not resolve an agent package. Check AZP_URL, and that AZP_TOKEN has" >&2
  echo "Agent Pools (read, manage) scope — an under-scoped token returns an empty list." >&2
  exit 1
fi

mkdir -p /azp/agent && cd /azp/agent
curl -fsSL "${url}" | tar -xz

cleanup() {
  # Without this the pool fills with dead entries — one per container start — and each
  # still counts toward the pool's agent list. --unattended so it never waits on a prompt
  # no one is watching.
  if [ -e ./config.sh ]; then
    ./config.sh remove --unattended --auth pat --token "${AZP_TOKEN}" || true
  fi
}
trap 'cleanup' EXIT

./config.sh --unattended \
  --agent "${name}" \
  --url "${AZP_URL}" \
  --auth pat \
  --token "${AZP_TOKEN}" \
  --pool "${pool}" \
  --work /azp/_work \
  --replace \
  --acceptTeeEula

# --once, deliberately. The agent takes a single job and exits, and compose restarts it
# clean. A long-lived agent accumulates state between unrelated runs, which is how a
# self-hosted lane starts passing builds that a fresh checkout would fail — the exact
# failure mode a hosted agent cannot have and the one worth engineering away up front.
#
# _work/ survives on a named volume, so the caches that make this fast (npm, pip, the
# .NET SDK, the tool cache) are NOT what gets discarded here. Only the process is.
exec ./run.sh --once
