"""Per-ROLE worker heartbeats, because the shared key is a coin toss between services.

WHAT THE SHARED KEY DOES. worker_main writes its beat twice (worker_main.py:105-106): to
`worker_tier_heartbeat`, and to `worker_tier_heartbeat:<role>`. `worker_tier_status` reads only
the first — ONE row, last writer wins — so with more than one worker service running (acp-worker
and acp-discovery, since #1169) `workers.version` and `workers.pool_size` report whichever service
beat most recently.

Measured against production on 2026-09-01, sampling /readyz every 6s for 90s while the app was on
2026.9.1.23:

    2026.8.31.39  pool=2   x13
    2026.8.31.20  pool=3   x1

Read as one tier that looks like a version flapping at random. Read per role it is two services,
each with a stable answer. This was originally diagnosed — by me — as stale replicas of a single
app; it is not, and the correction is the reason this module exists.

Anything comparing "the worker version" against an expected build needs the per-role reading:
against the shared key the same deploy passes or fails depending on which service beat last.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store as store_mod  # noqa: E402


def _beat(seconds_ago: int = 5, *, pool: int | None = 2, version: str | None = "2026.9.1.23") -> str:
    at = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    env: dict = {"at": at}
    if pool is not None:
        env["pool_size"] = pool
    if version is not None:
        env["version"] = version
    return json.dumps(env)


def _write(st, role: str, raw: str) -> None:
    st.set_setting(f"worker_tier_heartbeat:{role}", raw)


# ── the correction this module encodes ────────────────────────────────────────────────────
def test_two_services_are_two_entries_not_one_flapping_field(isolated_store):
    """THE regression. The shared key cannot express this and never could."""
    _write(isolated_store, "mixed", _beat(pool=2, version="2026.8.31.39"))
    _write(isolated_store, "discovery", _beat(pool=3, version="2026.8.31.20"))

    roles = isolated_store.worker_roles_status()
    assert set(roles) == {"mixed", "discovery"}
    assert roles["mixed"]["version"] == "2026.8.31.39"
    assert roles["mixed"]["pool_size"] == 2
    assert roles["discovery"]["version"] == "2026.8.31.20"
    assert roles["discovery"]["pool_size"] == 3


def test_the_shared_key_still_reports_only_the_last_writer(isolated_store):
    """Pins the behaviour the per-role read exists to work around, so nobody 'fixes' the shared
    key by accident and leaves two surfaces disagreeing."""
    isolated_store.set_setting("worker_tier_heartbeat", _beat(pool=3, version="2026.8.31.20"))
    _write(isolated_store, "mixed", _beat(pool=2, version="2026.8.31.39"))
    _write(isolated_store, "discovery", _beat(pool=3, version="2026.8.31.20"))

    tier = isolated_store.worker_tier_status()
    assert tier["version"] == "2026.8.31.20"          # whoever wrote last
    assert isolated_store.worker_roles_status()["mixed"]["version"] == "2026.8.31.39"


def test_a_role_that_never_beat_is_absent_rather_than_invented(isolated_store):
    """Absent and stale are different facts. Reporting an unstarted service as failing would make
    every single-service deployment look broken."""
    _write(isolated_store, "mixed", _beat())
    roles = isolated_store.worker_roles_status()
    assert "mixed" in roles
    assert "discovery" not in roles and "assess" not in roles


def test_a_stale_role_is_present_and_marked_not_alive(isolated_store):
    """The opposite case: it DID beat, and stopped. That must be visible, not omitted."""
    _write(isolated_store, "discovery", _beat(seconds_ago=3600))
    entry = isolated_store.worker_roles_status()["discovery"]
    assert entry["alive"] is False
    assert entry["age_s"] > 3000


def test_a_fresh_role_is_alive_with_a_small_age(isolated_store):
    _write(isolated_store, "assess", _beat(seconds_ago=5))
    entry = isolated_store.worker_roles_status()["assess"]
    assert entry["alive"] is True and entry["age_s"] < 60


def test_a_malformed_timestamp_is_reported_not_swallowed(isolated_store):
    """Same posture as worker_tier_status: a corrupt beat is a real fault and must not read as
    'never started'."""
    _write(isolated_store, "mixed", "not-a-timestamp")
    entry = isolated_store.worker_roles_status()["mixed"]
    assert entry["alive"] is False
    assert "unparseable" in entry["heartbeat_at"]


def test_an_old_format_bare_timestamp_still_parses(isolated_store):
    """A worker predating the JSON envelope writes a bare ISO string. It must not crash the read,
    and its missing version must be None rather than a guess."""
    bare = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    _write(isolated_store, "mixed", bare)
    entry = isolated_store.worker_roles_status()["mixed"]
    assert entry["alive"] is True
    assert entry["version"] is None


def test_only_known_roles_are_read(isolated_store):
    """Enumerated, not prefix-scanned: a future key sharing the namespace must not silently start
    being reported as a worker service."""
    _write(isolated_store, "mixed", _beat())
    isolated_store.set_setting("worker_tier_heartbeat:something_else", _beat())
    assert set(isolated_store.worker_roles_status()) == {"mixed"}


def test_the_role_set_matches_what_core_actually_accepts(isolated_store):
    """If core learns a new role and this list does not, that service becomes invisible here —
    which is precisely the failure mode the whole module is about."""
    import core
    accepted = {"mixed", "discovery", "assess", "remediate", "processing"}
    assert set(store_mod.Store.WORKER_ROLES) == accepted
    # And core really does reject anything outside it.
    assert "ACP_WORKER_ROLE must be" in Path(core.__file__).read_text()


# ── /readyz ───────────────────────────────────────────────────────────────────────────────
def test_readyz_exposes_the_roles(isolated_store, monkeypatch):
    import core
    from routes import system

    _write(isolated_store, "mixed", _beat(pool=2, version="2026.9.1.23"))
    _write(isolated_store, "discovery", _beat(pool=3, version="2026.8.31.20"))
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "WORKERS", 1, raising=False)
    monkeypatch.setattr(system, "pdf_engine_status",
                        lambda: {"available": True, "path": "/x", "reason": None})

    roles = system.readyz()["workers"]["roles"]
    assert roles["mixed"]["version"] == "2026.9.1.23"
    assert roles["discovery"]["version"] == "2026.8.31.20"


def test_a_failing_role_read_cannot_500_readyz(isolated_store, monkeypatch):
    """Same defence the source and vision probes take. Readiness must not depend on this."""
    import core
    from routes import system

    class Boom:
        def __getattr__(self, name):
            if name == "worker_roles_status":
                def _raise(*a, **k):
                    raise RuntimeError("nope")
                return _raise
            return getattr(isolated_store, name)

    monkeypatch.setattr(core, "store", Boom())
    monkeypatch.setattr(core, "WORKERS", 1, raising=False)
    monkeypatch.setattr(system, "pdf_engine_status",
                        lambda: {"available": True, "path": "/x", "reason": None})

    out = system.readyz()
    assert out["ready"] is True
    assert "error" in out["workers"]["roles"]
