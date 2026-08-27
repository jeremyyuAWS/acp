"""The three ways Discovery could still record a zero nobody could question.

Each of these is a case where the listing came back clean and empty, and every surface then
presented that emptiness as a fact about the estate:

  * the source was never actually read (a root the credential cannot see returns 200 + no items)
  * the scan was REFUSED for a concurrent-discovery conflict, and only the scan row said so —
    the job/SSE channel still described a finished run
  * a scan that crashed, resumed and finished correctly never got its published_at, so the flag
    meant "incomplete OR merely retried" and could not be read as evidence by anything

Companion to test_discovery_guard.py, which covers the baseline the suspicious-zero check
compares against.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


# ── the reachability probe ────────────────────────────────────────────────────────────────────

class TestRootsReachable:
    """`_roots_reachable` — one metadata call per root, never a listing.

    Its whole job is to separate "read the source, found nothing" from "never read the source",
    which the listing alone cannot do.
    """

    def _probe(self, **kw):
        import handlers
        return handlers._roots_reachable(**kw)

    def test_local_corpus_that_is_not_a_directory_is_unreachable(self, tmp_path):
        missing = tmp_path / "not-mounted"
        ok, why = self._probe(source="local", svc=None, roots=None, sp_token=None, corpus=missing)
        assert ok is False
        assert "not a readable directory" in why

    def test_local_corpus_that_exists_is_reachable(self, tmp_path):
        ok, why = self._probe(source="local", svc=None, roots=None, sp_token=None, corpus=tmp_path)
        assert (ok, why) == (True, None)

    def test_drive_root_the_token_cannot_see_is_unreachable(self):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.side_effect = PermissionError("403")
        ok, why = self._probe(source="drive", svc=svc, roots=["folder-a"], sp_token=None, corpus=None)
        assert ok is False
        assert "unreachable" in why

    def test_drive_root_that_reads_is_reachable(self):
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {"id": "folder-a"}
        ok, why = self._probe(source="drive", svc=svc, roots=["folder-a"], sp_token=None, corpus=None)
        assert (ok, why) == (True, None)

    def test_a_trashed_drive_root_is_unreachable(self):
        # Reads fine, and is not the estate anyone selected. Empty from a trashed folder is not
        # evidence of an empty estate.
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {"id": "f", "trashed": True}
        ok, why = self._probe(source="drive", svc=svc, roots=["f"], sp_token=None, corpus=None)
        assert ok is False
        assert "trashed" in why

    def test_only_a_real_true_counts_as_trashed(self):
        # `trashed` is a JSON boolean from Drive. Reading it by truthiness condemned every root
        # whose metadata came back as anything else — a scan refused over a field never actually
        # seen. Caught by three token-forwarding tests whose fake service returns a MagicMock.
        svc = MagicMock()
        svc.files.return_value.get.return_value.execute.return_value = {"id": "f", "trashed": "no"}
        ok, why = self._probe(source="drive", svc=svc, roots=["f"], sp_token=None, corpus=None)
        assert (ok, why) == (True, None)

    def test_sharepoint_without_a_token_is_unreachable(self):
        ok, why = self._probe(source="sharepoint", svc=None, roots=None, sp_token=None, corpus=None)
        assert ok is False
        assert "unauthenticated" in why

    def test_a_root_call_that_fails_counts_as_unreachable(self):
        # Not-confirmed is the point. The question the probe answers is whether an empty listing
        # is EVIDENCE about the estate, and a root nobody could read makes it not evidence —
        # whatever the call failed with.
        svc = MagicMock()
        svc.files.side_effect = RuntimeError("dead service object")
        ok, why = self._probe(source="drive", svc=svc, roots=["x"], sp_token=None, corpus=None)
        assert ok is False
        assert "unreachable" in why

    def test_the_probe_breaking_internally_falls_open(self):
        # Distinct from the case above: this is a bug in the probe, not a fact about the source.
        # `list(roots)` on a non-iterable raises before any root is examined. A defect in here
        # must not become a scan outage for estates that were fine.
        ok, why = self._probe(source="drive", svc=MagicMock(), roots=object(),
                              sp_token=None, corpus=None)
        assert (ok, why) == (True, None)


# ── published_at across a resume ──────────────────────────────────────────────────────────────

class TestPublishedAtSurvivesAResume:
    """published_at has to mean one thing for anything to be able to read it.

    The stamp was skipped whenever the run resumed from a checkpoint, so its absence meant
    "enumeration was incomplete" OR "this scan was retried". Ambiguous, so a consumer that fell
    back to the last published snapshot would have skipped perfectly good scans — which is why
    nothing consumed it.
    """

    def test_enumeration_persisted_on_the_first_attempt_is_readable_on_the_second(self, isolated_store):
        # What the resume path now reads back instead of skipping the stamp: attempt 1 wrote the
        # enumeration via merge_scan_scope before it died, and a resume only happens once
        # inventory rows exist, which is written after that.
        isolated_store.init_scan_run("s1", "drive", 0, "2026-01-01T00:00:00", "rb", "h",
                                     owner="o@x.com", status="running")
        isolated_store.merge_scan_scope("s1", {"enumeration": {"complete": True, "files_found": 7}})

        scope = ((isolated_store.get_scan("s1", owner="o@x.com") or {}).get("run") or {}).get("scope") or {}
        assert scope.get("enumeration", {}).get("complete") is True

    def test_mark_published_is_set_once_so_a_redelivered_job_cannot_move_it(self, isolated_store):
        isolated_store.init_scan_run("s2", "drive", 0, "2026-01-01T00:00:00", "rb", "h",
                                     owner="o@x.com", status="running")
        first = isolated_store.mark_published("s2")
        again = isolated_store.mark_published("s2", at="2099-01-01T00:00:00")
        assert first is not None and again == first

    def test_a_truncated_enumeration_stays_unpublished(self, isolated_store):
        # The other half: reading the flag back must not publish a snapshot that IS incomplete.
        isolated_store.init_scan_run("s3", "drive", 0, "2026-01-01T00:00:00", "rb", "h",
                                     owner="o@x.com", status="running")
        isolated_store.merge_scan_scope("s3", {"enumeration": {"complete": False, "truncated": True}})
        scope = ((isolated_store.get_scan("s3", owner="o@x.com") or {}).get("run") or {}).get("scope") or {}
        assert scope["enumeration"]["complete"] is False
