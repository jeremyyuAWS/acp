"""C4b — per-file scope wired into assessment scoring. Covers the assessment_policy helper,
the frozen-rules store round-trip, and store.scope_for_file (the one seam both the score and
trace paths call so a file's score and traces read one scope)."""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import assessment_policy as ap


# ── resolve_file_scope (pure helper) ─────────────────────────────────────────
GLOBAL = {"1.1.1": frozenset({"docx"}), "1.4.3": frozenset({"docx", "pdf"})}


def test_no_rules_returns_global_object_unchanged():
    assert ap.resolve_file_scope({"path": "finance/x"}, GLOBAL, None) is GLOBAL
    assert ap.resolve_file_scope({"path": "finance/x"}, GLOBAL, []) is GLOBAL


def test_no_match_returns_global_unchanged():
    rules = [{"rule_id": "r", "selector": "folder", "value": "Finance", "codes": ["1.4.3"], "enabled": True}]
    assert ap.resolve_file_scope({"path": "hr/policy.docx"}, GLOBAL, rules) is GLOBAL


def test_match_narrows_to_resolved_codes_keeping_global_lanes():
    rules = [{"rule_id": "r", "selector": "folder", "value": "Finance", "codes": ["1.4.3"], "enabled": True}]
    eff = ap.resolve_file_scope({"path": "finance/budget.xlsx"}, GLOBAL, rules)
    assert set(eff) == {"1.4.3"}                       # 1.1.1 dropped for this file
    assert eff["1.4.3"] == frozenset({"docx", "pdf"})  # lane kept from global


def test_rule_may_add_a_code_absent_from_global_using_rule_formats():
    # global omits 2.4.6; a Finance rule adds it → its lane comes from RULE_FORMATS
    rules = [{"rule_id": "r", "selector": "owner", "value": "cfo@x.com", "codes": ["2.4.6"], "enabled": True}]
    eff = ap.resolve_file_scope({"owner": "cfo@x.com"}, GLOBAL, rules)
    assert set(eff) == {"2.4.6"}
    assert eff["2.4.6"] == ap.RULE_FORMATS.get("2.4.6", frozenset())


def test_global_none_unrestricted_stays_none_without_a_match():
    rules = [{"rule_id": "r", "selector": "folder", "value": "Finance", "codes": ["1.4.3"], "enabled": True}]
    assert ap.resolve_file_scope({"path": "hr/x"}, None, rules) is None   # unrestricted preserved


def test_global_none_with_match_restricts_to_rule_codes():
    rules = [{"rule_id": "r", "selector": "folder", "value": "Finance", "codes": ["1.4.3"], "enabled": True}]
    eff = ap.resolve_file_scope({"path": "finance/x.pdf"}, None, rules)
    assert set(eff) == {"1.4.3"} and eff["1.4.3"] == ap.RULE_FORMATS.get("1.4.3", frozenset())


# ── store: frozen rules + per-file resolution ────────────────────────────────
@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "scopescore.db")
    return store_mod.Store()


def _freeze(st, scan_id, scan_scope_json, rules):
    """Init a scan run with a frozen scan_scope + scope_rules, as _scan_discover does."""
    st.init_scan_run(scan_id, "drive", 2, "2026-08-18T00:00:00+00:00", "rb", "hash",
                     owner="me", status="discovered",
                     scope={"scan_scope": scan_scope_json, "scope_rules": rules})


def test_get_scan_scope_rules_roundtrip(st):
    rules = [{"rule_id": "r1", "selector": "folder", "value": "Finance", "codes": ["1.4.3"],
              "priority": 0, "is_override": False, "enabled": True}]
    _freeze(st, "s1", {"1.1.1": ["docx"]}, rules)
    got = st.get_scan_scope_rules("s1")
    assert len(got) == 1 and got[0]["value"] == "Finance" and got[0]["codes"] == ["1.4.3"]
    assert st.get_scan_scope_rules("nope") == []     # unknown scan → []
    _freeze(st, "s2", {"1.1.1": ["docx"]}, [])
    assert st.get_scan_scope_rules("s2") == []       # no rules frozen → []


def test_scope_for_file_narrows_only_matching_files(st):
    rules = [{"rule_id": "r1", "selector": "folder", "value": "Finance", "codes": ["1.4.3"],
              "priority": 0, "is_override": False, "enabled": True}]
    _freeze(st, "s1", {"1.1.1": ["docx"], "1.4.3": ["docx", "pdf"]}, rules)
    st.add_inventory("s1", [
        {"file": "Finance/budget.xlsx", "path": "Finance/budget.xlsx", "parent_folder": "Finance"},
        {"file": "HR/policy.docx", "path": "HR/policy.docx", "parent_folder": "HR"},
    ])
    g = st.get_scan_scope("s1")
    fin = st.scope_for_file("s1", "Finance/budget.xlsx", g)
    hr = st.scope_for_file("s1", "HR/policy.docx", g)
    assert set(fin) == {"1.4.3"}          # Finance file narrowed by the rule
    assert set(hr) == set(g)              # HR file keeps the global scope
    assert hr is g                        # unchanged: same object, byte-for-byte pre-C4


def test_scope_for_file_noop_without_rules(st):
    _freeze(st, "s1", {"1.1.1": ["docx"]}, [])
    st.add_inventory("s1", [{"file": "a.docx", "path": "a.docx"}])
    g = st.get_scan_scope("s1")
    assert st.scope_for_file("s1", "a.docx", g) is g   # no frozen rules → global untouched
