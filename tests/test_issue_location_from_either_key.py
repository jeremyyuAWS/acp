"""A finding's position is persisted whichever key the detector used for it.

THE DEFECT. `issue_records.location` was written from `i.get("location")` at both INSERT sites.
The vendored .NET rules write `location` ("docx:hyperlink:paragraph:115:url:…"); several
first-party Python detectors write `locator` ("word/header1.xml#Picture 1") — see
formats/docx/detectors/non_text_content.py. So every Python-detected finding was stored with
location NULL: the finding survived, the ability to point at the thing it is about did not, and
that column is what a review card reads.

Measured before the fix by saving one of each through save_file_result: "docx:image:3" stored
for the .NET finding, NULL for the Python one.

NOT A RENAME, and the distinction is the reason this is a fallback rather than a merge. The keys
are not synonyms elsewhere: a `locator` is a RESOLVABLE WRITE TARGET that apply_alt.parse_locator
turns back into an element, while `location` is a position string for a human. On a FINDING they
answer the same question and the locator is the better answer, because it is resolvable. Nothing
that consumes `locator` as a write target is touched, and the tests below pin that boundary.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import store as store_mod  # noqa: E402

DOTNET = {"ruleId": "DOCX-ALT-001", "wcag": "SC_1_1_1", "severity": "CRITICAL",
          "detail": "dotnet rule", "location": "docx:image:3"}
PYTHON = {"ruleId": "DOCX_IMAGE_NO_ALT", "wcag": "1.1.1 Non-text Content",
          "severity": "CRITICAL", "detail": "python detector",
          "locator": "word/header1.xml#Picture 1"}


# ── the accessor ──────────────────────────────────────────────────────────────

def test_it_reads_either_key():
    assert store_mod._issue_location(DOTNET) == "docx:image:3"
    assert store_mod._issue_location(PYTHON) == "word/header1.xml#Picture 1"


def test_location_wins_when_a_finding_carries_both():
    """`location` is the column's own name and the .NET vocabulary; if a finding somehow has
    both, the explicit one is authoritative rather than order-dependent."""
    both = {**DOTNET, "locator": "word/document.xml#Picture 9"}
    assert store_mod._issue_location(both) == "docx:image:3"


def test_a_finding_with_neither_stays_unknown():
    """Absent means unknown, never a fabricated position — the same rule `_issue_with_loc`
    already follows for pages."""
    assert store_mod._issue_location({"ruleId": "X"}) is None


def test_an_empty_string_is_not_a_position():
    assert store_mod._issue_location({"location": "", "locator": "word/x.xml#P1"}) \
        == "word/x.xml#P1"
    assert store_mod._issue_location({"location": "", "locator": ""}) in (None, "")


# ── the persistence boundary, which is where it was lost ──────────────────────

@pytest.fixture
def store(isolated_store):
    return isolated_store


def _save(st, sid, issues):
    st.init_scan_run(sid, "local", 1, "2026-08-08T00:00:00Z", "default", "rh",
                     owner="a@example.com", status="running")
    st.save_file_result(sid, {"file": "a.docx", "engine": ".net/office", "status": "analysed",
                              "score": 80, "compliant": 0, "skipped_rules": 0,
                              "issues": issues}, "2026-08-08T00:00:00Z")
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT rule_id, location FROM issue_records WHERE scan_id=%s", (sid,))
        return {r["rule_id"]: r["location"] for r in st._db.fetchall(cur)}


def test_both_engines_positions_survive_save_file_result(store):
    rows = _save(store, "s1", [DOTNET, PYTHON])
    assert rows["DOCX-ALT-001"] == "docx:image:3"
    assert rows["DOCX_IMAGE_NO_ALT"] == "word/header1.xml#Picture 1", (
        "a Python detector's finding was persisted with no position")


def test_the_locator_reaches_the_read_path_too(store):
    """Stored is not the same as returned. `get_scan` is what a review card actually reads.

    Note the key: findings are WRITTEN as `ruleId` and READ BACK as `rule_id`. That is a second
    instance of the same naming split this file is about, and it cost a first draft of this test
    — filtering on `ruleId` found nothing and looked like the finding had been lost. Left alone
    rather than folded into this change: it is a real inconsistency but a load-bearing one (the
    read shape is the row shape, and every consumer already expects it), so renaming it is its
    own change with its own blast radius.
    """
    _save(store, "s2", [PYTHON])
    scan = store.get_scan("s2", owner="a@example.com")
    issues = [i for f in scan["files"] for i in f.get("issues", [])]
    got = [i for i in issues if i.get("rule_id") == "DOCX_IMAGE_NO_ALT"]
    assert got, "the finding did not come back at all"
    assert got[0].get("location") == "word/header1.xml#Picture 1"


# ── the boundary that must NOT move ───────────────────────────────────────────

def test_a_proposals_locator_is_still_a_write_target_not_a_position():
    """The reason this is a fallback and not a rename.

    `apply_alt.parse_locator` resolves a proposal's `locator` back to an element in a part. That
    is a different job from "where is this finding", and collapsing the two vocabularies would
    have made a human-readable position string look like something the applier could resolve.
    """
    import apply_alt
    assert apply_alt.parse_locator("word/header1.xml#Picture 1") == (
        "word/header1.xml", "Picture 1")
    # A .NET position string is NOT resolvable, and must not become one by accident.
    assert apply_alt.parse_locator("docx:image:3") is None
