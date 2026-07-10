#!/usr/bin/env bash
# One-time setup for pushing/pulling this repo's Azure DevOps remote without a PAT.
#
#   ./scripts/setup-ado-auth.sh          # install
#   ./scripts/setup-ado-auth.sh --check  # report state (incl. drift), change nothing
#
# INSTALLS A COPY of scripts/git-credential-ado.sh to a stable path outside the working tree,
# and points git at that copy. It must NOT point git at the in-repo path:
#
#   * a credential helper is machine-wide, but the working tree is per-branch. Check out a
#     branch created before the script existed — or any older branch — and the helper vanishes
#     mid-session, breaking every `git fetch` against Azure DevOps, including the one you would
#     use to get it back;
#   * worktrees and multiple clones each have their own copy at their own path.
#
# The repo copy stays the source of truth; `--check` reports drift between the two.
set -euo pipefail

ACP="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ACP/scripts/git-credential-ado.sh"
DEST_DIR="${ACP_HELPER_DIR:-$HOME/.local/bin}"
DEST="$DEST_DIR/git-credential-ado.sh"
URL_KEY='credential.https://dev.azure.com.helper'
LEGACY="$HOME/.git-credential-ado.sh"

CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

[ -f "$SRC" ] || { echo "missing: $SRC" >&2; exit 1; }

echo "== current state =="
echo "   repo copy     : $SRC"
echo "   installed to  : $DEST $([ -f "$DEST" ] || echo '(not yet)')"
if [ -f "$DEST" ]; then
  if cmp -s "$SRC" "$DEST"; then
    echo "   drift         : none"
  else
    echo "   drift         : INSTALLED COPY DIFFERS from the repo — re-run this script"
  fi
fi
printf '   git config    : '
git config --global --get-all "$URL_KEY" 2>/dev/null | tr '\n' '|' || printf '(nothing)'
echo
[ -f "$LEGACY" ] && echo "   legacy helper : $LEGACY (superseded; safe to delete once this is installed)"

if $CHECK_ONLY; then
  echo
  echo "== --check: no changes made =="
  exit 0
fi

echo
echo "== installing =="
mkdir -p "$DEST_DIR"
install -m 0755 "$SRC" "$DEST"
echo "   ✓ copied to $DEST (mode 0755)"

# Order matters. The FIRST value is an empty string, which resets the helper chain inherited from
# the system/global config for this URL only. Without it, macOS's osxkeychain (set in Xcode's
# system gitconfig, so it applies even with an empty ~/.gitconfig) runs first AND stores each
# minted token in the login keychain. The AAD token expires in ~90 min; the keychain entry does
# not. Git then serves a stale token, Azure DevOps answers 401, and you get an intermittent:
#
#     fatal: Authentication failed for 'https://dev.azure.com/...'
#
# GitHub and other hosts are untouched — the reset is scoped to the dev.azure.com URL.
git config --global --unset-all "$URL_KEY" 2>/dev/null || true
git config --global --add "$URL_KEY" ''
git config --global --add "$URL_KEY" "!$DEST"
echo "   ✓ $URL_KEY = ['', !$DEST]"

# Drop any token a previous (chained) osxkeychain run cached. Without this the stale token keeps
# being served until it is rejected, so the fix appears not to work.
if command -v git-credential-osxkeychain >/dev/null 2>&1 \
   || [ -x /Library/Developer/CommandLineTools/usr/libexec/git-core/git-credential-osxkeychain ]; then
  printf 'protocol=https\nhost=dev.azure.com\n\n' | git credential-osxkeychain erase 2>/dev/null || true
  echo "   ✓ cleared any cached dev.azure.com token from the login keychain"
fi

echo
echo "== verifying =="
command -v az >/dev/null 2>&1 || { echo "   ! 'az' not on PATH — install the Azure CLI, then: az login" >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "   ! not logged in — run: az login" >&2; exit 1; }
echo "   ✓ az logged in as $(az account show --query user.name -o tsv 2>/dev/null)"

if printf '' | "$DEST" get 2>/dev/null | grep -q '^password=.'; then
  echo "   ✓ installed helper mints a token"
else
  echo "   ✗ helper did not mint a token — run it directly to see az's error:" >&2
  echo "       $DEST get" >&2
  exit 1
fi

if git -C "$ACP" remote get-url origin 2>/dev/null | grep -q 'dev.azure.com'; then
  git -C "$ACP" ls-remote --heads origin HEAD >/dev/null 2>&1 \
    && echo "   ✓ git authenticates to the Azure DevOps remote" \
    || { echo "   ✗ git still cannot reach origin" >&2; exit 1; }
fi

echo
echo "Done. Every git call to dev.azure.com mints a fresh short-lived token; nothing is cached."
echo "The helper lives outside the working tree, so switching branches cannot remove it."
[ -f "$LEGACY" ] && echo "You can now delete the superseded copy:  rm $LEGACY"
exit 0
