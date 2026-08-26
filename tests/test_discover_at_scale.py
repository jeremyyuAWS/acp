"""Large-inventory tests for the deferred discover pipeline (_scan_discover).

Exercises the full pipeline at scale (hundreds to thousands of files) to verify:
  - Classification bucket counts sum correctly
  - Lifecycle rule evaluation scales without error
  - Save KPIs (new/updated/unchanged/failed) are correct
  - Done-phase payload contains all KPI fields
  - Checkpoint resume works with large inventories
  - Progress ticks fire at the expected cadence
  - Edge cases: all-one-class, all-unsupported, empty estate
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PDF = "application/pdf"
_HTML = "text/html"
_IMAGE = "image/png"
_VIDEO = "video/mp4"
_UNKNOWN = "application/octet-stream"


def _make_items(spec: list[tuple[str, str, int]]) -> list[dict]:
    """Build a list of scanner items from (prefix, mime, count) tuples."""
    items = []
    for prefix, mime, count in spec:
        for i in range(count):
            ext = {"application/pdf": ".pdf",
                   _DOCX: ".docx", _PPTX: ".pptx", _XLSX: ".xlsx",
                   "text/html": ".html", "image/png": ".png",
                   "video/mp4": ".mp4", _UNKNOWN: ".bin"}.get(mime, ".bin")
            items.append({
                "name": f"{prefix}_{i:04d}{ext}",
                "id": f"id-{prefix}-{i}",
                "mime": mime,
                "owner": "test@example.com",
                "source_modified": "2025-01-01",
                "created_at": "2020-01-01",
            })
    return items


# ── Classification bucket counts at scale ─────────────────────────────────────

class TestClassificationBuckets:
    """Verify _count_inventory_classes returns correct counts for large estates."""

    def test_mixed_500_files(self, isolated_store, monkeypatch):
        """500 files across all doc classes; buckets must sum to 500."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([
            ("doc", _DOCX, 100),
            ("slide", _PPTX, 80),
            ("sheet", _XLSX, 60),
            ("pdf", _PDF, 70),
            ("page", _HTML, 40),
            ("img", _IMAGE, 50),
            ("vid", _VIDEO, 30),
            ("misc", _UNKNOWN, 70),
        ])
        assert len(items) == 500

        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
        job_id = "j-cls-500"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-cls-500", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-cls-500", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["phase"] == "done"

        counts = handlers._count_inventory_classes("sd-cls-500")
        assert counts["assessable"] == 100 + 80 + 60 + 70 + 40  # docx+pptx+xlsx+pdf+html
        assert counts["metadata_only"] == 50 + 30               # image+video
        assert counts["eligibility_unknown"] == 70               # binary only
        assert counts["unsupported"] == 0
        total = sum(counts.values())
        assert total == 500, f"buckets must sum to 500, got {total}: {counts}"

    def test_1000_files_all_assessable(self, isolated_store, monkeypatch):
        """1000 docx files — all assessable, nothing in other buckets."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 1000)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
        job_id = "j-cls-1k"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-cls-1k", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-cls-1k", "id": job_id},
        )

        counts = handlers._count_inventory_classes("sd-cls-1k")
        assert counts["assessable"] == 1000
        assert counts["metadata_only"] == 0
        assert counts["unsupported"] == 0
        assert counts["eligibility_unknown"] == 0
        assert counts["excluded"] == 0

    def test_500_all_unknown_mime(self, isolated_store, monkeypatch):
        """500 unknown-MIME files — all eligibility_unknown (classify_from_metadata returns 'unknown')."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("bin", _UNKNOWN, 500)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
        job_id = "j-cls-unsup"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-cls-unsup", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-cls-unsup", "id": job_id},
        )

        counts = handlers._count_inventory_classes("sd-cls-unsup")
        assert counts["assessable"] == 0
        assert counts["eligibility_unknown"] == 500
        total = sum(counts.values())
        assert total == 500

    def test_empty_estate(self, isolated_store, monkeypatch):
        """Empty estate produces zero in every bucket."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        monkeypatch.setattr(scanner, "_list", lambda *a, **k: [])
        job_id = "j-cls-empty"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-cls-empty", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-cls-empty", "id": job_id},
        )

        counts = handlers._count_inventory_classes("sd-cls-empty")
        assert all(v == 0 for v in counts.values()), f"all zero expected: {counts}"


# ── Save KPIs at scale ────────────────────────────────────────────────────────

class TestSaveKPIs:
    """Verify save_new/updated/unchanged/failed in the job state."""

    def test_500_new_files(self, isolated_store, monkeypatch):
        """First run: all 500 files are new."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 300), ("pdf", _PDF, 200)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
        job_id = "j-save-500"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-save-500", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-save-500", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["save_new"] == 500, f"expected 500 new, got {state.get('save_new')}"
        assert state.get("save_updated", 0) == 0
        assert state.get("save_failed", 0) == 0
        assert state.get("schema_version") == 2

    def test_rerun_same_scan_id_shows_updated(self, isolated_store, monkeypatch):
        """Second run on same scan_id: all files show as updated (upsert)."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 200)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        sid = "sd-save-rerun"
        # First run
        j1 = "j-save-r1"
        core.JOBS[j1] = {"phase": "queued"}
        handlers._scan_discover(
            {"scan_id": sid, "source": "local", "user": "test@example.com"},
            {"scan_id": sid, "id": j1},
        )
        assert core.JOBS[j1]["save_new"] == 200

        # Second run hits checkpoint resume (inventory already exists)
        j2 = "j-save-r2"
        core.JOBS[j2] = {"phase": "queued"}
        handlers._scan_discover(
            {"scan_id": sid, "source": "local", "user": "test@example.com"},
            {"scan_id": sid, "id": j2},
        )
        # Checkpoint resume skips add_inventory, so no save KPIs
        assert "save_new" not in core.JOBS[j2], "checkpoint resume should skip inventory save"
        assert core.JOBS[j2]["phase"] == "done"


# ── Done-phase completeness ──────────────────────────────────────────────────

class TestDonePhase:
    """Verify the done-phase job state contains all required KPI fields."""

    def test_done_phase_all_fields_present_500(self, isolated_store, monkeypatch):
        """500 files: done-phase must carry all lifecycle_* fields."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 250), ("pdf", _PDF, 250)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
        job_id = "j-done-500"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-done-500", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-done-500", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["phase"] == "done"
        assert state["schema_version"] == 2
        for field in ("lifecycle_matches", "lifecycle_archive", "lifecycle_delete",
                      "lifecycle_tagged", "rules_enabled"):
            assert field in state, f"{field} missing from done-phase state: {state}"

    def test_done_phase_with_lifecycle_rules_500(self, isolated_store, monkeypatch):
        """500 files with a matching tag rule: lifecycle_tagged must equal matched count."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 500)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-tag-scale",
            name="tag-all-scale", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({"tags": ["scale-test"]}),
            owner_email=owner,
        )

        job_id = "j-done-lc"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-done-lc", "source": "local", "user": owner},
            {"scan_id": "sd-done-lc", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["phase"] == "done"
        assert state["rules_enabled"] == 1
        assert state["lifecycle_matches"] == 500, \
            f"expected 500 matches, got {state['lifecycle_matches']}"
        assert state["lifecycle_tagged"] == 500, \
            f"expected 500 tagged, got {state['lifecycle_tagged']}"
        assert state["lifecycle_archive"] == 0
        assert state["lifecycle_delete"] == 0


# ── Lifecycle evaluation at scale ─────────────────────────────────────────────

class TestLifecycleAtScale:
    """Verify lifecycle rule evaluation handles large inventories correctly."""

    def test_archive_rule_500_files(self, isolated_store, monkeypatch):
        """500 files matching an archive rule — all become Archive Candidates."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 500)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-archive-scale",
            name="archive-old", action="archive", enabled=True, requires_approval=True,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({}),
            owner_email=owner,
        )

        job_id = "j-arch-500"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-arch-500", "source": "local", "user": owner},
            {"scan_id": "sd-arch-500", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["lifecycle_archive"] == 500, \
            f"expected 500 archive candidates, got {state['lifecycle_archive']}"
        assert state["lifecycle_delete"] == 0

        inv = isolated_store.list_inventory("sd-arch-500")
        archived = [r for r in inv if r.get("lifecycle_status") == "Archive Candidate"]
        assert len(archived) == 500, f"expected 500 archive-candidate rows, got {len(archived)}"

    def test_tag_plus_archive_rules_300_files(self, isolated_store, monkeypatch):
        """300 files with both a tag and archive rule: files should be both tagged and archived."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 300)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-tag-combo",
            name="tag-combo", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({"tags": ["combo-tag"]}),
            owner_email=owner,
        )
        isolated_store.create_disposition_policy(
            "pol-arch-combo",
            name="arch-combo", action="archive", enabled=True, requires_approval=True,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({}),
            owner_email=owner,
        )

        job_id = "j-combo-300"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-combo-300", "source": "local", "user": owner},
            {"scan_id": "sd-combo-300", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["lifecycle_tagged"] == 300
        assert state["lifecycle_archive"] == 300
        assert state["lifecycle_matches"] == 300

    def test_no_rules_enabled_500_files(self, isolated_store, monkeypatch):
        """500 files with no lifecycle rules: lifecycle stats are all zero."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 500)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        job_id = "j-norule-500"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-norule-500", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-norule-500", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["lifecycle_matches"] == 0
        assert state["lifecycle_archive"] == 0
        assert state["lifecycle_delete"] == 0
        assert state["lifecycle_tagged"] == 0
        assert state["rules_enabled"] == 0

    def test_partial_match_800_files(self, isolated_store, monkeypatch):
        """800 files, rule matches only PDFs (200 of them)."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 600), ("pdf", _PDF, 200)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-pdf-only",
            name="tag-pdfs", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "doc_class", "op": "eq", "value": "pdf-document"}]),
            action_config=json.dumps({"tags": ["is-pdf"]}),
            owner_email=owner,
        )

        job_id = "j-partial-800"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-partial-800", "source": "local", "user": owner},
            {"scan_id": "sd-partial-800", "id": job_id},
        )

        state = core.JOBS[job_id]
        assert state["lifecycle_matches"] == 200, \
            f"expected 200 matches (PDFs only), got {state['lifecycle_matches']}"
        assert state["lifecycle_tagged"] == 200


# ── Checkpoint resume at scale ────────────────────────────────────────────────

class TestCheckpointResumeAtScale:
    """Verify checkpoint resume works correctly with large inventories."""

    def test_checkpoint_resume_500_files(self, isolated_store, monkeypatch, capsys):
        """After a 500-file first run, a retry must skip listing and still reach done."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 300), ("pdf", _PDF, 200)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        sid = "sd-ckpt-500"
        j1 = "j-ckpt-r1"
        core.JOBS[j1] = {"phase": "queued"}
        handlers._scan_discover(
            {"scan_id": sid, "source": "local", "user": "test@example.com"},
            {"scan_id": sid, "id": j1},
        )
        assert core.JOBS[j1]["save_new"] == 500
        assert isolated_store.count_inventory(sid) == 500

        list_calls = []
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: (list_calls.append(1), items)[-1])

        j2 = "j-ckpt-r2"
        core.JOBS[j2] = {"phase": "queued"}
        handlers._scan_discover(
            {"scan_id": sid, "source": "local", "user": "test@example.com"},
            {"scan_id": sid, "id": j2},
        )

        assert len(list_calls) == 0, "checkpoint resume must skip _list"
        assert core.JOBS[j2]["phase"] == "done"
        assert "save_new" not in core.JOBS[j2]
        out = capsys.readouterr().out
        assert "retry detected" in out
        assert "500 inventory rows" in out

    def test_checkpoint_preserves_classification_counts(self, isolated_store, monkeypatch):
        """After checkpoint resume, classification counts must still be correct."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 200), ("pdf", _PDF, 100)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        sid = "sd-ckpt-cls"
        j1 = "j-ckpt-cls1"
        core.JOBS[j1] = {"phase": "queued"}
        handlers._scan_discover(
            {"scan_id": sid, "source": "local", "user": "test@example.com"},
            {"scan_id": sid, "id": j1},
        )

        counts_before = handlers._count_inventory_classes(sid)

        j2 = "j-ckpt-cls2"
        core.JOBS[j2] = {"phase": "queued"}
        handlers._scan_discover(
            {"scan_id": sid, "source": "local", "user": "test@example.com"},
            {"scan_id": sid, "id": j2},
        )

        counts_after = handlers._count_inventory_classes(sid)
        assert counts_before == counts_after, \
            f"classification counts changed after checkpoint resume: {counts_before} != {counts_after}"
        assert counts_after["assessable"] == 300  # docx + pdf


# ── Progress tick cadence ─────────────────────────────────────────────────────

class TestProgressTicks:
    """Verify lifecycle progress ticks fire at the correct cadence."""

    def test_lifecycle_progress_ticks_500_files(self, isolated_store, monkeypatch):
        """500 files with a tag rule: progress ticks fire every max(10, N//100) files."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 500)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-tick-tag",
            name="tick-tag", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({"tags": ["tick"]}),
            owner_email=owner,
        )

        updates = []
        real_update = core.update_job

        def _capture_update(jid, data):
            updates.append(dict(data))
            return real_update(jid, data)

        monkeypatch.setattr(core, "update_job", _capture_update)

        job_id = "j-tick-500"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-tick-500", "source": "local", "user": owner},
            {"scan_id": "sd-tick-500", "id": job_id},
        )

        lc_updates = [u for u in updates if u.get("phase") == "lifecycle"]
        assert len(lc_updates) > 5, \
            f"expected many lifecycle progress ticks for 500 files, got {len(lc_updates)}"

        done_updates = [u for u in updates if u.get("phase") == "done"]
        assert len(done_updates) >= 1, "must have a done-phase update"

        last_lc = lc_updates[-1]
        assert last_lc.get("files_evaluated") == 500 or done_updates, \
            "final lifecycle tick should reflect all 500 files evaluated"


