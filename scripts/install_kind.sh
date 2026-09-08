#!/usr/bin/env bash
# Install kind, so the packaging reference cluster is a cluster rather than a render.
#
# SAME SHAPE AS install_helm.sh AND install_verapdf.sh, and for the same reason: kind is a Go
# binary and cannot be declared in tests/requirements.txt. It is deliberately NOT a third-party
# GitHub Action — every other binary this repository needs in CI arrives through a script it owns,
# with the version pinned here where a reviewer reading the packaging work can see it, rather than
# in an action whose own dependencies move independently.
#
# Idempotent, and safe to run when the tool is already present.
set -euo pipefail

VERSION="${ACP_KIND_VERSION:-0.25.0}"
TARGET="${ACP_KIND_DIR:-/usr/local/bin}"

if command -v kind >/dev/null 2>&1; then
    echo "install_kind: already present — $(kind --version 2>/dev/null || echo 'version unknown')"
    exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo "install_kind: unsupported architecture $ARCH" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://github.com/kubernetes-sigs/kind/releases/download/v${VERSION}/kind-linux-${ARCH}"
echo "install_kind: fetching $URL"
curl -fsSL --retry 3 --retry-delay 2 --max-time 180 "$URL" -o "$TMP/kind"
install -m 0755 "$TMP/kind" "$TARGET/kind"

# Verify the thing we just installed actually runs, rather than trusting that the copy succeeded.
# A binary for the wrong libc exits non-zero here instead of at `kind create cluster`, where it
# would read as a cluster problem.
kind --version
