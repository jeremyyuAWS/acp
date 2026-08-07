"""GET /config must report the scope the SERVER is gating on.

The SPA used to hard-code `ACTIVE_SCOPE_PRESET = 'deva-final'` in activeScope.js, so changing
the `scan_scope` setting moved the server's gate while every denominator and "N of 20 in scope"
line in the UI kept describing the preset compiled into the bundle. This endpoint is the single
source the SPA now adopts, so what it reports has to be exactly what in_scope() enforces.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


class _Store:
    def __init__(self, scope_name=""):
        self._s = {"scan_scope": scope_name}

    def get_setting(self, key, default=None):
        return self._s.get(key, default)


@pytest.fixture()
def sysmod(monkeypatch):
    import core
    import routes.system as s
    monkeypatch.setattr(core, "store", _Store(), raising=False)
    return s, core


def test_no_scope_set_reports_no_restriction(sysmod):
    s, core = sysmod
    core.store._s["scan_scope"] = ""
    info = s._active_scope_info()
    # criteria None means NO NARROWING. It must never be an empty dict: the UI would render
    # "0 of 20 criteria in scope", which is the most alarming possible way to misreport.
    assert info == {"name": "", "criteria": None}


def test_a_configured_scope_reports_its_name_and_resolved_criteria(sysmod):
    s, core = sysmod
    core.store._s["scan_scope"] = "deva-final"
    info = s._active_scope_info()
    assert info["name"] == "deva-final"
    assert isinstance(info["criteria"], dict) and info["criteria"]
    # Formats are sorted lists, not sets — the payload has to be JSON-serialisable.
    for sc, fmts in info["criteria"].items():
        assert isinstance(fmts, list) and fmts == sorted(fmts)


def test_what_it_reports_matches_what_in_scope_actually_enforces(sysmod):
    """The whole point: the UI's arithmetic and the server's gate must not diverge."""
    s, core = sysmod
    from store import active_scope, in_scope
    core.store._s["scan_scope"] = "deva-final"
    info = s._active_scope_info()
    scope = active_scope(core.store)
    for sc, fmts in info["criteria"].items():
        for fmt in ("docx", "xlsx", "pptx", "pdf"):
            assert in_scope(sc, fmt, scope) == (fmt in fmts), f"{sc}/{fmt} disagrees"


def test_an_unreadable_scope_reports_no_restriction_not_an_empty_one(sysmod, monkeypatch):
    s, core = sysmod

    def _boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(core.store, "get_setting", _boom)
    assert s._active_scope_info() == {"name": "", "criteria": None}


# ── a scope written as DATA reports the same way a preset does ────────────────────────────────
def test_a_json_scope_reports_its_resolved_criteria(sysmod):
    """The SPA arithmetics over `criteria`, so a data scope must arrive in the same shape."""
    import json
    s, core = sysmod
    core.store._s["scan_scope"] = json.dumps({"1.4.3": ["docx", "pdf"], "2.4.2": ["docx"]})
    info = s._active_scope_info()
    assert info["criteria"] == {"1.4.3": ["docx", "pdf"], "2.4.2": ["docx"]}
    # Formats are sorted, not set-ordered — the payload has to be stable across processes or the
    # SPA's own diffing sees phantom changes.
    assert info["criteria"]["1.4.3"] == sorted(info["criteria"]["1.4.3"])


def test_a_json_scope_is_named_custom_not_dumped_raw(sysmod):
    """`name` is a label the UI puts in a chip. Raw JSON there would be a wall of text."""
    import json
    s, core = sysmod
    core.store._s["scan_scope"] = json.dumps({"1.4.3": ["docx"]})
    assert s._active_scope_info()["name"] == "custom"


def test_a_saved_but_unusable_scope_says_so(sysmod):
    """The distinction that matters: a scope IS set, and the server is ignoring it.

    Without this, a typo'd scope reports exactly like no scope at all — the operator sees the
    full estate assessed and no reason why the narrowing they saved did nothing.
    """
    s, core = sysmod
    core.store._s["scan_scope"] = '{"9.9.9": ["docx"]}'
    info = s._active_scope_info()
    assert info["criteria"] is None          # fails OPEN — nothing is excluded
    assert "error" in info and "9.9.9" in info["error"]


def test_no_scope_set_carries_no_error_key(sysmod):
    """`error` appears only when there is something to say, so its presence is the signal."""
    s, core = sysmod
    core.store._s["scan_scope"] = ""
    assert "error" not in s._active_scope_info()