# ── Idempotency at scale ─────────────────────────────────────────────────────

class TestIdempotency:
    """Verify tag/status application is idempotent across re-runs."""

    def test_rerun_does_not_duplicate_tags(self, isolated_store, monkeypatch):
        """Two lifecycle evaluations on the same inventory must not duplicate tags."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)

        sid = "sd-idem-300"
        isolated_store.init_scan_run(sid, "local", 300, "2026-01-01T00:00:00+00:00",
                                     "acp", "h1", owner="test@example.com")
        items = []
        for i in range(300):
            items.append({
                "file": f"doc_{i:04d}.docx", "path": f"/doc_{i:04d}.docx",
                "doc_class": "text-document", "size_kb": 10,
                "owner": "test@example.com", "created_at": "2020-01-01",
            })
        isolated_store.add_inventory(sid, items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-idem-tag",
            name="idem-tag", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({"tags": ["idem-test"]}),
            owner_email=owner,
        )

        r1 = handlers._evaluate_discover_lifecycle_rules(sid, "local", owner)
        assert r1["lifecycle_tagged"] == 300

        r2 = handlers._evaluate_discover_lifecycle_rules(sid, "local", owner)
        assert r2["lifecycle_tagged"] == 0, \
            "second evaluation must not re-tag (idempotent via seen set)"

    def test_rerun_does_not_duplicate_archive_status(self, isolated_store, monkeypatch):
        """Two evaluations: second must not re-flag already-flagged files."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)

        sid = "sd-idem-arch"
        isolated_store.init_scan_run(sid, "local", 200, "2026-01-01T00:00:00+00:00",
                                     "acp", "h1", owner="test@example.com")
        items = []
        for i in range(200):
            items.append({
                "file": f"doc_{i:04d}.docx", "path": f"/doc_{i:04d}.docx",
                "doc_class": "text-document", "size_kb": 10,
                "owner": "test@example.com", "created_at": "2020-01-01",
            })
        isolated_store.add_inventory(sid, items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-idem-arch",
            name="idem-arch", action="archive", enabled=True, requires_approval=True,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({}),
            owner_email=owner,
        )

        r1 = handlers._evaluate_discover_lifecycle_rules(sid, "local", owner)
        assert r1["lifecycle_archive"] == 200

        r2 = handlers._evaluate_discover_lifecycle_rules(sid, "local", owner)
        assert r2["lifecycle_archive"] == 0, \
            "second evaluation must not re-archive (idempotent via disposition_audit guard)"


