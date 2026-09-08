"""The rubric is the GLOBAL scoring policy, so it has to leave the container that was told.

`PUT /rubric` used to write `config/rubric.active.json` inside whichever API replica served the
request, and `core.active_rubric()` read that same path. Nothing mounts a volume there, so it was
one container's ephemeral layer, and three things followed:

  - other API replicas kept the previous rubric (standard-production's floor is two);
  - EVERY WORKER CONTAINER kept it too — and workers are where scoring happens, since the handlers
    stamp `rubric_hash` per file and no worker ever receives the PUT. The change was invisible to
    the tier that applies it even with a single API replica;
  - it was lost on restart or redeploy.

`rubric_hash` is recorded against every scanned file, so replicas under different policies also
recorded different hashes for the same configuration.

WHAT THESE TESTS ASSERT IS THE PROPERTY, NOT THE MECHANISM. A test that checked "a row appears in
app_settings" would pass just as well if the read path still preferred a local file. So the reads
here go through a SEPARATELY CONSTRUCTED store against the same database — the closest thing in a
single process to "a different container" — and through a `core` whose filesystem still holds the
old file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import core  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cached_rubric():
    """`active_rubric` caches for a few seconds so a 986-file scan does not make 986 round trips.
    That cache is per-process and would mask exactly what these tests are about."""
    core.invalidate_rubric_cache()
    yield
    core.invalidate_rubric_cache()


def _client(monkeypatch, store):
    monkeypatch.setattr(core, "store", store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _second_container(store):
    """Another Store on the same database — a stand-in for the other replica or a worker."""
    import store as store_mod
    return store_mod.Store()


def test_a_rubric_set_on_one_container_is_read_by_another(monkeypatch, isolated_store):
    """THE BUG, stated as the property it violated. The write must be visible through a store
    this request never touched, because that is what a worker container is."""
    client = _client(monkeypatch, isolated_store)
    before = core.active_rubric(fresh=True)

    resp = client.put("/rubric", json={"compliant_threshold": 71})
    assert resp.status_code == 200, resp.text
    assert resp.json()["threshold"] == 71

    monkeypatch.setattr(core, "store", _second_container(isolated_store))
    core.invalidate_rubric_cache()
    elsewhere = core.active_rubric(fresh=True)
    assert elsewhere.threshold == 71, (
        "the other container is still scoring with the old rubric — this is the defect")
    assert elsewhere.hash != before.hash, "the hash stamped on results must move with the policy"


def test_the_rubric_does_not_come_from_this_containers_filesystem(monkeypatch, isolated_store,
                                                                  tmp_path):
    """The read path must not prefer a local file. `core.ACP` is repointed at a directory whose
    `rubric.active.json` says something different from the database: the database must win, or a
    container that happens to hold a stale file scores by it forever."""
    client = _client(monkeypatch, isolated_store)
    client.put("/rubric", json={"compliant_threshold": 64}).raise_for_status()

    config = tmp_path / "config"
    config.mkdir()
    stale = json.loads((core.ACP / "config" / "rubric.default.json").read_text())
    stale["compliant_threshold"] = 12
    (config / "rubric.active.json").write_text(json.dumps(stale))
    (config / "rubric.default.json").write_text(json.dumps(stale))

    monkeypatch.setattr(core, "ACP", tmp_path)
    core.invalidate_rubric_cache()
    assert core.active_rubric(fresh=True).threshold == 64, (
        "a stale file in this container outranked the stored policy")


def test_an_edit_composes_with_what_is_already_in_force(monkeypatch, isolated_store):
    """Two edits to different fields must both survive. The writer starts from the rubric IN
    FORCE, so the second PUT cannot silently reset the first back to the shipped default."""
    client = _client(monkeypatch, isolated_store)
    client.put("/rubric", json={"compliant_threshold": 55}).raise_for_status()
    resp = client.put("/rubric", json={"disabled_rules": ["docx.alt_text"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["threshold"] == 55, "the second edit reset the first"
    assert body["disabled_rules"] == ["docx.alt_text"]


def test_without_a_stored_rubric_the_shipped_default_is_used(monkeypatch, isolated_store):
    """The control, and the upgrade path. An installation that has never PUT must score exactly as
    it did before this change rather than fall to an empty or invented policy."""
    monkeypatch.setattr(core, "store", isolated_store)
    core.invalidate_rubric_cache()
    from rubric import Rubric
    shipped = Rubric.load(core.ACP / "config" / "rubric.default.json")
    assert core.active_rubric(fresh=True).hash == shipped.hash


def test_an_unreadable_store_falls_back_rather_than_stopping_every_scan(monkeypatch,
                                                                       isolated_store):
    """Scoring must not stop because a setting could not be read. The handlers call this per file,
    so raising here would fail every document in the fleet rather than degrade one endpoint."""
    class Broken:
        def get_setting(self, *a, **k):
            raise RuntimeError("database is down")

    monkeypatch.setattr(core, "store", Broken())
    core.invalidate_rubric_cache()
    from rubric import Rubric
    shipped = Rubric.load(core.ACP / "config" / "rubric.default.json")
    assert core.active_rubric(fresh=True).hash == shipped.hash


def test_a_corrupt_stored_rubric_falls_back_rather_than_raising(monkeypatch, isolated_store):
    """Same reasoning, one layer in: a setting that is not rubric JSON must not 500 every scan."""
    isolated_store.set_setting(core._RUBRIC_SETTING, "{not json")
    monkeypatch.setattr(core, "store", isolated_store)
    core.invalidate_rubric_cache()
    from rubric import Rubric
    shipped = Rubric.load(core.ACP / "config" / "rubric.default.json")
    assert core.active_rubric(fresh=True).hash == shipped.hash


def test_the_cache_is_bounded_and_the_writer_clears_it(monkeypatch, isolated_store):
    """The cache exists because `_scan_file` is a per-document job handler — a 986-file scan would
    otherwise make ~1000 round trips. It must not outlive a write on the replica that served it,
    and `fresh=True` must always bypass it."""
    monkeypatch.setattr(core, "store", isolated_store)
    core.invalidate_rubric_cache()
    first = core.active_rubric()
    assert core.active_rubric() is first, "not cached; every scanned file would hit the database"

    isolated_store.set_setting(core._RUBRIC_SETTING, json.dumps(
        {**json.loads((core.ACP / "config" / "rubric.default.json").read_text()),
         "compliant_threshold": 33}))
    assert core.active_rubric() is first, "the TTL is not being honoured at all"
    assert core.active_rubric(fresh=True).threshold == 33, "fresh=True did not bypass the cache"

    core.invalidate_rubric_cache()
    assert core.active_rubric().threshold == 33, "invalidation did not take"


def test_nothing_writes_the_active_rubric_file_any_more():
    """The defect was a WRITE to the container filesystem, so the absence of that write is the fix.
    Reads of the file remain — they are the fallback for an installation that has not PUT since
    this changed."""
    route = (Path(__file__).resolve().parent.parent / "api" / "routes" / "rubric.py").read_text()
    assert "write_text" not in route, "PUT /rubric writes to the container again"
    assert "set_setting" in route
