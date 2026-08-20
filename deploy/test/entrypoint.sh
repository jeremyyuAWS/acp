#!/usr/bin/env bash
# Make the MOUNTED repo runnable, then get out of the way.
#
# Two things are true of a bind-mounted checkout that are not true of a baked image, and both
# produce failures that name the wrong cause:
#
#   1. The tree is owned by the host user, not by root, so every `git` call inside the
#      container dies with "detected dubious ownership in repository at '/app'". Five test
#      modules shell out to git, and so do two of the four checks the CI job runs.
#   2. bin/ is gitignored, so a fresh clone has no AcpScan.Cli.dll — and tests/engines.py
#      reads OFFICE_OK as false, which turns the Office suites into skips rather than
#      failures. Skipped-but-green is precisely the outcome this image exists to make
#      impossible, so the DLL is built here rather than assumed.
set -euo pipefail

REPO=${ACP_REPO:-/app}
DLL="$REPO/spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll"

if [ ! -d "$REPO/tests" ]; then
  echo "::error::$REPO does not look like the acp repo (no tests/ directory)." >&2
  echo "The test service bind-mounts the repo root at /app — check the compose volume." >&2
  exit 1
fi

# (1) git, for the five modules that shell out to it and for the matrix/backlog guards.
git config --global --add safe.directory "$REPO" 2>/dev/null || true

# (2) the Office analyser CLI.
#
# Built from the MOUNTED source, not copied from a prebuilt copy inside the image: a baked DLL
# would be whatever the .cs files said on image-build day, and it would keep passing after the
# analysers changed underneath it. NuGet packages are already in the image, so this is a
# compile rather than a package pull.
#
# It lands at the exact path tests/engines.py probes — spike/dotnet/AcpScan.Cli/bin/Release/
# net10.0/AcpScan.Cli.dll — because that default is what a developer's own `dotnet build`
# produces, and an ACP_OFFICE_CLI override here would make the image's OFFICE_OK true for a
# reason the host could never reproduce. bin/ is gitignored, so writing into the mount adds
# nothing to `git status`.
if [ "${ACP_REBUILD_ENGINE:-0}" = "1" ] || [ ! -f "$DLL" ]; then
  echo "==> building the Office analyser CLI (this happens once; the output is gitignored)"
  dotnet build "$REPO/spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj" -c Release --nologo
fi

if [ -f "$DLL" ]; then
  echo "==> Office engine: $DLL"
else
  # Not fatal, and not silent either. The suites gated on OFFICE_OK will SKIP with the reason
  # tests/engines.py states; that is a legible outcome, whereas a green run that never says
  # the engine was missing is the failure mode this whole image is aimed at.
  echo "::warning::the Office analyser CLI was NOT built — Office-gated suites will SKIP." >&2
fi

exec "$@"
