"""docx heading OUTLINE evidence — the document's real styled headings and a deterministic never-skip
correction of them, for a heading finding's Structure preview. Real extraction only, no fabrication."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import doc_structure  # noqa: E402


def _docx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def _h(level: int, text: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'


def test_heading_skip_yields_before_and_corrected_outline():
    data = _docx(_h(1, "Intro") + _h(3, "Details") + _h(2, "Summary"))
    out = doc_structure.heading_outline(data, ".docx")
    assert out is not None
    assert [h["level"] for h in out["before"]] == [1, 3, 2]
    assert [h["text"] for h in out["before"]] == ["Intro", "Details", "Summary"]
    assert [h["level"] for h in out["after"]] == [1, 2, 2]                    # never-skip
    assert [h["text"] for h in out["after"]] == ["Intro", "Details", "Summary"]  # texts unchanged


def test_document_opening_at_h2_is_corrected_to_a_single_h1():
    out = doc_structure.heading_outline(_docx(_h(2, "Opens deep") + _h(4, "Deeper")), ".docx")
    assert [h["level"] for h in out["after"]] == [1, 2]


def test_clean_outline_returns_none():
    assert doc_structure.heading_outline(_docx(_h(1, "A") + _h(2, "B") + _h(2, "C")), ".docx") is None


def test_single_heading_returns_none():
    assert doc_structure.heading_outline(_docx(_h(1, "Only")), ".docx") is None


def test_non_docx_and_empty_return_none():
    assert doc_structure.heading_outline(b"whatever", ".pdf") is None
    assert doc_structure.heading_outline(b"", ".docx") is None


def test_corrected_levels_is_deterministic_and_never_skips():
    assert doc_structure.corrected_levels([1, 3, 2]) == [1, 2, 2]
    assert doc_structure.corrected_levels([3, 1, 2]) == [1, 1, 2]
    assert doc_structure.corrected_levels([1, 2, 3]) == [1, 2, 3]   # already clean, unchanged


# --- table_structure: real cell grid + header-row association ---

def _tc(text: str) -> str:
    return f'<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'


def _tr(cells: list[str], header: bool = False) -> str:
    hdr = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return f'<w:tr>{hdr}{"".join(_tc(c) for c in cells)}</w:tr>'


def _table(rows: list[str]) -> str:
    return f'<w:tbl>{"".join(rows)}</w:tbl>'


def test_marked_header_row_is_reported_as_marked():
    body = _table([_tr(["Name", "Role"], header=True), _tr(["Ada", "Author"])])
    out = doc_structure.table_structure(_docx(body), ".docx")
    assert out is not None
    t = out["tables"][0]
    assert t["rows"] == [["Name", "Role"], ["Ada", "Author"]]
    assert t["headerRow"] == 0
    assert t["headerMarked"] is True
    assert t["truncated"] is False


def test_unmarked_table_defaults_to_first_row_and_reports_not_marked():
    body = _table([_tr(["Q", "A"]), _tr(["1", "2"]), _tr(["3", "4"])])
    out = doc_structure.table_structure(_docx(body), ".docx")
    t = out["tables"][0]
    assert t["headerRow"] == 0
    assert t["headerMarked"] is False   # the fix would mark it — we never claim it already is


def test_single_row_or_single_column_table_is_not_evidence():
    assert doc_structure.table_structure(_docx(_table([_tr(["only one row", "x"])])), ".docx") is None
    assert doc_structure.table_structure(_docx(_table([_tr(["a"]), _tr(["b"])])), ".docx") is None


def test_no_table_returns_none():
    assert doc_structure.table_structure(_docx(_h(1, "No tables here") + _h(2, "Nope")), ".docx") is None


def test_table_is_capped_and_marks_truncated():
    wide = [f"c{i}" for i in range(12)]
    rows = [_tr(wide) for _ in range(12)]
    out = doc_structure.table_structure(_docx(_table(rows)), ".docx")
    t = out["tables"][0]
    assert len(t["rows"]) == doc_structure._MAX_ROWS
    assert all(len(r) == doc_structure._MAX_COLS for r in t["rows"])
    assert t["truncated"] is True


def test_table_non_docx_and_empty_return_none():
    assert doc_structure.table_structure(b"whatever", ".pdf") is None
    assert doc_structure.table_structure(b"", ".docx") is None
