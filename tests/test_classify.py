"""ADR 0020 stage 2 — lightweight Discover-side classification (inventory, not conformance).

A cheap container peek only: page/slide/sheet counts, image count, has-text/has-images/
looks-scanned, rolled into a doc_class. NO WCAG rule runs here (that stays Assess); never
raises. Persisted additively on the documents table, so a classify-less re-run never wipes a
prior classification.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import classify as C  # noqa: E402


def _img(w=200, h=150) -> bytes:
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (w, h)).save(buf, format="PNG"); return buf.getvalue()


def _pptx(tmp_path, slides=2, images=1, text=True):
    p = tmp_path / "d.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i in range(1, slides + 1):
            body = "<a:t>Hello</a:t>" if text else ""
            z.writestr(f"ppt/slides/slide{i}.xml",
                       f'<p:sld xmlns:p="p" xmlns:a="a"><p:cSld>{body}</p:cSld></p:sld>')
        for i in range(images):
            z.writestr(f"ppt/media/image{i}.png", _img())
    return p


def _xlsx(tmp_path, sheets=3):
    p = tmp_path / "d.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i in range(1, sheets + 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       '<worksheet><sheetData><row><c><v>1</v></c></row></sheetData></worksheet>')
    return p


def test_pptx_is_a_slide_deck_with_real_counts(tmp_path):
    m = C.classify(_pptx(tmp_path, slides=4, images=3), ".pptx")
    assert m["doc_class"] == "slide-deck"
    assert m["pages"] == 4 and m["images"] == 3
    assert m["has_text"] is True and m["has_images"] is True and m["is_scanned"] is False


def test_xlsx_is_a_spreadsheet_with_sheet_count(tmp_path):
    m = C.classify(_xlsx(tmp_path, sheets=3), ".xlsx")
    assert m["doc_class"] == "spreadsheet" and m["sheets"] == 3


def test_image_heavy_docx_vs_text_docx(tmp_path):
    def _docx(images):
        p = tmp_path / f"d{images}.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", '<w:document xmlns:w="w"><w:body><w:t>Hi</w:t></w:body></w:document>')
            for i in range(images):
                z.writestr(f"word/media/image{i}.png", _img())
        return p
    assert C.classify(_docx(0), ".docx")["doc_class"] == "text-document"
    assert C.classify(_docx(6), ".docx")["doc_class"] == "image-heavy-document"


def test_never_raises_on_junk_or_unknown(tmp_path):
    junk = tmp_path / "x.pptx"; junk.write_bytes(b"not a zip")
    m = C.classify(junk, ".pptx")
    assert m["doc_class"] == "unknown" and m["images"] == 0 and m["has_text"] is False
    assert C.classify(tmp_path / "nope.rtf", ".rtf")["doc_class"] == "unknown"


# ── persistence round-trip: additive, never wipes a prior classification ────────

def test_upsert_persists_classify_and_does_not_wipe_on_rerun(isolated_store):
    s = isolated_store
    cls = {"pages": 4, "images": 3, "sheets": None, "has_text": True,
           "has_images": True, "is_scanned": False, "doc_class": "slide-deck"}
    s.upsert_document("doc1", source="drive", path="deck.pptx", content_hash="h1",
                      owner="a@x.io", created_at="2026-07-12T00:00:00", last_seen="2026-07-12T00:00:00",
                      triage_score=50, triage_rationale="r", classify=cls)
    d = s.get_document("doc1")
    assert d["doc_class"] == "slide-deck" and d["pages"] == 4 and d["images"] == 3
    assert d["has_text"] == 1 and d["is_scanned"] == 0 and d["classified_at"]
    # a later triage-only upsert (no classify) must NOT null the classification
    s.upsert_document("doc1", source="drive", path="deck.pptx", content_hash="h1",
                      owner="a@x.io", created_at="2026-07-12T00:00:00", last_seen="2026-07-12T01:00:00",
                      triage_score=60, triage_rationale="r2")
    d2 = s.get_document("doc1")
    assert d2["doc_class"] == "slide-deck" and d2["pages"] == 4   # preserved
    assert d2["triage_score"] == 60                               # triage still updated


def test_scanner_and_handlers_wire_classify_onto_the_upsert():
    api = Path(__file__).resolve().parent.parent / "api"
    scan = (api / "scanner.py").read_text()
    hand = (api / "handlers.py").read_text()
    assert 'fdict["classify"] = _cls.classify' in scan          # fan-out per-file
    assert 'r["classify"] = _cls.classify' in scan               # monolithic thread body
    assert '"classify": raw[k].get("classify")' in scan          # monolithic report assembly
    assert "classify=fdict.get(\"classify\")" in hand            # fan-out upsert twin
