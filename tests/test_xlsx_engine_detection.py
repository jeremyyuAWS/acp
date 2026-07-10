"""Regression guard for two vendored .NET xlsx-analyser detection gaps.

Both were found while building the demo fixtures — the fixtures had to sidestep them
(numeric hidden cell, TwoCellAnchor image), which meant real Excel files that use the
*common* forms were being under-scanned:

  * HiddenContentRule read only Cell.CellValue.Text, so inline-string content
    (t="inlineStr", openpyxl's default) looked empty and a hidden inline-string
    row/column was never flagged (1.3.2).
  * AltTextRule only walked TwoCellAnchor drawings, so a one-cell-anchored image
    (openpyxl's default, and common in hand-authored sheets) was never alt-checked (1.1.1).

This builds a workbook using exactly those forms and asserts both fire. It needs the
built .NET CLI to run, so it self-skips when the analysers didn't run (CLI not built).
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402


def _scs(fdict) -> set[str]:
    out = set()
    for i in fdict.get("issues", []):
        w = str(i.get("wcag", "")).strip()
        out.add(w[3:].replace("_", ".") if w.startswith("SC_") else w.split(" ", 1)[0])
    return out


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image

    d = tmp_path_factory.mktemp("xlsx-engine")
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Confidential hidden reconciliation notes"   # inline string (openpyxl default)
    ws.row_dimensions[1].hidden = True
    buf = io.BytesIO()
    Image.new("RGB", (200, 120), (30, 60, 110)).save(buf, format="PNG")
    ws.add_image(XLImage(io.BytesIO(buf.getvalue())), "C3")  # DEFAULT one-cell anchor, no alt
    name = "engine-detection.xlsx"
    wb.save(str(d / name))

    fdict, _ = scanner.analyse_and_assess(d, name, detect_pii=False)
    return {"scs": _scs(fdict),
            "engine_ran": any(str(i.get("wcag", "")).startswith("SC_") for i in fdict.get("issues", []))}


def test_hidden_inline_string_content_is_flagged(scanned):
    if not scanned["engine_ran"]:
        pytest.skip("the .NET office analysers did not run (CLI not built)")
    assert "1.3.2" in scanned["scs"], "hidden inline-string content was not detected (HiddenContentRule regressed)"


def test_one_cell_anchored_image_alt_is_flagged(scanned):
    if not scanned["engine_ran"]:
        pytest.skip("the .NET office analysers did not run (CLI not built)")
    assert "1.1.1" in scanned["scs"], "one-cell-anchored image alt gap not detected (AltTextRule regressed)"
