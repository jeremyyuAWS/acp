"""A local-zone managed run drafts on the keyless floor instead of deferring.

THE BUG THIS EXISTS TO PREVENT. `ai_zone='local'` was accepted by the run policy and read by
nothing in the dispatch path, so `ai.suggest_fix` hit `if _managed_run is not None: defer` and
returned no draft at all. The plan offered "keep AI on our own infrastructure", the run started,
and it generated nothing — the failure mode this codebase keeps writing down, where a true state
(no cloud budget) is reported as a working one.

The fix is scoped by the RUN's zone, not by the cloud path's availability, so the two managed
cases below must stay opposite: a local run reaches Ollama, and every other managed run still
defers exactly as before.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai as _ai  # noqa: E402
import llm_waterfall_provider as _wf  # noqa: E402


class Ctx:
    """Only what suggest_fix reads off a run context."""
    def __init__(self, local_drafting, enabled=False):
        # `enabled` is the CLOUD gate and is false for the zero-cap local run this covers —
        # which is why the cloud seam defers and the floor has to be reachable past it.
        self.local_drafting, self.enabled = local_drafting, enabled
        self.scan_id, self.file, self.deferred = "scan", "doc.docx", []


@pytest.fixture
def floor(monkeypatch):
    """The local Ollama floor, answering; no cloud provider configured."""
    monkeypatch.setattr(_ai, "_prov", types.SimpleNamespace(
        text_generate=lambda *a, **kw: None), raising=False)
    posted = {}

    def fake_post(url, **kwargs):
        posted["url"] = url
        return types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"response": "Quarterly revenue by region.",
                          "prompt_eval_count": 10, "eval_count": 5})

    monkeypatch.setattr("httpx.post", fake_post)
    return posted


def _managed(monkeypatch, context):
    monkeypatch.setattr(_wf, "managed_context", lambda: context)
    monkeypatch.setattr(_ai, "managed_context", lambda: context, raising=False)


def test_a_local_zone_run_gets_a_draft_from_the_floor(monkeypatch, floor):
    _managed(monkeypatch, Ctx(local_drafting=True))
    out = _ai.suggest_fix("2.4.4", "Link Purpose", "click here", "doc.docx")
    assert out is not None, "a local-zone run must draft, not defer"
    assert out["suggestion"] == "Quarterly revenue by region."
    assert "/api/generate" in floor["url"]


def test_the_local_draft_still_requires_approval_and_reports_its_real_zone(monkeypatch, floor):
    """Same managed bookkeeping the cloud branch returns.

    Nothing downstream should have to know which path drew a draft — and an unapproved draft
    that omitted `approval_required` would read as one that had already cleared review.
    """
    _managed(monkeypatch, Ctx(local_drafting=True))
    out = _ai.suggest_fix("2.4.4", "Link Purpose", "click here", "doc.docx")
    assert out["approval_required"] is True
    assert out["provider"] == "ollama"
    assert out["cost_usd"] == 0.0
    assert out["processing_zone"] == _ai.provenance().get("zone")


def test_a_managed_run_that_is_not_local_still_defers(monkeypatch, floor):
    """The other half. Reaching the floor must be the RUN's zone talking, not the cloud path
    merely being unavailable — otherwise every cloud run silently degrades to local drafting
    off-budget, which is the opposite of what the budget gate is for."""
    context = Ctx(local_drafting=False)
    _managed(monkeypatch, context)
    assert _ai.suggest_fix("2.4.4", "Link Purpose", "click here", "doc.docx") is None
    assert "url" not in floor, "no local request may be made for a cloud-capable run"
    # It stops at whichever managed gate refuses first — here the cloud seam's own budget
    # check. Which reason is recorded is that gate's business; what this asserts is that the
    # run deferred and drew nothing, rather than falling through to the floor.
    assert [item["status"] for item in context.deferred] == ["deferred"]


def test_an_unmanaged_run_is_unaffected(monkeypatch, floor):
    _managed(monkeypatch, None)
    out = _ai.suggest_fix("2.4.4", "Link Purpose", "click here", "doc.docx")
    assert out is not None and "approval_required" not in out
