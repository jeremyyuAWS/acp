from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "release.db")
    return store_mod.Store()


def test_release_projection_scopes_files_and_joins_only_exact_call_ids(store):
    selected = store.record_ai_call(surface="vision", provider="openai", model="gpt-5",
                                    zone="cloud", latency_ms=100, ok=True,
                                    scan_id="s1", file="selected.docx")
    other = store.record_ai_call(surface="vision", provider="openai", model="gpt-5",
                                 zone="cloud", latency_ms=100, ok=True,
                                 scan_id="s1", file="other.docx")
    store.record_hitl_event("s1", "selected.docx", "1.1.1", "linked", "edit",
                            model_call_id=selected)
    store.record_hitl_event("s1", "selected.docx", "1.1.1", "unlinked", "approve")
    # A durable id pointing at another file must not leak into this selection.
    store.record_hitl_event("s1", "selected.docx", "1.1.1", "wrong-file", "approve",
                            model_call_id=other)
    store.record_ai_validation_outcomes("s1", "selected.docx", "1.1.1", ["linked"],
                                        "verified_regressed", regressions=["2.4.4"])

    rows = store.release_ai_provenance("s1", ["selected.docx"])
    assert [row["id"] for row in rows] == [selected]
    assert [row["action"] for row in rows[0]["review_decisions"]] == ["edit"]
    assert rows[0]["validation_outcomes"][0]["outcome"] == "verified_regressed"
    assert rows[0]["validation_outcomes"][0]["regressions"] == ["2.4.4"]


def test_release_projection_preserves_missing_linkage_as_absence(store):
    store.record_ai_call(surface="text", provider="ollama", model="local", zone="local",
                         latency_ms=20, ok=True, scan_id="s1", file="selected.docx")
    [row] = store.release_ai_provenance("s1", ["selected.docx"])
    assert row["ok"] == 1
    assert row["review_decisions"] == []
    assert row["validation_outcomes"] == []


def test_release_api_owner_and_file_scope(monkeypatch):
    from routes import scans

    class FakeStore:
        def get_scan(self, sid, owner=None):
            assert owner == "owner@example.com"
            return {"files": [{"file": "selected.docx"}]}

        def release_ai_provenance(self, sid, files):
            assert (sid, files) == ("s1", ["selected.docx"])
            return [{"id": "call-1"}]

    monkeypatch.setattr(scans.core, "store", FakeStore())
    request = SimpleNamespace(state=SimpleNamespace(user_email="owner@example.com"))
    body = scans.ReleaseAiProvenanceRequest(files=["selected.docx", "selected.docx"])
    assert scans.release_ai_provenance("s1", request, body) == [{"id": "call-1"}]
    with pytest.raises(scans.HTTPException) as exc:
        scans.release_ai_provenance("s1", request,
                                    scans.ReleaseAiProvenanceRequest(files=["other.docx"]))
    assert exc.value.status_code == 404
