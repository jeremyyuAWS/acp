"""Round-trip regression for deterministic docx structural remediation (ADR 0012 program).

Builds a broken docx (multi-row table with no header row + a heading outline with no H1),
runs it through remediate_office, re-scans the output with the owned analyser CLI, and
asserts the WCAG 1.3.1 structural findings are gone (0 residual). Self-skips when the .NET
CLI / python-docx are unavailable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("docx")
from docx import Document  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import remediate_office as R  # noqa: E402

_ACP = Path(__file__).resolve().parents[1]
_DOTNET = Path(os.environ.get("ACP_DOTNET") or os.path.expanduser("~/.dotnet/dotnet"))
_CLI = Path(os.environ.get("ACP_OFFICE_CLI")
            or _ACP / "spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll")

pytestmark = pytest.mark.skipif(
    not _DOTNET.exists() or not _CLI.exists(),
    reason="office analyser CLI or dotnet runtime not built/available",
)


def _scan(indir: Path, out: Path) -> list[dict]:
    env = {**os.environ, "DOTNET_ROOT": os.path.expanduser("~/.dotnet")}
    subprocess.run([str(_DOTNET), str(_CLI), str(indir), str(out)],
                   capture_output=True, text=True, env=env, check=True)
    return json.loads(out.read_text())[0].get("issues", [])


def test_docx_structural_round_trip_clears_1_3_1(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir(); after.mkdir()

    d = Document()
    d.add_heading("First section", level=2)         # no Heading 1 anywhere
    d.add_paragraph("Body text with several words of content under the first section.")
    t = d.add_table(rows=3, cols=3)                 # multi-row table, no header row
    for row in t.rows:
        for i, cell in enumerate(row.cells):
            cell.text = f"cell {i}"
    d.add_heading("Second section", level=2)
    src = before / "broken.docx"
    d.save(src)

    fixed, applied, _ = R.remediate_office(src)
    assert fixed is not None
    (after / "broken.docx").write_bytes(Path(fixed).read_bytes())

    pre = _scan(before, tmp_path / "b.json")
    post = _scan(after, tmp_path / "a.json")

    pre_131 = [i for i in pre if i["wcag"] == "SC_1_3_1"]
    post_131 = [i for i in post if i["wcag"] == "SC_1_3_1"]
    assert len(pre_131) >= 2, f"fixture should trip table-header + no-H1: {pre_131}"
    assert post_131 == [], f"structural findings should clear after remediation: {post_131}"
