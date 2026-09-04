"""SharePoint-native freshness — "has the source drifted since ACP scanned it?", answered for
SharePoint at last, and answered the way SharePoint can afford.

WHY IT WAS MISSING RATHER THAN SLOW. `/scans/{sid}/source-status` asks Drive per FILE, with a live
`files().get()` each. On a 30-site estate that is thousands of Graph calls to render one screen,
so SharePoint had no freshness answer at all: every SharePoint file came back `untracked`.

SharePoint has something Drive does not — a delta cursor — which turns the same question into ONE
call per LIBRARY. The two halves that make it correct rather than merely cheap:

  * The cursor is the one THIS SCAN recorded (handlers._sp_scan_cursors), not the live one. The
    live cursor answers "changed since the last sync", which is a different question the moment a
    second scan runs, and its answer is indistinguishable from the right one.
  * The replay does NOT save. Advancing the cursor here would move the scan's recorded position
    every time somebody opened the screen, so the second viewing would report "nothing changed"
    however much had — a read that quietly destroys what it reads.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


def _run(cursors=None, source="sharepoint"):
    scope = {"kind": "sharepoint"}
    if cursors is not None:
        scope["sp_cursors"] = cursors
    return {"source": source, "status": "completed", "scope": scope}


def _delta(monkeypatch, changed=(), removed=(), calls=None, raises=None):
    def fake(token, drive_id, link):
        if calls is not None:
            calls.append((drive_id, link))
        if raises:
            raise raises
        return list(changed), set(removed), "https://delta/NEW"
    monkeypatch.setattr(scanner, "sp_delta_since", fake, raising=True)


_DEFAULT_HEADERS = {"x-sp-token": "tok"}


def _freshness(run, headers=_DEFAULT_HEADERS):
    # A sentinel default, not `headers or {...}`: an EMPTY dict is falsy, so the `or` form
    # silently handed the token back to the very test that was checking what happens without one.
    from routes.scans import _sp_freshness
    return _sp_freshness(run, _Req(headers))


# ── when it can answer, and when it honestly cannot ──────────────────────────────────────────

def test_a_drive_scan_is_not_this_functions_business():
    assert _freshness(_run(source="drive")) == (None, set(), None)


def test_a_scan_with_no_recorded_cursor_cannot_answer():
    """A scan from before this shipped, or one whose shape the delta query cannot serve. None is
    "cannot answer" and the caller renders those files `untracked` — never a false `unchanged`,
    which is the one wrong answer that looks like a right one."""
    assert _freshness(_run(cursors=None)) == (None, set(), None)
    assert _freshness(_run(cursors={})) == (None, set(), None)


def test_no_microsoft_token_cannot_answer_either():
    assert _freshness(_run(cursors={"d1": "https://delta/1"}), headers={}) == (None, set(), None)


def test_a_scope_stored_as_json_text_is_read(monkeypatch):
    """scan_runs.scope comes back as a string on some paths and a dict on others. A reader that
    handled only one would report every SharePoint scan untrackable on whichever path it was
    not."""
    _delta(monkeypatch, changed=[{"id": "i1", "lastModifiedDateTime": "2026-09-01T00:00:00Z"}])
    run = {"source": "sharepoint", "status": "completed",
           "scope": json.dumps({"kind": "sharepoint", "sp_cursors": {"d1": "https://delta/1"}})}
    changed, _, err = _freshness(run)
    assert err is None and changed == {("d1", "i1"): "2026-09-01T00:00:00Z"}


# ── the cost argument, and the read that must not write ──────────────────────────────────────

def test_it_costs_one_call_per_LIBRARY_not_one_per_document(monkeypatch):
    calls: list = []
    _delta(monkeypatch, changed=[{"id": f"i{n}"} for n in range(500)], calls=calls)
    _freshness(_run(cursors={"d1": "https://delta/1", "d2": "https://delta/2"}))
    assert len(calls) == 2, f"500 documents across 2 libraries cost {len(calls)} calls"


def test_the_replay_starts_from_the_cursor_the_SCAN_recorded(monkeypatch):
    """Not the live one. The live cursor answers "since the last sync"; this endpoint is asked
    "since this scan"."""
    calls: list = []
    _delta(monkeypatch, calls=calls)
    _freshness(_run(cursors={"d1": "https://delta/scan-time"}))
    assert calls == [("d1", "https://delta/scan-time")]


def test_the_replay_does_not_advance_the_stored_cursor(monkeypatch):
    """`sp_delta_since` hands back a NEW deltaLink and this endpoint throws it away. Saving it
    would make the second viewing of the screen report "nothing changed" however much had."""
    import inspect
    from routes import scans
    src = inspect.getsource(scans._sp_freshness)
    assert "save_sync_cursor" not in src
    # …and the new link is discarded at the call site, not merely unsaved by luck elsewhere.
    assert "items, gone, _ = sp_delta_since" in src


# ── what the changes mean per file ───────────────────────────────────────────────────────────

def test_a_changed_document_reports_its_new_timestamp(monkeypatch):
    _delta(monkeypatch, changed=[{"id": "i1", "lastModifiedDateTime": "2026-09-01T00:00:00Z"}])
    changed, removed, err = _freshness(_run(cursors={"d1": "https://delta/1"}))
    assert changed == {("d1", "i1"): "2026-09-01T00:00:00Z"}
    assert removed == set() and err is None


def test_a_deleted_document_comes_back_as_a_removed_key(monkeypatch):
    _delta(monkeypatch, removed=[("d1", "i9")])
    changed, removed, err = _freshness(_run(cursors={"d1": "https://delta/1"}))
    assert removed == {("d1", "i9")} and changed == {} and err is None


def test_the_onedrive_key_round_trips(monkeypatch):
    """JSON object keys must be strings, so the no-drive key is stored as "" and has to come back
    as None — the drive id every OneDrive item carries, and the key `apply_sp_delta` and the
    cursor store both use. A mismatch here would make every OneDrive file look unchanged."""
    calls: list = []
    _delta(monkeypatch, changed=[{"id": "i1"}], calls=calls)
    changed, _, _ = _freshness(_run(cursors={"": "https://delta/1"}))
    assert calls == [(None, "https://delta/1")]
    assert list(changed) == [(None, "i1")]


def test_a_graph_failure_is_named_rather_than_reported_as_unchanged(monkeypatch):
    """An operator seeing a wall of `untracked` deserves to know it is a Graph problem this
    endpoint hit, not a scan that recorded nothing."""
    _delta(monkeypatch, raises=RuntimeError("410 Gone"))
    changed, removed, err = _freshness(_run(cursors={"d1": "https://delta/1"}))
    assert changed is None
    assert "could not read changes for library d1" in err and "410 Gone" in err


# ── the classification is the SAME one Drive gets ────────────────────────────────────────────

def test_a_sharepoint_file_is_classified_by_the_same_comparison_drive_uses():
    """A second classification path would be a second thing to keep true. What differs between
    the two sources is how `current` was obtained — one call per library instead of one per
    file — not what the timestamps then mean."""
    import source_staleness as ss
    row = {"source_modified": "2026-08-01T00:00:00Z", "drive_file_id": "i1"}
    assert ss.classify_file(row, "2026-09-01T00:00:00Z", source_is_drive=False,
                            source_tracked=True)["state"] == "stale"
    assert ss.classify_file(row, "2026-08-01T00:00:00Z", source_is_drive=False,
                            source_tracked=True)["state"] == "unchanged"


def test_an_untrackable_source_still_reads_untracked():
    """The default is unchanged for every existing caller: `source_tracked` falls back to
    `source_is_drive`, which is what it meant when Drive was the only source that could answer."""
    import source_staleness as ss
    row = {"source_modified": "2026-08-01T00:00:00Z", "drive_file_id": "i1"}
    assert ss.classify_file(row, "x", source_is_drive=False)["state"] == "untracked"


# ── the cursors get recorded in the first place ──────────────────────────────────────────────

def test_the_scan_records_the_position_each_library_listed_from(monkeypatch):
    import handlers
    import core
    saved = {"sharepoint:[\"o@example.com\", \"d1\"]": {"page_token": "https://delta/1"},
             "sharepoint:[\"o@example.com\", null]": {"page_token": "https://delta/me"}}
    monkeypatch.setattr(core.store, "get_sync_cursor", lambda k: saved.get(k), raising=False)
    got = handlers._sp_scan_cursors("o@example.com", {"delta": {"d1": {}}, "full": {None: "why"}})
    assert got == {"d1": "https://delta/1", "": "https://delta/me"}


def test_recording_the_cursors_can_never_fail_a_scan(monkeypatch):
    """A diagnostic recorded on the way past, after the estate has already been listed. If it
    could raise, it would throw away a completed scan for a field nothing had to have."""
    import handlers
    import core

    def boom(_k):
        raise RuntimeError("store is down")

    monkeypatch.setattr(core.store, "get_sync_cursor", boom, raising=False)
    assert handlers._sp_scan_cursors("o@example.com", {"delta": {"d1": {}}, "full": {}}) == {}
