"""content_type: SharePoint's Content Type column, persisted and read back through
scan_inventory. Verifies the round trip and the one behaviour that had to be deliberate — a
re-list must never blank out a content type it already recorded."""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "invct.db")
    return store_mod.Store()


def test_content_type_round_trips(st):
    st.add_inventory("s1", [{"file": "policy.docx", "content_type": "Policy"}])
    assert st.list_inventory("s1")[0]["content_type"] == "Policy"


def test_absent_for_every_source_that_never_supplies_one(st):
    # Drive / local / a SharePoint tenant that returned nothing — the column exists and is None,
    # not missing, not an error.
    st.add_inventory("s1", [{"file": "a.docx"}])
    assert st.list_inventory("s1")[0]["content_type"] is None


def test_a_re_list_does_not_blank_out_a_recorded_content_type(st):
    # THE CASE THAT MATTERS. Enrichment is best-effort per scan (scanner._sp_enrich_content_types'
    # circuit breaker can disable it partway through), so a re-list of the same file may genuinely
    # get no answer this time. Overwriting a real value with that "no answer" would throw away a
    # fact that was true and replace it with a gap — worse than never having recorded it.
    st.add_inventory("s1", [{"file": "policy.docx", "content_type": "Policy"}])
    st.add_inventory("s1", [{"file": "policy.docx", "content_type": None}])
    assert st.list_inventory("s1")[0]["content_type"] == "Policy"


def test_a_re_list_CAN_still_update_it_when_a_real_answer_comes_back(st):
    # Not frozen forever — a genuine new answer (the library recategorised the document) must
    # still land. Only a NULL from a failed read is protected against.
    st.add_inventory("s1", [{"file": "policy.docx", "content_type": "Policy"}])
    st.add_inventory("s1", [{"file": "policy.docx", "content_type": "Retired Policy"}])
    assert st.list_inventory("s1")[0]["content_type"] == "Retired Policy"


def test_paged_read_carries_it_too(st):
    st.add_inventory("s1", [{"file": "policy.docx", "content_type": "Policy"}])
    page = st.list_inventory_page("s1", limit=10, offset=0)
    assert page[0]["content_type"] == "Policy"
