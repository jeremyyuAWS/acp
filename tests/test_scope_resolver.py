"""C4a — per-file WCAG scope resolution (PRD §4.4 / AC-09): the pure resolver + the
scope_rule store round-trip. No scoring wired yet (that is C4b)."""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scope_resolver as sr


# ── matches() ────────────────────────────────────────────────────────────────
def test_folder_is_case_insensitive_prefix():
    r = {"selector": "folder", "value": "Finance"}
    assert sr.matches({"path": "finance/q3/budget.xlsx"}, r)
    assert sr.matches({"parent_folder": "Finance"}, r)
    assert not sr.matches({"path": "HR/policy.docx"}, r)


def test_owner_and_department_equality():
    assert sr.matches({"owner": "CFO@x.com"}, {"selector": "owner", "value": "cfo@x.com"})
    assert not sr.matches({"owner": "cfo@x.com"}, {"selector": "owner", "value": "hr@x.com"})
    assert sr.matches({"department": "Legal"}, {"selector": "department", "value": "legal"})


def test_blank_value_never_matches():
    assert not sr.matches({"path": "anything"}, {"selector": "folder", "value": ""})
    assert not sr.matches({"owner": "x"}, {"selector": "bogus", "value": "x"})


# ── resolve() ────────────────────────────────────────────────────────────────
DEFAULT = {"1.1.1", "1.4.3", "2.4.6"}


def test_no_rule_matches_returns_default():
    assert sr.resolve({"path": "misc/x.pdf"}, [], DEFAULT) == DEFAULT
    rules = [{"rule_id": "r1", "selector": "folder", "value": "Finance", "codes": ["1.4.3"]}]
    assert sr.resolve({"path": "hr/x.docx"}, rules, DEFAULT) == DEFAULT


def test_single_match_uses_rule_codes_not_default():
    rules = [{"rule_id": "r1", "selector": "folder", "value": "Finance", "codes": ["1.4.3", "1.3.1"]}]
    assert sr.resolve({"path": "finance/b.xlsx"}, rules, DEFAULT) == {"1.4.3", "1.3.1"}


def test_multiple_matches_union():
    rules = [
        {"rule_id": "r1", "selector": "folder", "value": "Finance", "codes": ["1.4.3"]},
        {"rule_id": "r2", "selector": "owner", "value": "cfo@x.com", "codes": ["1.1.1", "2.4.6"]},
    ]
    f = {"path": "finance/b.xlsx", "owner": "cfo@x.com"}
    assert sr.resolve(f, rules, DEFAULT) == {"1.4.3", "1.1.1", "2.4.6"}


def test_override_replaces_union_highest_priority_wins():
    rules = [
        {"rule_id": "r1", "selector": "folder", "value": "Finance", "codes": ["1.4.3", "1.3.1"]},
        {"rule_id": "r2", "selector": "owner", "value": "cfo@x.com", "codes": ["1.1.1"],
         "is_override": True, "priority": 5},
        {"rule_id": "r3", "selector": "department", "value": "finance", "codes": ["2.4.6"],
         "is_override": True, "priority": 9},
    ]
    f = {"path": "finance/b.xlsx", "owner": "cfo@x.com", "department": "Finance"}
    # two overrides match; priority 9 (r3) wins and REPLACES the union
    assert sr.resolve(f, rules, DEFAULT) == {"2.4.6"}


def test_override_tie_broken_deterministically_by_rule_id():
    rules = [
        {"rule_id": "b", "selector": "owner", "value": "o", "codes": ["1.4.3"],
         "is_override": True, "priority": 1},
        {"rule_id": "a", "selector": "owner", "value": "o", "codes": ["1.1.1"],
         "is_override": True, "priority": 1},
    ]
    # equal priority → max rule_id "b" wins, deterministically
    assert sr.resolve({"owner": "o"}, rules, DEFAULT) == {"1.4.3"}


def test_disabled_rule_is_ignored():
    rules = [{"rule_id": "r1", "selector": "folder", "value": "Finance",
              "codes": ["1.4.3"], "enabled": False}]
    assert sr.resolve({"path": "finance/b.xlsx"}, rules, DEFAULT) == DEFAULT


# ── validate_scope_rule() ────────────────────────────────────────────────────
ALLOWED = {"1.1.1", "1.3.1", "1.4.3", "2.4.6"}


def test_validate_accepts_good_rule():
    sr.validate_scope_rule({"selector": "folder", "value": "Finance", "codes": ["1.4.3"]}, ALLOWED)


@pytest.mark.parametrize("bad", [
    {"selector": "size", "value": "x", "codes": ["1.4.3"]},   # bad selector
    {"selector": "folder", "value": "", "codes": ["1.4.3"]},  # blank value
    {"selector": "folder", "value": "F", "codes": []},         # no codes
    {"selector": "folder", "value": "F", "codes": ["9.9.9"]},  # code outside Core-17
])
def test_validate_rejects_bad_rules(bad):
    with pytest.raises(ValueError):
        sr.validate_scope_rule(bad, ALLOWED)


def test_validate_uses_core17_from_codeset():
    import wcag_codeset
    allowed = set(wcag_codeset.core17_codes())
    assert len(allowed) == 17
    sr.validate_scope_rule({"selector": "owner", "value": "x", "codes": ["1.4.3", "2.4.6"]}, allowed)
    with pytest.raises(ValueError):
        sr.validate_scope_rule({"selector": "owner", "value": "x", "codes": ["1.4.2"]}, allowed)  # not tracked


# ── store round-trip ─────────────────────────────────────────────────────────
@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "scope.db")
    return store_mod.Store()


def test_store_roundtrip_and_ordering(st):
    st.create_scope_rule("r1", name="Finance", selector="folder", value="Finance",
                         codes=["1.4.3", "1.3.1"], priority=1)
    st.create_scope_rule("r2", name="Legal override", selector="department", value="Legal",
                         codes=["1.1.1"], priority=9, is_override=True)
    rows = st.list_scope_rules()
    assert [r["rule_id"] for r in rows] == ["r2", "r1"]        # priority desc
    r2 = st.get_scope_rule("r2")
    assert r2["codes"] == ["1.1.1"] and r2["is_override"] is True and r2["enabled"] is True
    # the store rows drive the resolver directly
    eff = sr.resolve({"department": "legal", "path": "finance/x"}, st.list_scope_rules(enabled_only=True),
                     {"2.4.6"})
    assert eff == {"1.1.1"}    # the Legal override wins


def test_store_enable_disable_and_delete(st):
    st.create_scope_rule("r1", name="F", selector="folder", value="Finance", codes=["1.4.3"])
    st.set_scope_rule_enabled("r1", False)
    assert st.list_scope_rules(enabled_only=True) == []
    st.set_scope_rule_enabled("r1", True)
    assert len(st.list_scope_rules(enabled_only=True)) == 1
    st.delete_scope_rule("r1")
    assert st.get_scope_rule("r1") is None
