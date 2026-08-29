"""A scheduled sweep must obey the setting, and must never substitute a different corpus.

Both defects were observed in production on 2026-07-29, five minutes apart, forever:

    scheduled sweep fell back to local (1 files); drive error: <HttpError 403 ...
    "Request had insufficient authentication scopes.">

Two separate bugs in one line of log.

1. IT COULD NOT BE TURNED OFF. `PUT /schedule` calls `reload_scheduler()` in whichever process
   served the request. Only `acp-app` has ingress, so that is the only process it can reach —
   while `worker_main.py:49-50` arms its own scheduler with this same job. Toggling the schedule
   off in the UI left the other copy running until the container restarted. Observed: six
   consecutive 5-minute sweeps (18:48:40 → 19:13:40 UTC) straight through a UI toggle.

2. IT REPLACED THE ESTATE WITH THE SAMPLES. On failure it ran `local` instead and saved AND
   finalized that as a scan. Every "latest" view reads `scan_runs ORDER BY completed_at DESC`,
   so a 1-file scan of the bundled corpus displaced a 258-document Drive estate — on the
   dashboard, in the report, and in the scan selector — every five minutes.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def core_mod(monkeypatch):
    import core
    import scanner
    calls = {"scans": [], "saved": 0, "finalized": 0, "reloads": 0}

    class _Store:
        def __init__(self):
            self.schedule = {"enabled": True, "interval_minutes": 5,
                             "owner_email": "a@b.c", "source": "drive"}
            self.sweeps = []
            self.sync_cursors: dict = {}   # source -> {"page_token": ..., "owner_email": ...}
            self.prior_inventory = None    # None = no prior completed scan to reconstruct from
        def get_schedule(self): return dict(self.schedule)
        def get_ai_enabled(self): return False
        def save_scan(self, report): calls["saved"] += 1; return "sid-1"
        # Mirrors Store.record_sweep_outcome. Kept on the double deliberately: a sweep's OUTCOME
        # is now part of what _do_scheduled_scan is responsible for (see the third section
        # below), so a double that omitted it would only prove the method is never called.
        def record_sweep_outcome(self, **kw): self.sweeps.append(kw)
        # PRD Phase 3: mirrors Store.get_sync_cursor/save_sync_cursor. A fresh instance starts
        # with no cursor, so every pre-existing test below (none of which pre-seeds one) takes
        # _drive_sync_plan's "no baseline yet — seed one, never skip" branch and runs exactly as
        # before this feature existed.
        def get_sync_cursor(self, source):
            return dict(self.sync_cursors[source]) if source in self.sync_cursors else None
        def save_sync_cursor(self, source, owner_email, page_token):
            self.sync_cursors[source] = {"source": source, "owner_email": owner_email,
                                         "page_token": page_token}
        # Mirrors Store.latest_scan_inventory_items. None by default, so a test that only wants
        # to prove "a real change triggers a full scan" (not exercise reconstruction itself —
        # see test_drive_changes_sync.py for that) gets exactly today's fallback: no prior scan
        # to reconstruct from, so _drive_sync_plan returns drive_delta=None.
        def latest_scan_inventory_items(self, owner, source):
            return self.prior_inventory

    store = _Store()
    monkeypatch.setattr(core, "get_store", lambda: store)
    monkeypatch.setattr(core, "finalize_scan", lambda *a, **k: calls.__setitem__("finalized", calls["finalized"] + 1))
    monkeypatch.setattr(core, "reload_scheduler", lambda: calls.__setitem__("reloads", calls["reloads"] + 1))

    def _scan(src, **kw):
        calls["scans"].append(src)
        calls.setdefault("drive_deltas", []).append(kw.get("drive_delta"))
        calls.setdefault("sp_deltas", []).append(kw.get("sp_delta"))
        calls.setdefault("sp_tokens", []).append(kw.get("sp_token"))
        calls.setdefault("folders", []).append(kw.get("folder"))
        if src == "drive":
            raise RuntimeError("HttpError 403 ... Request had insufficient authentication scopes.")
        return {"summary": {"files": 1}}

    monkeypatch.setattr(core, "run_scan", _scan)

    # Hermetic doubles for _drive_sync_plan's own calls (it imports these from `scanner` at
    # call time) — no real Drive API access from this test module. Default: seeding a fresh
    # cursor returns "seed-token", and a check against an existing cursor finds no changes
    # (empty list, empty set); individual tests override drive_changes_since to exercise the
    # other branches.
    monkeypatch.setattr(scanner, "_drive_service", lambda token=None: object())
    monkeypatch.setattr(scanner, "drive_start_page_token", lambda svc: "seed-token")
    monkeypatch.setattr(scanner, "drive_changes_since", lambda svc, token: ([], set(), "next-token"))
    return core, store, calls


# ── 1. the setting is authoritative on every fire ─────────────────────────────────────

def test_a_disabled_schedule_runs_nothing(core_mod):
    core, store, calls = core_mod
    store.schedule["enabled"] = False
    core._do_scheduled_scan()
    assert calls["scans"] == [], "a disabled schedule must not scan anything"
    assert calls["saved"] == 0


def test_a_disabled_schedule_disarms_the_job_in_this_process(core_mod):
    """The self-heal. Without it the stale job keeps firing every interval forever — it would
    just do nothing each time, which is correct but wasteful and hides the misconfiguration."""
    core, store, calls = core_mod
    store.schedule["enabled"] = False
    core._do_scheduled_scan()
    assert calls["reloads"] == 1


def test_the_check_is_re_read_not_cached(core_mod):
    """The whole point: a process that armed the job while enabled must notice it was turned
    off elsewhere. This is the worker's case, which no reload_scheduler() call can reach."""
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"]          # armed and enabled — it runs
    store.schedule["enabled"] = False           # turned off in another container
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"], "the second fire must read the setting again and stop"


