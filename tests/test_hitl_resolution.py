"""WCAG-exception resolutions (the HITL-six close-out) — the two findings a model must not decide.

A reviewer can resolve a finding by applying the standard's own exception instead of authoring a
fix: 'decorative' (WCAG 1.1.1 — the image conveys nothing, so no text alternative is required) and
'essential_exception' (WCAG 1.4.5/1.4.9 — a logo/brand mark is exempt from images-of-text). The
resolution is recorded in the immutable audit trail as WHY the finding was resolved, and — crucially
— writes NO value into the document, so nothing is misrepresented as an authored fix.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "res.db")
    return store_mod.Store()


def _req(user_email="reviewer@example.com"):
    return SimpleNamespace(state=SimpleNamespace(user_email=user_email))


def _row(st, sid="s1", f="deck.pptx", rule="1.1.1"):
    st.init_scan_run(sid, "drive", 1, "t0", "r", "h")
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,remediated_at) "
            "VALUES(%s,%s,'office','fail',60,0,0,'2026-07-10T00:00:00')", (sid, f))
    st.queue_hitl_deferral(sid, f, "image lacks a faithful alt source", 1, rule_id=rule)
    return next(i for i in st.list_hitl_queue(scan_id=sid))


@pytest.fixture()
def route(st, monkeypatch):
    import core
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(core, "fire_webhook", lambda *a, **k: None, raising=False)
    jobs, decisions = [], []
    monkeypatch.setattr(st, "enqueue_job",
                        lambda name, payload, **k: jobs.append((name, payload)), raising=False)
    _orig = st.log_decision
    def _capture(actor, action, **k):
        decisions.append({"actor": actor, "action": action, **k})
        return _orig(actor, action, **k)
    monkeypatch.setattr(st, "log_decision", _capture, raising=False)
    from routes.hitl import hitl_update, HitlUpdate
    return hitl_update, HitlUpdate, jobs, decisions


def test_decorative_resolves_the_finding(st, route):
    hitl_update, HitlUpdate, _jobs, _dec = route
    row = _row(st, rule="1.1.1")
    hitl_update(row["id"], HitlUpdate(status="approved", resolution="decorative"), _req())
    assert st.get_hitl_item(row["id"])["status"] == "approved"


def test_decorative_records_the_exception_in_the_audit_trail(st, route):
    hitl_update, HitlUpdate, _jobs, decisions = route
    row = _row(st, rule="1.1.1")
    hitl_update(row["id"], HitlUpdate(status="approved", resolution="decorative"), _req())
    hitl_line = next(d for d in decisions if d["action"] == "hitl.approved")
    assert "decorative" in (hitl_line.get("detail") or "")
    assert "1.1.1" in (hitl_line.get("detail") or "")


def test_essential_exception_records_the_logo_exemption(st, route):
    hitl_update, HitlUpdate, _jobs, decisions = route
    row = _row(st, rule="1.4.5")
    hitl_update(row["id"], HitlUpdate(status="approved", resolution="essential_exception"), _req())
    hitl_line = next(d for d in decisions if d["action"] == "hitl.approved")
    assert "essential" in (hitl_line.get("detail") or "").lower()


def test_a_resolution_writes_no_value_into_the_document(st, route):
    """The whole point: an exception is NOT a written fix. No apply job may fire, or the report
    would claim alt text was authored when the reviewer explicitly said none was needed."""
    hitl_update, HitlUpdate, jobs, _dec = route
    row = _row(st, rule="1.1.1")
    hitl_update(row["id"], HitlUpdate(status="approved", resolution="decorative"), _req())
    assert not any(name == "apply_approved_values" for name, _ in jobs)


def test_an_unknown_resolution_is_rejected(st, route):
    from fastapi import HTTPException
    hitl_update, HitlUpdate, _jobs, _dec = route
    row = _row(st)
    with pytest.raises(HTTPException) as ei:
        hitl_update(row["id"], HitlUpdate(status="approved", resolution="made_up"), _req())
    assert ei.value.status_code == 422


def test_no_resolution_is_the_unchanged_default(st, route):
    """Every existing approval sends no resolution — behaviour must be identical to before."""
    hitl_update, HitlUpdate, _jobs, decisions = route
    row = _row(st, rule="1.1.1")
    hitl_update(row["id"], HitlUpdate(status="approved"), _req())
    hitl_line = next(d for d in decisions if d["action"] == "hitl.approved")
    assert "resolution:" not in (hitl_line.get("detail") or "")
