"""Per-user setting overrides — owner default + per-user override (backlog R7, stage 1).

The storage + resolution primitive R7 is built on: a setting has an owner/global value, and a user
may override it for themselves. This pins the PRECEDENCE (override > owner default > fallback) and,
critically, the two edges that a naive implementation gets wrong: an override that is present but
EMPTY is not the same as no override, and one user's override never leaks into another's resolution.

Scan-time wiring (which scans actually read the override) is a separate, reviewed change on the scope
hot path — see ADR 0035. This tests only the primitive.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

KEY = "scan_scope"
A = "alice@hospital.example"
B = "bob@hospital.example"


def test_resolve_with_no_user_is_the_global_setting(isolated_store):
    s = isolated_store
    s.set_setting(KEY, "owner-default")
    assert s.resolve_setting(KEY) == "owner-default"
    assert s.resolve_setting(KEY, user=None) == "owner-default"


def test_a_user_override_wins_over_the_owner_default(isolated_store):
    s = isolated_store
    s.set_setting(KEY, "owner-default")
    s.set_user_setting(A, KEY, "alice-override")
    assert s.resolve_setting(KEY, user=A) == "alice-override"     # A sees their own
    assert s.resolve_setting(KEY, user=B) == "owner-default"      # B, no override, sees the default


def test_absent_override_falls_back_to_the_owner_default(isolated_store):
    s = isolated_store
    s.set_setting(KEY, "owner-default")
    assert s.get_user_setting(A, KEY) is None                     # no override recorded
    assert s.resolve_setting(KEY, user=A) == "owner-default"


def test_an_empty_override_is_a_real_value_not_absence(isolated_store):
    # "" clears a scope — a user deliberately opting into "no restriction" must override the owner
    # default, not be mistaken for having no preference. This is the edge a truthiness check breaks.
    s = isolated_store
    s.set_setting(KEY, "owner-default")
    s.set_user_setting(A, KEY, "")
    assert s.get_user_setting(A, KEY) == ""
    assert s.resolve_setting(KEY, user=A) == ""                   # the empty override wins, not the default


def test_clear_removes_the_override_and_restores_the_default(isolated_store):
    s = isolated_store
    s.set_setting(KEY, "owner-default")
    s.set_user_setting(A, KEY, "alice-override")
    s.clear_user_setting(A, KEY)
    assert s.get_user_setting(A, KEY) is None
    assert s.resolve_setting(KEY, user=A) == "owner-default"
    s.clear_user_setting(A, KEY)                                  # idempotent — no error on a second clear


def test_one_users_override_never_leaks_into_anothers(isolated_store):
    s = isolated_store
    s.set_user_setting(A, KEY, "alice-only")
    assert s.resolve_setting(KEY, user=B) is None                 # no global, no B override → None
    assert s.resolve_setting(KEY, user=B, default="fallback") == "fallback"
    assert s.resolve_setting(KEY, user=A) == "alice-only"


def test_default_is_used_only_when_nothing_is_set(isolated_store):
    s = isolated_store
    assert s.resolve_setting(KEY, user=A, default="fallback") == "fallback"
    s.set_setting(KEY, "owner-default")
    assert s.resolve_setting(KEY, user=A, default="fallback") == "owner-default"   # global beats default
