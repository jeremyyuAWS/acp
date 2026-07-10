"""ACP's own remediated copy must not be counted as a document in the user's estate.

Live symptom: a Drive holding ONE deck reported "2 total scanned · 1 duplicate · 1 remediated ✓",
and a worker spent 16 minutes remediating the phantom `… (1).pptx`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
from store import logical_name, shadowed_acp_outputs  # noqa: E402


def f(name, stamped=False):
    return {"file": name, "acp_stamped": "2026-07-09" if stamped else None}


# ── logical_name ──

def test_logical_name_strips_the_dedupe_suffix():
    assert logical_name("deck (1).pptx") == "deck.pptx"
    assert logical_name("deck (12).pptx") == "deck.pptx"
    assert logical_name("deck.pptx") == "deck.pptx"
    assert logical_name("report (draft).pdf") == "report (draft).pdf"   # not a numeric suffix
    assert logical_name("") == ""


# ── the discriminator ──

def test_acp_copy_shadowing_its_source_is_dropped():
    files = [f("deck.pptx"), f("deck (1).pptx", stamped=True)]
    assert shadowed_acp_outputs(files) == {"deck (1).pptx"}


def test_it_is_the_stamp_that_decides_not_the_suffix():
    # _dedupe_names renames whichever item Drive returned SECOND — that may be the original.
    # If we keyed off " (1)" we would drop the user's real document and keep ACP's copy.
    files = [f("deck.pptx", stamped=True), f("deck (1).pptx")]
    assert shadowed_acp_outputs(files) == {"deck.pptx"}


def test_a_published_certified_document_standing_alone_is_never_dropped():
    # Publish writes the certified doc back into the estate. It carries the ACP stamp but has
    # no unstamped twin — it IS the document now, and must still be scanned and monitored.
    assert shadowed_acp_outputs([f("policy.pdf", stamped=True)]) == set()


def test_two_acp_copies_with_no_source_present_are_both_kept():
    # Nothing here shadows a source document; dropping both would hide the estate entirely.
    files = [f("a.pptx", stamped=True), f("a (1).pptx", stamped=True)]
    assert shadowed_acp_outputs(files) == set()


def test_unstamped_duplicates_are_left_alone():
    # Two genuine same-named uploads. Not ACP's doing — the duplicates panel handles them.
    files = [f("deck.pptx"), f("deck (1).pptx")]
    assert shadowed_acp_outputs(files) == set()


def test_unrelated_documents_are_untouched():
    # b.pdf is stamped but stands alone under its own name -> kept.
    files = [f("a.pptx"), f("b.pdf", stamped=True), f("c.docx")]
    assert shadowed_acp_outputs(files) == set()


def test_only_the_stamped_member_of_the_group_is_dropped():
    files = [f("deck.pptx"), f("deck (1).pptx", stamped=True), f("other.pdf")]
    shadowed = shadowed_acp_outputs(files)
    assert shadowed == {"deck (1).pptx"}
    kept = [x["file"] for x in files if x["file"] not in shadowed]
    assert kept == ["deck.pptx", "other.pdf"]


def test_empty_input():
    assert shadowed_acp_outputs([]) == set()


# ── the filter actually applies at the read path the whole UI uses ──

def test_get_scan_hides_the_shadowing_copy_and_its_findings(tmp_path, monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp_path / "shadow.db")
    st = store_mod.Store()
    st.init_scan_run("s1", "drive", total=2, started_at="t0", rubric_name="r", rubric_hash="h")

    def rec(name, stamped):
        return {"file": name, "engine": "dotnet/office", "status": "analysed", "score": 40,
                "compliant": 0, "skipped_rules": 0, "acp_stamped": stamped,
                "issues": [{"ruleId": "PPTX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"}]}

    st.save_file_result("s1", rec("deck.pptx", None), "t1")
    st.save_file_result("s1", rec("deck (1).pptx", "2026-07-09"), "t1")

    files = st.get_scan("s1")["files"]
    assert [f["file"] for f in files] == ["deck.pptx"]     # one document, not two

    # The row is filtered from the read, not deleted — the evidence survives.
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT file FROM file_records WHERE scan_id=%s ORDER BY file", ("s1",))
        assert len(st._db.fetchall(cur)) == 2