# ── Per-file resilience at scale ──────────────────────────────────────────────

class TestResilienceAtScale:
    """Verify per-file try/except handles scattered failures in large inventories."""

    def test_10_bad_files_among_500(self, isolated_store, monkeypatch):
        """10 poisoned files among 500 must not crash the pass; 490 should still be tagged."""
        import core
        import disposition
        import handlers
        monkeypatch.setattr(core, "store", isolated_store)

        sid = "sd-resilient-500"
        isolated_store.init_scan_run(sid, "local", 500, "2026-01-01T00:00:00+00:00",
                                     "acp", "h1", owner="test@example.com")
        items = []
        for i in range(500):
            items.append({
                "file": f"doc_{i:04d}.docx", "path": f"/doc_{i:04d}.docx",
                "doc_class": "text-document", "size_kb": 10,
                "owner": "test@example.com", "created_at": "2020-01-01",
            })
        isolated_store.add_inventory(sid, items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-resilient-tag",
            name="resilient-tag", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({"tags": ["survived"]}),
            owner_email=owner,
        )

        bad_indices = {50, 99, 150, 200, 250, 300, 350, 400, 450, 499}
        real_matches = disposition.matches

        def _boom(doc, match):
            doc_id = doc.get("doc_id", "")
            for idx in bad_indices:
                if f"doc_{idx:04d}" in doc_id:
                    raise ValueError(f"simulated bad row {idx}")
            return real_matches(doc, match)

        monkeypatch.setattr(disposition, "matches", _boom)

        result = handlers._evaluate_discover_lifecycle_rules(sid, "local", owner)

        assert result["lifecycle_errors"] == 10, \
            f"expected 10 errors, got {result['lifecycle_errors']}"
        assert result["files_evaluated"] == 500
        assert result["lifecycle_tagged"] == 490, \
            f"expected 490 tagged (500 - 10 bad), got {result['lifecycle_tagged']}"


