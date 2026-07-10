"""The remediation worker must never remediate ACP's own output.

POST /scans/{sid}/remediate already cannot enqueue one: it iterates get_scan's filtered file
list. But jobs are DURABLE. A remediate_file job queued before that filter existed — or
retried out of the dead-letter — still reaches the worker, downloads the phantom, and spends
a 60-second llava call describing an image ACP itself wrote. Live evidence (Langfuse): 47 of
90 traced vision calls described 'Movate_AccessOps_Healthcare_v6 (1).pptx'.

The guard must fire BEFORE the download, or the phantom has already cost us the fetch.
"""
import sys
import tempfile
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "rsk.db")
    return store_mod.Store()


def _rec(name, stamped, issues=True):
    return {"file": name, "engine": "office", "status": "analysed", "score": 40, "compliant": 0,
            "skipped_rules": 0, "acp_stamped": stamped,
            "issues": [{"ruleId": "PPTX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"}] if issues else []}


def _shadow_pair(store, sid="s1"):
    store.init_scan_run(sid, "drive", 2, "t0", "r", "h")
    store.save_file_result(sid, _rec("deck.pptx", None), "t1")
    store.save_file_result(sid, _rec("deck (1).pptx", "2026-07-09"), "t1")


def _run(monkeypatch, store, filename, *, sid="s1"):
    """Drive the real handler. Any Drive access is a test failure."""
    import core, handlers
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(handlers, "_drive_client",
                        lambda *a, **k: pytest.fail("downloaded a file it should have skipped"))
    handlers._remediate_file(
        {"scan_id": sid, "file": filename, "drive_file_id": "drv1", "drive_token": "t"},
        {"scan_id": sid})


# ── the store predicate ───────────────────────────────────────────────────────

def test_predicate_flags_only_the_shadowing_copy(store):
    _shadow_pair(store)
    assert store.is_shadowed_output("s1", "deck (1).pptx") is True
    assert store.is_shadowed_output("s1", "deck.pptx") is False


def test_a_stamped_file_standing_alone_is_not_a_shadow(store):
    """A certified document published back into the estate shadows nothing."""
    store.init_scan_run("s2", "drive", 1, "t0", "r", "h")
    store.save_file_result("s2", _rec("published.pptx", "2026-07-09"), "t1")
    assert store.is_shadowed_output("s2", "published.pptx") is False


def test_a_scan_that_never_recorded_stamps_flags_nothing(store):
    """Data-dependent by construction: NULL stamps cannot be told from a real document.
    This is why the 2026-07-09 scans still remediated their copies."""
    store.init_scan_run("s3", "drive", 2, "t0", "r", "h")
    store.save_file_result("s3", _rec("deck.pptx", None), "t1")
    store.save_file_result("s3", _rec("deck (1).pptx", None), "t1")   # pre-stamping scan
    assert store.is_shadowed_output("s3", "deck (1).pptx") is False


# ── the worker guard ──────────────────────────────────────────────────────────

def test_worker_skips_the_shadow_copy_before_downloading_it(monkeypatch, store):
    _shadow_pair(store)
    _run(monkeypatch, store, "deck (1).pptx")      # _drive_client would pytest.fail
    acts = [d["action"] for d in store.list_decisions("s1")]
    assert "remediate.skipped" in acts


def test_the_skip_is_recorded_against_the_file_with_a_reason(monkeypatch, store):
    _shadow_pair(store)
    _run(monkeypatch, store, "deck (1).pptx")
    d = next(d for d in store.list_decisions("s1") if d["action"] == "remediate.skipped")
    assert d["file"] == "deck (1).pptx"
    assert "shadowing its source" in d["detail"]


def test_the_real_document_is_NOT_skipped(monkeypatch, store):
    """The guard must not swallow the document the reviewer actually cares about. It gets
    past the guard and reaches the download (which this test stubs to fail loudly)."""
    _shadow_pair(store)
    import core, handlers
    monkeypatch.setattr(core, "store", store)
    reached = {}
    def _boom(*a, **k):
        reached["download"] = True
        raise RuntimeError("stop here — we only needed to prove the guard let it through")
    monkeypatch.setattr(handlers, "_drive_client", _boom)
    with pytest.raises(Exception):
        handlers._remediate_file(
            {"scan_id": "s1", "file": "deck.pptx", "drive_file_id": "drv1", "drive_token": "t"},
            {"scan_id": "s1"})
    assert reached.get("download") is True
    assert "remediate.skipped" not in [d["action"] for d in store.list_decisions("s1")]
