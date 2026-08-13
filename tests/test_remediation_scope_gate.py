"""The operator scope must gate what gets FIXED, not only what gets assessed and scored — and
under Phase 3a it gates from the scan's FROZEN scope, not the live global.

#107 made `scan_scope` gate assessment and scoring. Nothing gated remediation, so a scoped scan
still wrote changes into a customer's document for criteria they had explicitly excluded — and
did it silently, because the resulting diffs were then filtered back out of the score. This
suite pins the remediation half.

PHASE 3a moved the contract from the LIVE global scope to the scan's FROZEN scope: remediation
resolves `store.get_scan_scope(scan_id)`, the scope recorded when the scan started, NOT
`active_scope(store)`. Changing the operator's global scope after a scan must no longer alter
what that old scan remediates while its frozen Assess counts stay put. These tests set a scan's
stored scope, then move the global setting the OTHER way, and assert remediation follows the
FROZEN one.

Layered exactly like tests/test_scan_scope_gate.py, and each layer verified to FAIL when its
implementation is reverted:

  1. the predicate            — _remediation_scope resolves the scan's FROZEN get_scan_scope
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
    """Minimal Store stand-in: a per-scan FROZEN scope (what remediation must read) plus a
    deliberately-conflicting LIVE global setting (what it must NOT read), and the two sinks
    under test."""

    def __init__(self):
        self._frozen = {}                      # scan_id -> {sc: frozenset(fmts)} | None
        self._settings = {"scan_scope": ""}    # the LIVE global — proves it is NOT consulted
        self.enqueued = []      # (scan_id, file, sc, n_props)
        self.decisions = []     # (actor, action, detail)

    def freeze(self, scan_id, preset_or_map):
        """Record the scan's frozen scope. A preset name is resolved to the same map the real
        get_scan_scope would rehydrate; a dict/None is stored verbatim."""
        from assessment_policy import parse_scope_setting
        if isinstance(preset_or_map, str):
            self._frozen[scan_id] = parse_scope_setting(preset_or_map)[0]
        else:
            self._frozen[scan_id] = preset_or_map

    def get_scan_scope(self, scan_id):
        return self._frozen.get(scan_id)

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
def test_no_scope_recorded_returns_none_so_nothing_is_gated(handlers):
    h, store = handlers
    # Nothing frozen for this scan (a legacy pre-3a scan reads this way too).
    assert h._remediation_scope("report.docx", "s1") is None


def test_scope_resolves_through_the_scans_frozen_scope_not_the_live_global(handlers):
    """The 3a contract. The predicate must read the scan's FROZEN scope. We freeze engagement-14
    on the scan and move the LIVE global the opposite way; remediation must follow the frozen one.

    engagement-14 admits 1.1.1 on docx and does NOT admit 2.1.1 on docx (pptx/pdf only). The live
    global is set to admit exactly 2.1.1 on docx — so if remediation read the global it would
    flip both answers."""
    h, store = handlers
    store.freeze("s1", "engagement-14")
    store._settings["scan_scope"] = '{"2.1.1": ["docx"]}'   # the LIVE global, deliberately opposite
    allows = h._remediation_scope("report.docx", "s1")
    assert allows is not None, "a configured frozen scope must produce a predicate"
    assert allows("1.1.1") is True, "frozen scope admits 1.1.1 on docx"
    assert allows("2.1.1") is False, "frozen scope excludes 2.1.1 on docx — the live global must not win"


def test_a_global_scope_change_after_the_scan_does_not_move_the_gate(handlers):
    """The exact Remediate/Assess contradiction 3a removes: the scan was frozen with no
    restriction, so remediation stays unscoped even after the operator narrows the global."""
    h, store = handlers
    store.freeze("s1", None)                                 # scan started unscoped
    store._settings["scan_scope"] = "engagement-14"          # operator narrows the GLOBAL, later
    assert h._remediation_scope("report.docx", "s1") is None, (
        "an old unscoped scan must keep remediating everything — the later global change is not its scope")


def test_unknown_format_is_never_excluded(handlers):
    """The gate honours a deliberate choice; it must not invent one from an unparseable name."""
    h, store = handlers
    store.freeze("s1", "engagement-14")
    allows = h._remediation_scope("no-extension-here", "s1")
    assert allows("2.1.1") is True


def test_a_broken_scope_lookup_does_not_block_everything(handlers, monkeypatch):
    """Fail open, not closed: an unresolvable scope must not silently stop all remediation."""
    h, store = handlers

    def _boom(*a, **k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "get_scan_scope", _boom)
    assert h._remediation_scope("report.docx", "s1") is None


# ── 2. the proposal lane ──────────────────────────────────────────────────────
def test_in_scope_proposals_are_enqueued(handlers):
    h, store = handlers
    store.freeze("s1", "engagement-14")
    h._enqueue_proposals("s1", "report.docx", "1.1.1", "Non-text Content", [{"v": "alt"}])
    assert [e[2] for e in store.enqueued] == ["1.1.1"]


def test_out_of_scope_proposals_are_dropped(handlers):
    """The regression this suite exists for: 2.1.1 is not in engagement-14 for docx, so no review
    card may be created for it — deferring is still acting on an excluded criterion."""
    h, store = handlers
    store.freeze("s1", "engagement-14")
    h._enqueue_proposals("s1", "report.docx", "2.1.1", "Keyboard", [{"v": "x"}])
    assert store.enqueued == []


def test_the_drop_is_recorded_not_silent(handlers):
    """An operator who narrowed the scope must be able to see that the narrowing is what
    stopped the fix, rather than wonder why a known finding produced no card."""
    h, store = handlers
    store.freeze("s1", "engagement-14")
    h._enqueue_proposals("s1", "report.docx", "2.1.1", "Keyboard", [{"v": "x"}, {"v": "y"}])
    actions = [d[1] for d in store.decisions]
    assert "remediate.out_of_scope" in actions
    detail = [d[2] for d in store.decisions if d[1] == "remediate.out_of_scope"][0]
    assert "2.1.1" in detail and "2 proposal" in detail


def test_same_criterion_allowed_on_one_format_and_blocked_on_another(handlers):
    """Scope is per (criterion, format) — the whole reason it is not a file-type filter."""
    h, store = handlers
    store.freeze("s1", "engagement-14")
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
    store.freeze("s1", None)     # nothing frozen for this scan → no restriction
    for sc in ("1.1.1", "2.1.1", "4.1.2"):
        h._enqueue_proposals("s1", "report.docx", sc, sc, [{"v": "x"}])
    assert [e[2] for e in store.enqueued] == ["1.1.1", "2.1.1", "4.1.2"]
    assert not [d for d in store.decisions if d[1] == "remediate.out_of_scope"]