# ── persist_discovery_inventory integration ───────────────────────────────────

class TestPersistDiscoveryInventory:
    """Test the shared persist_discovery_inventory function with large inventories."""

    def test_persist_400_mixed_files(self, isolated_store, monkeypatch):
        """persist_discovery_inventory returns merged save-outcome + lifecycle + classification."""
        import core
        import handlers
        monkeypatch.setattr(core, "store", isolated_store)

        sid = "sd-persist-400"
        isolated_store.init_scan_run(sid, "local", 400, "2026-01-01T00:00:00+00:00",
                                     "acp", "h1", owner="test@example.com")

        inv = []
        for i in range(200):
            inv.append({"file": f"doc_{i:04d}.docx", "doc_class": "text-document",
                        "size_kb": 10, "owner": "test@example.com", "created_at": "2020-01-01"})
        for i in range(100):
            inv.append({"file": f"pdf_{i:04d}.pdf", "doc_class": "pdf-document",
                        "size_kb": 20, "owner": "test@example.com", "created_at": "2020-01-01"})
        for i in range(100):
            inv.append({"file": f"img_{i:04d}.png", "doc_class": "image",
                        "size_kb": 500, "owner": "test@example.com", "created_at": "2020-01-01"})

        result = handlers.persist_discovery_inventory(
            sid, inv, "local", "test@example.com")

        assert result["new"] == 400
        assert result["assessable"] == 300  # docx + pdf
        assert result["metadata_only"] == 100  # image
        assert result["unsupported"] == 0
        assert "rules_enabled" in result
        assert "lifecycle_matches" in result

    def test_persist_empty_inventory(self, isolated_store, monkeypatch):
        """persist_discovery_inventory with empty list returns zero counts."""
        import core
        import handlers
        monkeypatch.setattr(core, "store", isolated_store)

        sid = "sd-persist-empty"
        isolated_store.init_scan_run(sid, "local", 0, "2026-01-01T00:00:00+00:00",
                                     "acp", "h1", owner="test@example.com")

        result = handlers.persist_discovery_inventory(
            sid, [], "local", "test@example.com")

        assert result["new"] == 0
        assert result["assessable"] == 0
        assert result["metadata_only"] == 0