# ── 2. a failed sweep saves nothing ───────────────────────────────────────────────────

def test_a_drive_failure_does_not_substitute_the_local_corpus(core_mod):
    core, store, calls = core_mod
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"], "it must not run a second scan against a different source"
    assert calls["saved"] == 0, "a failed sweep must not save a scan"
    assert calls["finalized"] == 0, "and must certainly not finalize one"


def test_a_failed_sweep_says_so_and_names_the_error(core_mod, capsys):
    core, store, calls = core_mod
    core._do_scheduled_scan()
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "previous scan stands" in out
    assert "403" in out, "the underlying cause must survive into the log, not be swallowed"


def test_a_failed_sweep_does_not_raise(core_mod):
    """APScheduler would log a job exception and keep going, but a raising job is noise in the
    logs and, with max_instances=1, risks masking the next fire."""
    core, store, calls = core_mod
    core._do_scheduled_scan()   # must not raise


# ── 3. and a failed sweep is recorded, not only logged ────────────────────────────────
#
# "Leaves the last real scan standing" is only honest if somebody is told. Until this was
# recorded, the sole trace was the log line above — inside the container — while every UI surface
# went on presenting an hours-old scan as the live estate. That is how the 403 loop ran unnoticed:
# `last_at` is the last SUCCESSFUL scan, so a failing sweep never moves it and the schedule reads
# as healthy. See tests/test_sweep_failure_visible.py for the /schedule + store half.

def test_a_failed_sweep_records_the_outcome_for_the_ui(core_mod):
    core, store, calls = core_mod
    core._do_scheduled_scan()
    assert len(store.sweeps) == 1
    rec = store.sweeps[0]
    assert rec["ok"] is False
    assert rec["source"] == "drive"
    assert "insufficient authentication scopes" in rec["error"]
    assert rec["when"]


def test_a_successful_sweep_records_ok_so_the_warning_clears(core_mod):
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert store.sweeps[-1]["ok"] is True
    assert store.sweeps[-1]["scan_id"] == "sid-1"
    assert store.sweeps[-1]["files"] == 1


def test_a_disabled_schedule_records_nothing(core_mod):
    """Off is not a failure. Recording one would raise a stale-estate warning about a sweep the
    operator deliberately turned off."""
    core, store, calls = core_mod
    store.schedule["enabled"] = False
    core._do_scheduled_scan()
    assert store.sweeps == []


# ── 4. PRD Phase 3 — the Drive sync gate ──────────────────────────────────────────────

def test_first_ever_sweep_has_nothing_to_compare_against_so_it_scans_and_seeds_a_cursor(core_mod):
    core, store, calls = core_mod
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"], "no cursor yet — nothing to skip, so it must scan"
    assert store.sync_cursors["drive"]["page_token"] == "seed-token"


