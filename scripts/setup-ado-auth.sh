#!/usr/bin/env bash
# One-time setup for pushing/pulling this repo's Azure DevOps remote without a PAT.
#
#   ./scripts/setup-ado-auth.sh          # install
#   ./scripts/setup-ado-auth.sh --check  # report state, change nothing
#
# Points git at scripts/git-credential-ado.sh, which mints a short-lived AAD token from the
# `az` CLI on every call. Idempotent: safe to re-run.
set -euo pipefail

ACP="$(cd "$(dirname "$0")/.." && pwd)"
HELPER="$ACP/scripts/git-credential-ado.sh"
URL_KEY='credential.https://dev.azure.com.helper'
CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

[ -x "$HELPER" ] || { echo "not executable: $HELPER  (git add --chmod=+x)" >&2; exit 1; }

echo "== current state =="
echo "   helper script : $HELPER"
printf '   configured    : '
if git config --global --get-all "$URL_KEY" >/dev/null 2>&1; then
  git config --global --get-all "$URL_KEY" | sed -n '1p;2p' | tr '\n' '|' ; echo
else
  echo "(nothing)"
fi
printf '   system chain  : '
git config --system --get-all credential.helper 2>/dev/null | tr '\n' ' ' || true
echo

if $CHECK_ONLY; then
  echo
  echo "== --check: no changes made =="
  exit 0
fi

echo
echo "== configuring =="
# Order matters. The FIRST value is an empty string, which resets the helper chain inherited from
# the system/global config for this URL only. Without it, macOS's osxkeychain (set in Xcode's
# system gitconfig) runs first AND stores each minted token in the login keychain. The AAD token
# expires in ~90 min; the keychain entry does not. Git then serves a stale token, Azure DevOps
# answers 401, and you get an intermittent, misleading:
#
#     fatal: Authentication failed for 'https://dev.azure.com/...'
#
# GitHub and other hosts are untouched — this reset is scoped to the dev.azure.com URL.
git config --global --unset-all "$URL_KEY" 2>/dev/null || true
git config --global --add "$URL_KEY" ''
git config --global --add "$URL_KEY" "!$HELPER"
echo "   ✓ $URL_KEY = ['', !$HELPER]"

# Drop any token a previous (chained) osxkeychain run cached. Without this the stale token keeps
# being served until it is rejected, so the fix appears not to work.
if command -v git-credential-osxkeychain >/dev/null 2>&1 \
   || [ -x /Library/Developer/CommandLineTools/usr/libexec/git-core/git-credential-osxkeychain ]; then
  printf 'protocol=https\nhost=dev.azure.com\n\n' | git credential-osxkeychain erase 2>/dev/null || true
  echo "   ✓ cleared any cached dev.azure.com token from the login keychain"
fi

echo
echo "== verifying =="
if ! command -v az >/dev/null 2>&1; then
  echo "   ! 'az' is not on PATH — install the Azure CLI, then: az login" >&2
  exit 1
fi
if ! az account show >/dev/null 2>&1; then
  echo "   ! not logged in — run: az login" >&2
  exit 1
fi
echo "   ✓ az logged in as $(az account show --query user.name -o tsv 2>/dev/null)"

# The helper must emit a password on the happy path...
if printf '' | "$HELPER" get 2>/dev/null | grep -q '^password=.'; then
  echo "   ✓ helper mints a token"
else
  echo "   ✗ helper did not mint a token — run it directly to see az's error:" >&2
  echo "       $HELPER get" >&2
  exit 1
fi

# ...and git must actually reach the remote with it, if this repo has an ADO remote.
if git -C "$ACP" remote get-url origin 2>/dev/null | grep -q 'dev.azure.com'; then
  if git -C "$ACP" ls-remote --heads origin HEAD >/dev/null 2>&1; then
    echo "   ✓ git authenticates to the Azure DevOps remote"
  else
    echo "   ✗ git still cannot reach origin" >&2
    exit 1
  fi
fi

echo
echo "Done. Every git call to dev.azure.com now mints a fresh short-lived token; nothing is cached."
