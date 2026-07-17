"""F6 (ADR 0026 Epic 2) — honest examined-element denominators.

"of 18 images examined" must be an ENGINE-REPORTED count (classify() walks every raster media
part / PDF page at scan time), surfaced only when it exists — never estimated (ADR 0016).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "examined.db")
    return store_mod.Store()


def test_examined_returns_the_latest_classified_counts(st):
    st.upsert_document("d1", source="drive", path="deck.pptx", content_hash="h1", owner="o",
                       created_at="2026-07-10T00:00:00Z", last_seen="2026-07-10T00:00:00Z",
                       triage_score=1, triage_rationale="r",
                       classify={"pages": 12, "images": 18, "has_text": True,
                                 "has_images": True, "is_scanned": False, "doc_class": "deck"})
    row = st.get_document_examined("deck.pptx")
    assert row and row["images"] == 18 and row["pages"] == 12


def test_never_classified_returns_none(st):
    st.upsert_document("d2", source="drive", path="plain.docx", content_hash="h2", owner="o",
                       created_at="2026-07-10T00:00:00Z", last_seen="2026-07-10T00:00:00Z",
                       triage_score=1, triage_rationale="r")     # no classify → no counts
    assert st.get_document_examined("plain.docx") is None       # absent, not zero-filled
    assert st.get_document_examined("never-seen.pdf") is None


def test_wiring_pins():
    """The route + drawer surface the counts only where they are honest."""
    scans = (ACP / "api" / "routes" / "scans.py").read_text()
    assert '"/scans/{sid}/files/{filename:path}/examined"' in scans
    assert "get_document_examined" in scans
    drawer = (ACP / "frontend" / "src" / "FileDrawer.jsx").read_text()
    # denominator gated on BOTH the criterion set and a reported count — nothing estimated
    assert "IMAGE_CRITERIA.has(r.id) && examined?.images != null" in drawer
    assert "new Set(['1.1.1', '1.4.5', '1.4.9'])" in drawer
    api = (ACP / "frontend" / "src" / "api.js").read_text()
    assert "getExamined" in api
