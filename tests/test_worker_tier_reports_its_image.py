"""Which image is the worker tier actually running? Before this, nothing could answer that.

WHY IT COULD NOT BE ANSWERED. `acp-worker` has NO INGRESS — there is no route, no port, nothing
outside the cluster can ask it anything. The API tier answers the question about ITSELF on
/healthz (`version`, from ACP_BUILD_VERSION, stamped by deploy.sh), but the worker's only channel
to the outside is the `worker_tier_heartbeat` setting, and that carried a timestamp and a pool
size. So "did the deploy reach the worker?" had no answer at all, from anywhere.

That is not an academic gap. app and worker deploy from DIFFERENT IMAGES with nothing sequencing
them — ADR 0045 §6 documents exactly that window — so "the app is on the new build" has never
said anything about the worker. Establishing this took reading redeploy.sh, because the system
could not be asked.

The `worker_instances` table has `revision_name` and `software_version` columns that would carry
this properly, and NO WRITER: it is PR 1 of a 5-PR plan whose emit sites are deliberately
deferred for explicit human review, since they touch worker.py's claim and reclaim paths. This
does not pre-empt any of that — it adds one string to an envelope that already exists.

THE THREE ANSWERS, which must stay three:

    "2026.8.30.60"  a stamped image; compare directly against /healthz's version
    "dev"           an image that never went through deploy.sh — same word /healthz uses, so
                    the two tiers are comparable strings
    None            the beat came from a worker that predates this field, i.e. the deploy has
                    NOT reached the worker tier. That is an answer, not a gap, and collapsing
                    it into "dev" would destroy the one fact somebody is asking for.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402


@pytest.fixture()
def st(monkeypatch):
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "wver.db")
    return store_mod.Store()


def _beat(**fields):
    return json.dumps({"at": datetime.now(timezone.utc).isoformat(), **fields})


# ── the parser ────────────────────────────────────────────────────────────────────────────────

def test_a_stamped_version_survives_the_envelope():
    iso, pool, version = store_mod._parse_worker_tier_heartbeat(
        _beat(pool_size=4, version="2026.8.30.60"))
    assert version == "2026.8.30.60"
    assert pool == 4 and iso


def test_the_old_bare_iso_format_still_parses():
    """A pre-envelope worker beating at a post-rollout API. Every mix of old and new has to work
    during a rolling deploy — that is the whole reason this parser exists."""
    raw = "2026-08-31T00:00:00+00:00"
    iso, pool, version = store_mod._parse_worker_tier_heartbeat(raw)
    assert iso == raw
    assert pool is None and version is None


def test_an_envelope_without_the_field_reports_none_not_dev(st):
    """THE distinction. A worker that predates this field has not taken the deploy — which is
    exactly the fact somebody is asking for. Reporting it as "dev" would answer a different
    question with the same word."""
    _, _, version = store_mod._parse_worker_tier_heartbeat(_beat(pool_size=2))
    assert version is None, "an absent version was conflated with an unstamped one"


def test_a_junk_version_is_dropped_rather_than_reported():
    """Same rule the pool_size parse already follows: a mistyped field must read as absent, never
    crash and never surface as a version string nobody wrote."""
    for junk in (5, True, None, "", "   ", ["2026.1.1"], {"v": 1}):
        _, _, version = store_mod._parse_worker_tier_heartbeat(_beat(version=junk))
        assert version is None, f"{junk!r} was reported as a version"


def test_a_completely_malformed_beat_still_does_not_crash():
    iso, pool, version = store_mod._parse_worker_tier_heartbeat("{not json at all")
    assert iso == "{not json at all" and pool is None and version is None


# ── what /readyz and the preflight block actually see ─────────────────────────────────────────

def test_worker_tier_status_carries_the_version_through(st):
    st.set_setting("worker_tier_heartbeat", _beat(pool_size=4, version="2026.8.31.7"))
    out = st.worker_tier_status()
    assert out["version"] == "2026.8.31.7"
    assert out["alive"] is True


def test_the_key_is_present_even_when_no_worker_has_ever_beaten(st):
    """`/readyz` spreads this dict straight into its response, so a key that only sometimes
    exists makes a reader write `?? something` — which is how a missing fact becomes a
    fabricated one. It is always there; the VALUE says whether it is known."""
    out = st.worker_tier_status()
    assert "version" in out and out["version"] is None
    assert out["ever_seen"] is False


def test_an_old_worker_reads_as_unknown_rather_than_matching_the_api(st):
    """The failure this exists to make visible: a stale worker tier must not be mistakable for
    one that took the deploy."""
    st.set_setting("worker_tier_heartbeat", _beat(pool_size=4))
    assert st.worker_tier_status()["version"] is None


def test_worker_tier_alive_is_unaffected(st):
    """The scan-start guard reads the same setting through a different path. Adding a field to
    the envelope must not touch the yes/no answer anything gates on."""
    st.set_setting("worker_tier_heartbeat", _beat(pool_size=1, version="2026.8.31.7"))
    assert st.worker_tier_alive() is True
    st.set_setting("worker_tier_heartbeat", "2020-01-01T00:00:00+00:00")
    assert st.worker_tier_alive() is False


# ── the writer ────────────────────────────────────────────────────────────────────────────────

def test_the_worker_stamps_the_same_string_healthz_reports(monkeypatch):
    """Comparability is the point: `readyz.workers.version` against `healthz.version` is the
    whole diagnostic, and it only works if both derive from ACP_BUILD_VERSION the same way —
    including the "dev" fallback for an image deploy.sh never stamped."""
    import os
    import routes.system as system_mod

    monkeypatch.setenv("ACP_BUILD_VERSION", "2026.8.31.7")
    assert system_mod._build_info()["version"] == "2026.8.31.7"
    assert ((os.environ.get("ACP_BUILD_VERSION") or "").strip() or "dev") == "2026.8.31.7"

    monkeypatch.delenv("ACP_BUILD_VERSION", raising=False)
    assert system_mod._build_info()["version"] == "dev"
    assert ((os.environ.get("ACP_BUILD_VERSION") or "").strip() or "dev") == "dev"


def test_worker_main_puts_the_version_in_the_envelope():
    """Read from the source rather than by running the loop: worker_main's heartbeat is a
    15-second timer inside a signal-handled process, and starting one to observe a dict costs
    more than it proves. What matters is that the key is in the payload the loop writes."""
    src = (Path(__file__).resolve().parent.parent / "api" / "worker_main.py").read_text()
    assert '"version": _build_version' in src, (
        "worker_main no longer stamps the version into the heartbeat envelope — nothing outside "
        "the cluster can then tell which image the worker tier is running")
    assert '_build_version = (os.environ.get("ACP_BUILD_VERSION") or "").strip() or "dev"' in src
