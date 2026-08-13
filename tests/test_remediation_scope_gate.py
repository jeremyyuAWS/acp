"""The operator scope must gate what gets FIXED, not only what gets assessed and scored.

#107 made `scan_scope` gate assessment and scoring. Nothing gated remediation, so a scoped scan
still wrote changes into a customer's document for criteria they had explicitly excluded — and
did it silently, because the resulting diffs were then filtered back out of the score. This
suite pins the remediation half.

Layered exactly like tests/test_scan_scope_gate.py, and each layer verified to FAIL when its
implementation is reverted:

  1. the predicate            — _remediation_scope resolves the setting through the Store
  2. the proposal lane        — _enqueue_proposals drops out-of-scope criteria, and says so
  3. the deterministic lane   — remediate_html skips out-of-scope fixers entirely
  4. the unscoped default     — none of the above changes behaviour when no scope is set
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


# ── doubles ───────────────────────────────────────────────────────────────────
class _Store:
    """Minimal Store stand-in: the scope setting plus the two sinks under test."""

    def __init__(self, scope_name=""):
        self._settings = {"scan_scope": scope_name}
        self.enqueued = []      # (scan_id, file, sc, n_props)
        self.decisions = []     # (actor, action, detail)

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)

    def enqueue_proposals(self, scan_id, filename, sc, proposals, *, validated=False,
                          rule_name=""):
        self.enqueued.append((scan_id, filename, sc, len(proposals)))

    def log_decision(self, actor, action, **kw):
        self.decisions.append((actor, action, kw.get("detail", "")))


@pytest.fixture()
def handlers(monkeypatch):
    import core
    import handlers as h
    store = _Store()
    monkeypatch.setattr(core, "store", store, raising=False)
    return h, store


# ── 1. the predicate ──────────────────────────────────────────────────────────
def test_no_scope_set_returns_none_so_nothing_is_gated(handlers):
    h, store = handlers
    store._settings["scan_scope"] = ""
    assert h._remediation_scope("report.docx") is None


def test_scope_resolves_through_the_store_not_the_storeless_fallback(handlers):
    """`in_scope`'s storeless fallback answers True for everything — the exact failure its own
    docstring calls the worst way for a feature flag to be off. The predicate must see the
    SETTING, so a criterion outside the preset comes back False."""
    h, store = handlers
    store._settings["scan_scope"] = "engagement-14"
    allows = h._remediation_scope("report.docx")
    assert allows is not None, "a configured scope must produce a predicate"
    # engagement-14 admits 1.1.1 on docx and does NOT admit 2.1.1 on docx (pptx/pdf only).
    assert allows("1.1.1") is True
    assert allows("2.1.1") is False


def test_unknown_format_is_never_excluded(handlers):
    """The gate honours a deliberate choice; it must not invent one from an unparseable name."""
    h, store = handlers
    store._settings["scan_scope"] = "engagement-14"
    allows = h._remediation_scope("no-extension-here")
    assert allows("2.1.1") is True


def test_a_broken_scope_lookup_does_not_block_everything(handlers, monkeypatch):
    """Fail open, not closed: an unresolvable scope must not silently stop all remediation."""
    h, store = handlers

    def _boom(*a, **k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "get_setting", _boom)
    assert h._remediation_scope("report.docx") is None


# ── 2. the proposal lane ──────────────────────────────────────────────────────
def test_in_scope_proposals_are_enqueued(handlers):
    h, store = handlers
    store._settings["scan_scope"] = "engagement-14"
    h._enqueue_proposals("s1", "report.docx", "1.1.1", "Non-text Content", [{"v": "alt"}])
    assert [e[2] for e in store.enqueued] == ["1.1.1"]


def test_out_of_scope_proposals_are_dropped(handlers):
    """The regression this suite exists for: 2.1.1 is not in engagement-14 for docx, so no review
    card may be created for it — deferring is still acting on an excluded criterion."""
    h, store = handlers
    store._settings["scan_scope"] = "engagement-14"
    h._enqueue_proposals("s1", "report.docx", "2.1.1", "Keyboard", [{"v": "x"}])
    assert store.enqueued == []


def test_the_drop_is_recorded_not_silent(handlers):
    """An operator who narrowed the scope must be able to see that the narrowing is what
    stopped the fix, rather than wonder why a known finding produced no card."""
    h, store = handlers
    store._settings["scan_scope"] = "engagement-14"
    h._enqueue_proposals("s1", "report.docx", "2.1.1", "Keyboard", [{"v": "x"}, {"v": "y"}])
    actions = [d[1] for d in store.decisions]
    assert "remediate.out_of_scope" in actions
    detail = [d[2] for d in store.decisions if d[1] == "remediate.out_of_scope"][0]
    assert "2.1.1" in detail and "2 proposal" in detail


def test_same_criterion_allowed_on_one_format_and_blocked_on_another(handlers):
    """Scope is per (criterion, format) — the whole reason it is not a file-type filter."""
    h, store = handlers
    store._settings["scan_scope"] = "engagement-14"
    h._enqueue_proposals("s1", "deck.pptx", "2.1.1", "Keyboard", [{"v": "x"}])
    h._enqueue_proposals("s1", "report.docx", "2.1.1", "Keyboard", [{"v": "x"}])
    assert [(e[1], e[2]) for e in store.enqueued] == [("deck.pptx", "2.1.1")]


# ── 3. the deterministic lane ─────────────────────────────────────────────────
def _html_missing_lang_and_title():
    return "<html><head></head><body><p>hi</p></body></html>"


def test_html_fixers_run_when_unscoped():
    from remediate import remediate_html
    fixed, applied, _ = remediate_html(_html_missing_lang_and_title(), ai_enabled=False)
    assert applied, "the unscoped path must still apply its fixers"
    assert 'lang=' in fixed


def test_html_fixer_is_skipped_when_its_criterion_is_out_of_scope():
    """3.1.1 Language of Page is an auto fixer; excluding it must leave the document alone."""
    from remediate import remediate_html
    fixed, applied, deferred = remediate_html(
        _html_missing_lang_and_title(), ai_enabled=False, in_scope=lambda sc: sc != "3.1.1")
    assert 'lang=' not in fixed, "an excluded criterion must not be written into the document"
    assert not any("3.1.1" in a for a in applied)


def test_excluded_criterion_is_not_deferred_either():
    """Excluding a criterion means ACP leaves it alone — it must not land in HITL instead."""
    from remediate import remediate_html
    _, _, deferred = remediate_html(
        _html_missing_lang_and_title(), ai_enabled=False, in_scope=lambda sc: False)
    assert deferred == [], "an out-of-scope criterion must not be deferred to a human either"


# ── 4. the unscoped default ───────────────────────────────────────────────────
def test_unscoped_deployment_is_byte_identical():
    """No scope set must cost nothing and change nothing — same output as passing no predicate."""
    from remediate import remediate_html
    a, applied_a, deferred_a = remediate_html(_html_missing_lang_and_title(), ai_enabled=False)
    b, applied_b, deferred_b = remediate_html(_html_missing_lang_and_title(), ai_enabled=False,
                                              in_scope=None)
    assert a == b and applied_a == applied_b and deferred_a == deferred_b


def test_unscoped_proposals_are_never_dropped(handlers):
    h, store = handlers
    store._settings["scan_scope"] = ""
    for sc in ("1.1.1", "2.1.1", "4.1.2"):
        h._enqueue_proposals("s1", "report.docx", sc, sc, [{"v": "x"}])
    assert [e[2] for e in store.enqueued] == ["1.1.1", "2.1.1", "4.1.2"]
    assert not [d for d in store.decisions if d[1] == "remediate.out_of_scope"]