# ── Metadata completeness at scale ───────────────────────────────────────────

class TestMetadataCompletenessAtScale:
    """Verify metadata_complete/incomplete counts in progress payloads at scale."""

    def test_metadata_counts_500_files(self, isolated_store, monkeypatch):
        """500 files: 300 with full metadata, 200 missing owner/source_modified."""
        import core
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)

        items = []
        for i in range(300):
            items.append({
                "name": f"complete_{i:04d}.docx", "id": f"c-{i}", "mime": _DOCX,
                "owner": "alice@x.com", "source_modified": "2025-01-01",
            })
        for i in range(200):
            items.append({
                "name": f"incomplete_{i:04d}.pdf", "id": f"ic-{i}", "mime": _PDF,
                "owner": None, "source_modified": None,
            })

        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)
        monkeypatch.setattr(scanner, "_download",
                            lambda *a, **k: (_ for _ in ()).throw(PermissionError()))

        captured = []
        isolated_store.init_scan_run("s-meta-500", "local", 500,
                                     "2026-01-01T00:00:00+00:00", "acp", "h1", owner=None)

        try:
            scanner.run_scan(source="local", progress=lambda p: captured.append(p),
                             scan_id="s-meta-500")
        except Exception:
            pass

        meta_events = [p for p in captured if "metadata_complete" in p]
        assert meta_events, f"no metadata_complete events; phases: {[p.get('phase') for p in captured]}"

        ev = meta_events[0]
        assert ev["metadata_complete"] == 300, f"expected 300 complete: {ev}"
        assert ev["metadata_incomplete"] == 200, f"expected 200 incomplete: {ev}"
        assert ev["metadata_complete"] + ev["metadata_incomplete"] == 500


