#!/bin/sh
# Git credential helper for Azure DevOps — mints a short-lived AAD access token from the
# already-authenticated `az` CLI. No PAT is stored, and nothing is written to disk.
#
# Install with:  ./scripts/setup-ado-auth.sh
#
# Git calls this with "get" and reads username/password from stdout. "store" and "erase" are
# no-ops: the token is short-lived by design, and caching it defeats the design (see below).
#
# ── Why the install script also has to reset the helper chain ────────────────────────────────
# macOS ships `credential.helper = osxkeychain` in Xcode's SYSTEM gitconfig
# (/Library/Developer/CommandLineTools/usr/share/git-core/gitconfig), so it applies even with an
# empty ~/.gitconfig. Configure this helper for the dev.azure.com URL without resetting that
# chain and osxkeychain runs FIRST, *and* git stores every token we mint into the login keychain.
#
# The AAD token lives ~90 minutes. The keychain entry never expires. So once a token was cached,
# git kept serving the stale one, Azure DevOps answered 401, and the operator saw
#
#     fatal: Authentication failed for 'https://dev.azure.com/...'
#
# intermittently — recovering only when git erased the rejected credential and asked again. The
# credential was never wrong; it was expired, and it should never have been kept. setup-ado-auth.sh
# writes an empty `helper =` entry before this one, which resets the inherited chain for that URL
# only. GitHub and every other host keep using osxkeychain.
#
# ── Why failure prints nothing ───────────────────────────────────────────────────────────────
# On failure this must NOT print `password=` with an empty value. Git reads an empty password as a
# credential the server rejected, and reports the same misleading "Authentication failed" — when in
# truth the token was never minted. The original helper also sent `az`'s stderr to /dev/null, so the
# real reason was thrown away. Print nothing, explain on stderr, exit non-zero.
set -u

RESOURCE=499b84ac-1321-427f-aa17-267ca6975798   # Azure DevOps
ATTEMPTS=3

[ "${1:-}" = "get" ] || exit 0                  # store / erase: deliberate no-ops

command -v az >/dev/null 2>&1 || {
  echo "git-credential-ado: the 'az' CLI is not on PATH; cannot mint an Azure DevOps token." >&2
  exit 1
}

err=$(mktemp -t gitcredado) || { echo "git-credential-ado: mktemp failed" >&2; exit 1; }
trap 'rm -f "$err"' EXIT HUP INT TERM

# Retry once or twice: when several tools share ~/.azure/azureProfile.json, a concurrent write
# (`az account set`) can make an unrelated `az` call fail transiently. Costs latency only on a
# path that was about to fail anyway.
token=''
i=1
while [ "$i" -le "$ATTEMPTS" ]; do
  token=$(az account get-access-token --resource "$RESOURCE" --query accessToken -o tsv 2>"$err")
  rc=$?
  [ "$rc" -eq 0 ] && [ -n "$token" ] && break
  token=''
  [ "$i" -lt "$ATTEMPTS" ] && sleep 1
  i=$((i + 1))
done

if [ -z "$token" ]; then
  echo "git-credential-ado: could not mint an Azure DevOps token after $ATTEMPTS attempts." >&2
  echo "git-credential-ado: this is an 'az' failure, NOT a rejected git credential." >&2
  echo "git-credential-ado:   - session expired?  run: az login" >&2
  echo "git-credential-ado:   - otherwise, likely transient contention on a shared ~/.azure profile" >&2
  if [ -s "$err" ]; then
    echo "git-credential-ado: last stderr from az ---" >&2
    sed 's/^/  /' "$err" >&2
  fi
  exit 1
fi

echo "username=azuretoken"
echo "password=$token"