def test_a_cursor_with_no_changes_skips_the_scan_entirely(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive"] = {"page_token": "tok-1"}
    monkeypatch.setattr(scanner, "drive_changes_since", lambda svc, token: ([], set(), "tok-2"))
    core._do_scheduled_scan()
    assert calls["scans"] == [], "nothing changed — a full re-scan must not run"
    assert calls["saved"] == 0
    assert store.sync_cursors["drive"]["page_token"] == "tok-2", "the cursor still advances"


def test_a_skipped_sweep_is_recorded_distinctly_from_a_zero_file_scan(core_mod, monkeypatch):
    """skipped=True with files=None must never look like 'a scan ran and saw 0 files' —
    those already mean something different (a legitimately small ADC-scoped estate)."""
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive"] = {"page_token": "tok-1"}
    monkeypatch.setattr(scanner, "drive_changes_since", lambda svc, token: ([], set(), "tok-2"))
    core._do_scheduled_scan()
    rec = store.sweeps[-1]
    assert rec["ok"] is True
    assert rec["skipped"] is True
    assert rec.get("files") is None
    assert rec.get("scan_id") is None


def test_a_cursor_with_changes_but_no_prior_scan_runs_a_full_fresh_scan(core_mod, monkeypatch):
    """A cursor exists (so a change-check was possible) but latest_scan_inventory_items is None
    — every prior sweep since the cursor was seeded must have failed before saving. Nothing to
    reconstruct FROM, so this falls back to today's full listing (drive_delta=None), not a
    reconstruction built on nothing."""
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive"] = {"page_token": "tok-1"}
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, token: ([{"id": "F1", "name": "changed.pdf"}], set(), "tok-2"))
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"], "a real change must trigger a scan, not a skip"
    assert calls["drive_deltas"] == [None], "no prior inventory to reconstruct from"
    assert store.sync_cursors["drive"]["page_token"] == "tok-2"


def test_a_cursor_with_changes_and_a_prior_scan_reconstructs_instead_of_a_fresh_listing(
        core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive"] = {"page_token": "tok-1"}
    store.prior_inventory = [{"file": "unchanged.pdf", "drive_file_id": "F0", "mime": "application/pdf",
                             "size_kb": 1, "checksum": "x", "created_at": None,
                             "source_modified": None, "owner": None, "parent_folder": None}]
    changed_file = {"id": "F1", "name": "changed.pdf", "mimeType": "application/pdf"}
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, token: ([changed_file], set(), "tok-2"))
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"]
    [delta] = calls["drive_deltas"]
    assert delta is not None, "a prior scan exists — must reconstruct, not fall back to a full listing"
    assert delta["changed"] == [changed_file]
    assert delta["removed_ids"] == set()
    assert [f["id"] for f in delta["prior_files"]] == ["F0"]


def test_a_cursor_with_removed_files_also_triggers_a_scan(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive"] = {"page_token": "tok-1"}
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, token: ([], {"F1", "F2", "F3"}, "tok-2"))
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"], "a removal is still a change — must not be skipped"


def test_a_failed_change_check_falls_back_to_a_full_scan_never_a_skip(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive"] = {"page_token": "tok-1"}
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, token: (_ for _ in ()).throw(RuntimeError("HttpError 404")))
    core._do_scheduled_scan()
    assert calls["scans"] == ["drive"], "an uncertain check must never cause a skip"
    # the failing scan itself is still recorded as a failure, not silently swallowed
    assert store.sweeps[-1]["ok"] is False


def test_a_non_drive_source_never_consults_the_gate(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.schedule["source"] = "local"

    def _boom(*a, **k):
        raise AssertionError("the drive sync gate must not run for a non-drive source")
    monkeypatch.setattr(scanner, "drive_changes_since", _boom)
    monkeypatch.setattr(scanner, "drive_start_page_token", _boom)
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"]


# ── 5. PRD Phase 3 — the SharePoint sync gate ─────────────────────────────────────────
#
# Mirrors section 4 above, for Microsoft Graph. Originally gate-or-not only (no checksum on a
# SharePoint item, so no reconstruction was possible) — #963 added the checksum and this section
# (item 10) added the reconstruction step itself, so _sp_sync_plan now has the SAME three-way
# contract _drive_sync_plan does: skip, reconstruct, or fall back to a full listing.

def test_an_unconfigured_sharepoint_sync_leaves_token_and_folder_none(core_mod, monkeypatch):
    """Zero behavior change until ACP_SP_SYNC_* is configured: the gate is never consulted,
    sp_token/folder stay None, and the scan proceeds exactly as it always has (the same
    PermissionError path it always had with no unattended SharePoint credential)."""
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: False)

    def _boom(*a, **k):
        raise AssertionError("the sharepoint sync gate must not run when unconfigured")
    monkeypatch.setattr(core, "_sp_sync_plan", _boom)

    core._do_scheduled_scan()
    assert calls["scans"] == ["sharepoint"]
    assert calls["sp_tokens"] == [None]
    assert calls["folders"] == [None]


def test_first_ever_sharepoint_sweep_seeds_a_cursor_and_does_not_skip(core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([], set(), "link-1"))

    core._do_scheduled_scan()
    assert calls["scans"] == ["sharepoint"], "no cursor yet — nothing to skip, so it must scan"
    assert calls["sp_tokens"] == ["TOK1"]
    assert calls["folders"] == ["drv-1/root"]
    assert store.sync_cursors["sharepoint"]["page_token"] == "link-1"


