#!/usr/bin/env bash
# Install helm, so the chart render tests RUN rather than skip.
#
# WHY THIS IS A SCRIPT AND NOT A PIP LINE, and why it is not `continue-on-error`. helm is a Go
# binary; it cannot be declared in tests/requirements.txt. tests/test_packaging_chart.py degrades
# to a skip when it is missing — correct on a developer machine, and exactly the wrong thing here,
# where a skipped render is a chart nothing evaluated. The whole packaging contract (ADR 0048's
# "one application package, per-cloud adapters") is asserted by rendering four platforms and
# comparing the manifests; without helm, all of that passes by not running.
#
# That failure mode is why test_packaging_chart.py::test_ci_has_helm FAILS when CI is set and helm
# is absent, instead of skipping with the rest. This script is the other half of the same rule —
# the same shape as install_verapdf.sh, for the same reason.
#
# Idempotent, and safe to run when the tool is already present.
set -euo pipefail

VERSION="${ACP_HELM_VERSION:-3.16.3}"
TARGET="${ACP_HELM_DIR:-/usr/local/bin}"

if command -v helm >/dev/null 2>&1; then
    echo "install_helm: already present — $(helm version --short 2>/dev/null || echo 'version unknown')"
    exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo "install_helm: unsupported architecture $ARCH" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://get.helm.sh/helm-v${VERSION}-linux-${ARCH}.tar.gz"
echo "install_helm: fetching $URL"
curl -fsSL --retry 3 --retry-delay 2 --max-time 180 "$URL" -o "$TMP/helm.tar.gz"
tar -xzf "$TMP/helm.tar.gz" -C "$TMP"
install -m 0755 "$TMP/linux-${ARCH}/helm" "$TARGET/helm"

# Verify the thing we just installed actually runs, rather than trusting that the copy succeeded.
# An unpacked binary for the wrong libc exits non-zero here instead of at the first test that
# needs it, where it would read as a chart problem.
helm version --short
