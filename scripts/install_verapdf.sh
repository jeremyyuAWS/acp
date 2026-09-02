#!/usr/bin/env bash
# Install veraPDF for the PDF/UA-1 conformance gate.
#
# WHY THIS IS A SCRIPT AND NOT A PIP LINE. veraPDF is a Java application, so it cannot be declared
# in tests/requirements.txt the way weasyprint is. tests/verapdf.py degrades to a stated skip when
# it is missing — which is correct behaviour for a developer machine and exactly the wrong thing
# on CI, where a skipped conformance check is a compliance claim nothing evaluated. That is the
# silent-skip shape tests/test_undeclared_importorskip.py was written to refuse; this script is
# the other half of the same rule, for the dependency that has no wheel.
#
# Idempotent, and safe to run when the tool is already present.
set -euo pipefail

VERSION="${ACP_VERAPDF_VERSION:-1.30.2}"
TARGET="${ACP_VERAPDF_DIR:-/opt/verapdf}"

if [ -x "$TARGET/verapdf" ]; then
    echo "install_verapdf: already present at $TARGET/verapdf"
    "$TARGET/verapdf" --version 2>/dev/null | head -1 || true
    exit 0
fi

# veraPDF 1.30 requires a JRE; 21 is what the runners carry and what this was validated against.
if ! command -v java >/dev/null 2>&1; then
    echo "install_verapdf: no java on PATH — veraPDF needs a JRE (21 works)" >&2
    exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "install_verapdf: fetching greenfield installer $VERSION"
curl -sSL --retry 3 --retry-delay 2 \
     -o "$WORK/verapdf.zip" \
     "https://software.verapdf.org/releases/verapdf-installer.zip"
unzip -q -o "$WORK/verapdf.zip" -d "$WORK/vp"

JAR="$(find "$WORK/vp" -name 'verapdf-izpack-installer-*.jar' -print -quit)"
if [ -z "$JAR" ]; then
    echo "install_verapdf: no izpack installer in the archive" >&2
    exit 1
fi

# IzPack auto-install. Only the CLI and batch packs — the GUI, docs, sample plugins and validation
# model are dead weight on a runner.
cat > "$WORK/auto.xml" <<XML
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<AutomatedInstallation langpack="eng">
  <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>
  <com.izforge.izpack.panels.target.TargetPanel id="install_dir">
    <installpath>$TARGET</installpath>
  </com.izforge.izpack.panels.target.TargetPanel>
  <com.izforge.izpack.panels.packs.PacksPanel id="sdk_pack_select">
    <pack index="0" name="veraPDF GUI" selected="true"/>
    <pack index="1" name="veraPDF Batch files" selected="true"/>
    <pack index="2" name="veraPDF Validation model" selected="false"/>
    <pack index="3" name="veraPDF Documentation" selected="false"/>
    <pack index="4" name="veraPDF Sample Plugins" selected="false"/>
  </com.izforge.izpack.panels.packs.PacksPanel>
  <com.izforge.izpack.panels.install.InstallPanel id="install"/>
  <com.izforge.izpack.panels.finish.FinishPanel id="finish"/>
</AutomatedInstallation>
XML

java -jar "$JAR" "$WORK/auto.xml" >/dev/null
echo "install_verapdf: installed to $TARGET"
"$TARGET/verapdf" --version 2>/dev/null | head -1 || true