def test_a_sharepoint_cursor_with_no_changes_skips_the_scan_entirely(core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    store.sync_cursors["sharepoint"] = {"page_token": "tok-1"}
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([], set(), "tok-2"))

    core._do_scheduled_scan()
    assert calls["scans"] == [], "nothing changed — a full re-scan must not run"
    assert calls["saved"] == 0
    assert store.sync_cursors["sharepoint"]["page_token"] == "tok-2", "the cursor still advances"


def test_a_skipped_sharepoint_sweep_is_recorded_distinctly_from_a_zero_file_scan(
        core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    store.sync_cursors["sharepoint"] = {"page_token": "tok-1"}
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([], set(), "tok-2"))

    core._do_scheduled_scan()
    rec = store.sweeps[-1]
    assert rec["ok"] is True
    assert rec["skipped"] is True
    assert rec.get("files") is None
    assert rec.get("scan_id") is None


def test_a_sharepoint_cursor_with_changes_triggers_a_full_scan_with_the_app_token(
        core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    store.sync_cursors["sharepoint"] = {"page_token": "tok-1"}
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")
    changed_file = {"id": "I1", "name": "changed.pptx"}
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([changed_file], set(), "tok-2"))

    core._do_scheduled_scan()
    assert calls["scans"] == ["sharepoint"], "a real change must trigger a scan, not a skip"
    assert calls["sp_tokens"] == ["TOK1"], "the sync app's own token authenticates the scan"
    assert calls["folders"] == ["drv-1/root"], "the whole configured library, no site enumeration"
    assert store.sync_cursors["sharepoint"]["page_token"] == "tok-2"
    assert calls["sp_deltas"] == [None], "no prior inventory to reconstruct from"


def test_a_sharepoint_cursor_with_changes_and_a_prior_scan_reconstructs_instead_of_a_fresh_listing(
        core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    store.sync_cursors["sharepoint"] = {"page_token": "tok-1"}
    store.prior_inventory = [{"file": "unchanged.pptx", "drive_file_id": "F0",
                             "mime": "application/vnd.openxmlformats-officedocument"
                                    ".presentationml.presentation",
                             "size_kb": 1, "checksum": "x", "created_at": None,
                             "source_modified": None, "owner": None, "parent_folder": None,
                             "drive_id": "drv-1"}]
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")
    changed_file = {"id": "I1", "name": "changed.pptx",
                    "parentReference": {"driveId": "drv-1"}}
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([changed_file], set(), "tok-2"))

    core._do_scheduled_scan()
    assert calls["scans"] == ["sharepoint"]
    [delta] = calls["sp_deltas"]
    assert delta is not None, "a prior scan exists — must reconstruct, not fall back to a full listing"
    assert delta["changed"] == [changed_file]
    assert delta["removed_ids"] == set()
    assert [f["id"] for f in delta["prior_files"]] == ["F0"]


def test_a_sharepoint_cursor_with_removed_files_also_triggers_a_scan(core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    store.sync_cursors["sharepoint"] = {"page_token": "tok-1"}
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([], {("drv-1", "I1")}, "tok-2"))

    core._do_scheduled_scan()
    assert calls["scans"] == ["sharepoint"], "a removal is still a change — must not be skipped"


def test_a_failed_sharepoint_change_check_falls_back_to_a_full_scan_never_a_skip(
        core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store, calls = core_mod
    store.schedule["source"] = "sharepoint"
    store.sync_cursors["sharepoint"] = {"page_token": "tok-1"}
    monkeypatch.setattr(sp_sync, "sp_sync_configured", lambda: True)
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: "drv-1")
    monkeypatch.setattr(sp_sync, "app_token", lambda: "TOK1")

    def _boom(token, drive_id, link):
        raise RuntimeError("http 410")
    monkeypatch.setattr(scanner, "sp_delta_since", _boom)

    core._do_scheduled_scan()
    assert calls["scans"] == ["sharepoint"], "an uncertain check must never cause a skip"


# ── the happy path still works ────────────────────────────────────────────────────────

def test_a_working_sweep_scans_saves_and_finalizes_once(core_mod):
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert calls["scans"] == ["local"]
    assert (calls["saved"], calls["finalized"]) == (1, 1)


def test_the_owner_is_carried_through_so_the_scan_is_attributable(core_mod, capsys):
    core, store, calls = core_mod
    store.schedule["source"] = "local"
    core._do_scheduled_scan()
    assert "owner=a@b.c" in capsys.readouterr().out