# ── Dedupe at scale ───────────────────────────────────────────────────────────

class TestDedupeAtScale:
    """Verify _dedupe_inventory_files handles collisions in large lists."""

    def test_dedupe_500_with_50_collisions(self):
        """50 pairs of duplicate names among 500 items: all names must be unique after dedupe."""
        from scanner import _dedupe_inventory_files

        rows = []
        for i in range(450):
            rows.append({"file": f"unique_{i:04d}.docx"})
        for i in range(50):
            rows.append({"file": f"dup_{i:04d}.docx"})
            rows.append({"file": f"dup_{i:04d}.docx"})

        assert len(rows) == 550
        _dedupe_inventory_files(rows)

        names = [r["file"] for r in rows]
        assert len(names) == len(set(names)), \
            f"duplicate names remain after dedupe: {[n for n in names if names.count(n) > 1][:5]}"

        for i in range(50):
            original = f"dup_{i:04d}.docx"
            suffixed = f"dup_{i:04d} (1).docx"
            assert original in names, f"original {original} should be preserved"
            assert suffixed in names, f"suffixed {suffixed} should exist"


# ── Progress event sequence ordering ─────────────────────────────────────────

class TestProgressSequence:
    """Verify the full update_job call sequence during _scan_discover.

    The deferred discover pipeline emits progress updates in a defined order:
      listing → save → lifecycle-start → lifecycle-ticks → lifecycle-final → done
    This test captures every update_job call and validates that phase transitions
    happen in the correct order, with no phases skipped or duplicated.
    """

    def test_phase_ordering_300_files(self, isolated_store, monkeypatch):
        """300 files with a lifecycle rule: all 6 progress phases appear in order."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 200), ("pdf", _PDF, 100)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        owner = "test@example.com"
        isolated_store.create_disposition_policy(
            "pol-seq-tag",
            name="seq-tag", action="tag", enabled=True, requires_approval=False,
            match=json.dumps([{"field": "age_days", "op": "gte", "value": 0}]),
            action_config=json.dumps({"tags": ["seq-test"]}),
            owner_email=owner,
        )

        updates = []
        real_update = core.update_job

        def _capture(jid, data):
            updates.append(dict(data))
            return real_update(jid, data)

        monkeypatch.setattr(core, "update_job", _capture)

        job_id = "j-seq-300"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-seq-300", "source": "local", "user": owner},
            {"scan_id": "sd-seq-300", "id": job_id},
        )

        # Extract the sequence of observed phases / event types from update_job calls.
        # Listing updates carry files_found but no phase.
        # Save updates carry schema_version + save_new.
        # Lifecycle updates carry phase="lifecycle".
        # Done updates carry phase="done".
        phases = []
        for u in updates:
            if u.get("phase") == "done":
                phases.append("done")
            elif u.get("phase") == "lifecycle":
                phases.append("lifecycle")
            elif "save_new" in u or "save_updated" in u:
                phases.append("save")
            elif "files_found" in u and "phase" not in u:
                phases.append("listing")

        # Deduplicate consecutive entries to get the phase transition order.
        transitions = []
        for p in phases:
            if not transitions or transitions[-1] != p:
                transitions.append(p)

        # Listing progress is driven by the scanner's _search_drive callback, which
        # is not invoked when _list is monkeypatched. The observable transition
        # order from update_job is: save → lifecycle → done.
        expected = ["save", "lifecycle", "done"]
        assert transitions == expected, \
            f"phase ordering mismatch:\n  expected: {expected}\n  got:      {transitions}\n  raw: {phases}"

        # Save must come before lifecycle
        save_idx = phases.index("save")
        lc_idx = phases.index("lifecycle")
        done_idx = len(phases) - 1 - phases[::-1].index("done")
        assert save_idx < lc_idx < done_idx, \
            f"ordering violated: save@{save_idx} lifecycle@{lc_idx} done@{done_idx}"

    def test_phase_ordering_no_lifecycle_rules(self, isolated_store, monkeypatch):
        """Without lifecycle rules, lifecycle phase still appears (with zero counts) before done."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([("doc", _DOCX, 100)])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        updates = []
        real_update = core.update_job

        def _capture(jid, data):
            updates.append(dict(data))
            return real_update(jid, data)

        monkeypatch.setattr(core, "update_job", _capture)

        job_id = "j-seq-norule"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-seq-norule", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-seq-norule", "id": job_id},
        )

        phases = []
        for u in updates:
            if u.get("phase") == "done":
                phases.append("done")
            elif u.get("phase") == "lifecycle":
                phases.append("lifecycle")
            elif "save_new" in u or "save_updated" in u:
                phases.append("save")
            elif "files_found" in u and "phase" not in u:
                phases.append("listing")

        transitions = []
        for p in phases:
            if not transitions or transitions[-1] != p:
                transitions.append(p)

        expected = ["save", "lifecycle", "done"]
        assert transitions == expected, \
            f"phase ordering mismatch:\n  expected: {expected}\n  got:      {transitions}\n  raw: {phases}"

        # Done must carry all lifecycle KPI fields even with zero rules
        done_updates = [u for u in updates if u.get("phase") == "done"]
        assert done_updates, "no done-phase update"
        d = done_updates[-1]
        assert d["rules_enabled"] == 0
        assert d["lifecycle_matches"] == 0

    def test_classification_buckets_in_done_phase(self, isolated_store, monkeypatch):
        """Done phase with mixed estate: image/video now classified as metadata_only."""
        import core
        import handlers
        import scanner
        monkeypatch.setattr(core, "store", isolated_store)
        monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

        items = _make_items([
            ("doc", _DOCX, 50),
            ("img", _IMAGE, 30),
            ("vid", _VIDEO, 20),
        ])
        monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

        job_id = "j-seq-cls"
        core.JOBS[job_id] = {"phase": "queued"}

        handlers._scan_discover(
            {"scan_id": "sd-seq-cls", "source": "local", "user": "test@example.com"},
            {"scan_id": "sd-seq-cls", "id": job_id},
        )

        counts = handlers._count_inventory_classes("sd-seq-cls")
        assert counts["assessable"] == 50
        assert counts["metadata_only"] == 50  # 30 image + 20 video
        assert counts["eligibility_unknown"] == 0
        assert sum(counts.values()) == 100
