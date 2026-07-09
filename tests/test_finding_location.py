"""Per-finding location capture — the analysers already record page/slide; surface + persist it.

Foundation for "locate in document": the review UI renders the exact page instead of making a
reviewer hunt. Invariant: an unattributed finding stays NULL — we never default it to page 1.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402


# ── normalisation: .NET CLI dict + engine pydantic model → (page, location_text) ──

def test_loc_fields_from_dotnet_cli_dict():
    p, t = scanner._loc_fields({"pageNumber": None, "slideNumber": 3, "elementIndex": None,
                                "xPath": None, "description": "pptx:slide:2"})
    assert p == 3 and t == "pptx:slide:2"


def test_loc_fields_from_engine_model():
    class L:                       # duck-types the engine's pydantic IssueLocation
        page_number = 7
        slide_number = None
        description = None
        x_path = "/html/body/img[2]"
    p, t = scanner._loc_fields(L())
    assert p == 7 and t == "/html/body/img[2]"


def test_unattributed_location_is_none_never_page_one():
    assert scanner._loc_fields(None) == (None, None)
    assert scanner._loc_fields({}) == (None, None)
    assert scanner._loc_fields({"pageNumber": None, "slideNumber": None}) == (None, None)
    assert scanner._loc_fields({"pageNumber": 0}) == (None, None)   # 0 is not a valid 1-based page


def test_issue_with_loc_omits_unknown_keys():
    base = {"ruleId": "X", "wcag": "1.1.1", "severity": "CRITICAL"}
    out = scanner._issue_with_loc(dict(base), None)
    assert "page" not in out and "location" not in out              # absent = unknown, not invented
    out2 = scanner._issue_with_loc(dict(base), {"slideNumber": 2, "description": "pptx:slide:1"})
    assert out2["page"] == 2 and out2["location"] == "pptx:slide:1"


# ── persistence round-trip ──

@pytest.fixture()
def st():
    import store as store_mod
    store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "loc.db"
    store_mod._SCHEMA[:] = [x for x in store_mod._SCHEMA
                            if not x.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def _deck():
    return {"file": "deck.pptx", "engine": "dotnet/office", "status": "analysed", "score": 40,
            "compliant": 0, "skipped_rules": 0, "issues": [
                {"ruleId": "PPTX-TITLE-001", "wcag": "2.4.2 Page Titled", "severity": "SERIOUS",
                 "detail": "Slide is missing a title", "page": 3, "location": "pptx:slide:2"},
                {"ruleId": "PPTX-ALT-001", "wcag": "1.1.1 Non-text Content", "severity": "CRITICAL"},
            ]}


def test_page_location_round_trip(st):
    st.init_scan_run("s1", "drive", total=1, started_at="t0", rubric_name="r", rubric_hash="h")
    st.save_file_result("s1", _deck(), "t1")
    files = st.get_scan("s1")["files"]
    issues = {i["rule_id"]: i for i in files[0]["issues"]}
    assert issues["PPTX-TITLE-001"]["page"] == 3
    assert issues["PPTX-TITLE-001"]["location"] == "pptx:slide:2"
    # A finding the analyser could not place stays NULL — the UI shows no page rather than a wrong one.
    assert issues["PPTX-ALT-001"]["page"] is None
    assert issues["PPTX-ALT-001"]["location"] is None
