"""docx 1.3.2 Meaningful Sequence — reading-order recommendations for floating text boxes/frames.
No safe silent fix (re-anchoring re-flows the page), so this is a deterministic proposal that
surfaces each floating box's own text with a 'move it inline here' recommendation."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import proposals  # noqa: E402


def _docx(tmp: Path, body: str) -> Path:
    p = tmp / "d.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')
    p.write_bytes(buf.getvalue())
    return p


def test_floating_textbox_gets_a_reading_order_recommendation(tmp_path):
    body = ('<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>'
            '<w:txbxContent><w:p><w:r><w:t>Sidebar: quarterly summary</w:t></w:r></w:p></w:txbxContent>')
    out = proposals.propose_reading_order(_docx(tmp_path, body), ".docx")
    assert len(out) == 1
    assert out[0]["sc"] == "1.3.2"
    assert "Sidebar: quarterly summary" in out[0]["proposed_value"]   # carries the box's own text
    assert out[0]["locator"] == "floating-text:1"


def test_positioned_frame_is_surfaced(tmp_path):
    body = '<w:p><w:pPr><w:framePr w:w="2000"/></w:pPr><w:r><w:t>Pull quote</w:t></w:r></w:p>'
    out = proposals.propose_reading_order(_docx(tmp_path, body), ".docx")
    assert len(out) == 1
    assert "Pull quote" in out[0]["proposed_value"]


def test_linear_document_yields_no_recommendation(tmp_path):
    body = "".join(f'<w:p><w:r><w:t>Paragraph {i}.</w:t></w:r></w:p>' for i in range(5))
    assert proposals.propose_reading_order(_docx(tmp_path, body), ".docx") == []


def test_empty_textbox_is_ignored(tmp_path):
    body = '<w:p><w:r><w:t>Body.</w:t></w:r></w:p><w:txbxContent><w:p></w:p></w:txbxContent>'
    assert proposals.propose_reading_order(_docx(tmp_path, body), ".docx") == []


def test_works_with_ai_off_deterministic(tmp_path):
    # No ai_enabled parameter — the recommendation is deterministic (text + placement), always available.
    body = '<w:txbxContent><w:p><w:r><w:t>Callout box</w:t></w:r></w:p></w:txbxContent>'
    assert proposals.propose_reading_order(_docx(tmp_path, body), ".docx")


def test_non_docx_yields_nothing(tmp_path):
    assert proposals.propose_reading_order(tmp_path / "x.pptx", ".pptx") == []
