"""PUT /settings must be able to set the scan scope, and must refuse a scope it cannot parse.

The admin scope grid writes through this endpoint, so two things have to be true that were not
before:

  1. `scan_scope` is a field the model HAS. It was not, and SettingsUpdate had no
     `extra="forbid"`, so a PUT naming it returned 200 and changed nothing — the request handed
     back as a success. That is the same shape of bug that cost two debugging cycles on a
     production vision-model override, where a setting was "saved" repeatedly while the worker
     used the old value.
  2. An unparseable scope is REJECTED rather than stored. A stored-but-broken scope fails open
     at read time (parse_scope_setting), so the operator would be looking at a saved value the
     engine silently ignores — the exact condition /config's `error` key exists to report. Better
     never to create it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


class _Store:
    def __init__(self):
        self.settings = {}
        self.decisions = []

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def log_decision(self, who, what, **kw):
        self.decisions.append((who, what, kw.get("detail", "")))

    # update_settings touches these only when the matching field is sent.
    def set_drive_mirror_enabled(self, v): self.settings["drive_mirror_enabled"] = v
    def set_drive_mirror_folder(self, v): self.settings["drive_mirror_folder"] = v
    def get_ai_enabled(self): return True
    def get_drive_mirror_enabled(self): return True
    def get_drive_mirror_folder(self): return "Remediated"
    def get_auto_apply_validated(self): return False


@pytest.fixture()
def sysmod(monkeypatch):
    import core
    import routes.system as s
    monkeypatch.setattr(core, "store", _Store(), raising=False)
    # _require_admin is a separate concern with its own tests; this module is about the payload.
    monkeypatch.setattr(s, "_require_admin", lambda request: None)
    return s, core


def _put(s, **kw):
    return s.update_settings(s.SettingsUpdate(**kw), request=None)


# ── the field exists and round-trips ──────────────────────────────────────────────────────────
def test_a_scope_sent_as_a_dict_is_stored_as_json(sysmod):
    s, core = sysmod
    _put(s, scan_scope={"1.4.3": ["docx", "pdf"]})
    assert json.loads(core.store.settings["scan_scope"]) == {"1.4.3": ["docx", "pdf"]}


def test_a_preset_name_is_stored_verbatim(sysmod):
    s, core = sysmod
    _put(s, scan_scope="deva-final")
    assert core.store.settings["scan_scope"] == "deva-final"


def test_get_settings_returns_the_raw_stored_value(sysmod):
    """The editor must see what is STORED, or a save cannot round-trip.

    /config reports the RESOLVED map for everything that renders a scope; this endpoint is the
    edit surface. Conflating them is how an editor starts overwriting what it never loaded.
    """
    s, core = sysmod
    core.store.settings["scan_scope"] = '{"2.4.2": ["docx"]}'
    assert s.get_settings()["scan_scope"] == '{"2.4.2": ["docx"]}'


def test_no_scope_set_reads_as_empty_string(sysmod):
    s, _ = sysmod
    assert s.get_settings()["scan_scope"] == ""


# ── clearing ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["", {}])
def test_an_empty_scope_clears_the_setting(sysmod, value):
    """`{}` and `""` both mean no restriction, so both store the simpler one."""
    s, core = sysmod
    core.store.settings["scan_scope"] = "deva-final"
    _put(s, scan_scope=value)
    assert core.store.settings["scan_scope"] == ""


# ── rejection, with a reason ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value,fragment", [
    ({"9.9.9": ["docx"]},          "not a criterion this build knows"),
    ({"1.4.3": ["rtf"]},           "unknown format"),
    ("no-such-preset",             "unknown scope preset"),
    ("{not json",                  "not valid JSON"),
])
def test_an_unparseable_scope_is_refused_not_stored(sysmod, value, fragment):
    s, core = sysmod
    with pytest.raises(HTTPException) as e:
        _put(s, scan_scope=value)
    assert e.value.status_code == 422
    assert fragment in str(e.value.detail)
    assert "scan_scope" not in core.store.settings, "a refused scope must not be persisted"


def test_a_refused_scope_leaves_the_previous_one_intact(sysmod):
    """Rejection must not be destructive — the operator keeps the scope they had."""
    s, core = sysmod
    core.store.settings["scan_scope"] = "deva-final"
    with pytest.raises(HTTPException):
        _put(s, scan_scope={"9.9.9": ["docx"]})
    assert core.store.settings["scan_scope"] == "deva-final"


# ── the hollow-200 class ──────────────────────────────────────────────────────────────────────
def test_an_unknown_field_is_a_422_not_a_silent_no_op(sysmod):
    """The model forbids extras, so a typo'd or renamed field is visible to the caller.

    Without this the request is echoed back as a success and nothing is written — which is
    indistinguishable, from the client, from a save that worked.
    """
    s, _ = sysmod
    with pytest.raises(Exception) as e:      # pydantic ValidationError
        s.SettingsUpdate(scan_scoped={"1.4.3": ["docx"]})
    assert "scan_scoped" in str(e.value)


# ── audit ─────────────────────────────────────────────────────────────────────────────────────
def test_setting_the_scope_is_audited(sysmod):
    s, core = sysmod
    _put(s, scan_scope={"1.4.3": ["docx"]})
    assert any(what == "settings.scan_scope" for _who, what, _d in core.store.decisions)
