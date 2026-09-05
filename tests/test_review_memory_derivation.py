"""ADR 0021 §D — Review Memory nightly derivation job.

Test sections:
1. Unit tests for memory_derive.run_derivation() — store is a MagicMock that
   returns canned hitl events; no DB or cron needed.
2. Maturity threshold enforcement — pairs below each threshold are not proposed.
3. Idempotency — existing proposed/active rules are skipped.
4. Guidance text — _guidance() returns useful text for each editing pattern.
5. Evidence payload — shape and content of the JSON written to org_memory.
6. Sweeper wiring — run_sweep() calls run_derivation() after the interval elapses,
   not before.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import memory_derive as md


# ── helpers ──────────────────────────────────────────────────────────────────

def _event(rule_id="1.1.1", file="report.pdf", action="approve",
           edited=0, ai_value=None, final_value=None):
    return {
        "rule_id": rule_id,
        "file": file,
        "action": action,
        "edited": edited,
        "ai_value": ai_value,
        "final_value": final_value,
        "created_at": "2026-09-04T00:00:00Z",
    }


def _mature_events(n=12, rule_id="1.1.1", file="doc.pdf"):
    """n approval events with no edits — clears all three maturity thresholds."""
    return [_event(rule_id=rule_id, file=file, action="approve") for _ in range(n)]


def _mock_store(events_by_org: dict, existing_memory: list | None = None):
    store = MagicMock()
    orgs = list(events_by_org.keys())
    store.list_org_owners.return_value = orgs
    store.list_hitl_events_for_org.side_effect = lambda org, **kw: events_by_org.get(org, [])
    store.list_org_memory.return_value = existing_memory or []
    store.add_org_memory.return_value = "abc123"
    return store


# ══ 1. run_derivation basic behaviour ═══════════════════════════════════════

class TestRunDerivation:
    def test_returns_summary_dict_keys(self):
        store = _mock_store({})
        result = md.run_derivation(store)
        assert {"orgs_scanned", "pairs_proposed", "pairs_skipped"}.issubset(result)

    def test_no_orgs_returns_zeros(self):
        store = _mock_store({})
        result = md.run_derivation(store)
        assert result == {"orgs_scanned": 0, "pairs_proposed": 0, "pairs_skipped": 0}

    def test_org_with_no_events_not_counted(self):
        store = _mock_store({"alice@example.com": []})
        result = md.run_derivation(store)
        assert result["orgs_scanned"] == 0

    def test_mature_pair_is_proposed(self):
        org = "org@example.com"
        store = _mock_store({org: _mature_events()})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 1
        store.add_org_memory.assert_called_once()

    def test_proposed_row_has_correct_fields(self):
        org = "org@example.com"
        store = _mock_store({org: _mature_events(rule_id="1.1.1", file="a.pdf")})
        md.run_derivation(store)
        call = store.add_org_memory.call_args
        assert call.args[0] == org
        assert call.args[1] == "derived"
        assert isinstance(call.args[2], str) and len(call.args[2]) > 10
        assert call.kwargs["rule_id"] == "1.1.1"
        assert call.kwargs["format"] == "pdf"
        assert call.kwargs["status"] == "proposed"
        assert call.kwargs["author"] == "system:memory-derive"
        ev = json.loads(call.kwargs["evidence"])
        assert ev["rule"] == "1.1.1"
        assert ev["format"] == "pdf"

    def test_multiple_orgs_proposed_separately(self):
        events = _mature_events()
        store = _mock_store({
            "a@example.com": events,
            "b@example.com": events,
        })
        result = md.run_derivation(store)
        assert result["orgs_scanned"] == 2
        assert result["pairs_proposed"] == 2

    def test_multiple_rules_same_org(self):
        org = "org@example.com"
        events = (
            _mature_events(rule_id="1.1.1", file="doc.pdf")
            + _mature_events(rule_id="1.3.1", file="doc.pdf")
        )
        store = _mock_store({org: events})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 2

    def test_since_iso_passed_to_store(self):
        store = _mock_store({"org@example.com": []})
        md.run_derivation(store)
        call_kwargs = store.list_hitl_events_for_org.call_args.kwargs
        assert "since_iso" in call_kwargs
        assert call_kwargs["since_iso"].startswith("20")  # ISO 8601 date


# ══ 2. Maturity threshold enforcement ════════════════════════════════════════

class TestMaturityThresholds:
    def test_below_min_approvals_not_proposed(self):
        org = "org@example.com"
        # Only 5 approvals — below _MIN_APPROVALS=10
        store = _mock_store({org: _mature_events(n=5)})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 0

    def test_exactly_min_approvals_is_proposed(self):
        org = "org@example.com"
        store = _mock_store({org: _mature_events(n=md._MIN_APPROVALS)})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 1

    def test_high_edit_rate_not_proposed(self):
        org = "org@example.com"
        # 10 approvals, 3 edited = 30% edit rate > 20%
        events = [
            _event(action="approve", edited=1, ai_value="x", final_value="xy")
            if i < 3 else _event(action="approve")
            for i in range(10)
        ]
        store = _mock_store({org: events})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 0

    def test_high_rejection_rate_not_proposed(self):
        org = "org@example.com"
        # 8 approvals + 3 rejections = 72.7% approval rate < 90%
        events = _mature_events(n=8) + [_event(action="reject") for _ in range(3)]
        store = _mock_store({org: events})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 0

    def test_approvals_and_rejections_counted_correctly(self):
        org = "org@example.com"
        # 10 approvals, 0 rejections — should pass
        events = _mature_events(n=10)
        store = _mock_store({org: events})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 1

    def test_skip_events_not_counted_in_decided(self):
        org = "org@example.com"
        # 10 approvals + 20 skips — skips don't count toward decided or rejection rate
        events = _mature_events(n=10) + [_event(action="skip") for _ in range(20)]
        store = _mock_store({org: events})
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 1


# ══ 3. Idempotency ═══════════════════════════════════════════════════════════

class TestIdempotency:
    def test_existing_proposed_rule_is_skipped(self):
        org = "org@example.com"
        existing = [{"rule_id": "1.1.1", "format": "pdf", "status": "proposed"}]
        store = _mock_store({org: _mature_events(rule_id="1.1.1", file="doc.pdf")},
                            existing_memory=existing)
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 0
        assert result["pairs_skipped"] == 1
        store.add_org_memory.assert_not_called()

    def test_existing_active_rule_is_skipped(self):
        org = "org@example.com"
        existing = [{"rule_id": "1.1.1", "format": "pdf", "status": "active"}]
        store = _mock_store({org: _mature_events(rule_id="1.1.1", file="doc.pdf")},
                            existing_memory=existing)
        result = md.run_derivation(store)
        assert result["pairs_skipped"] == 1

    def test_archived_rule_is_not_blocking(self):
        org = "org@example.com"
        # An archived rule was dismissed — allow re-proposing a new candidate
        existing = [{"rule_id": "1.1.1", "format": "pdf", "status": "archived"}]
        store = _mock_store({org: _mature_events(rule_id="1.1.1", file="doc.pdf")},
                            existing_memory=existing)
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 1

    def test_different_format_not_blocked_by_existing(self):
        org = "org@example.com"
        # Existing rule is for docx — pdf pair should still be proposed
        existing = [{"rule_id": "1.1.1", "format": "docx", "status": "active"}]
        store = _mock_store({org: _mature_events(rule_id="1.1.1", file="doc.pdf")},
                            existing_memory=existing)
        result = md.run_derivation(store)
        assert result["pairs_proposed"] == 1


# ══ 4. Guidance text ═════════════════════════════════════════════════════════

class TestGuidanceText:
    def test_zero_edits_mentions_accepted_verbatim(self):
        ev = {"rule": "1.1.1", "format": "pdf", "edited": 0, "of": 12, "median_delta_chars": 0}
        g = md._guidance("1.1.1", "pdf", ev)
        assert "without edits" in g.lower() or "verbatim" in g.lower()

    def test_negative_delta_mentions_shorter(self):
        ev = {"rule": "1.1.1", "format": "pdf", "edited": 1, "of": 12, "median_delta_chars": -45}
        g = md._guidance("1.1.1", "pdf", ev)
        assert "concise" in g.lower() or "shorten" in g.lower() or "shorter" in g.lower()

    def test_positive_delta_mentions_detail(self):
        ev = {"rule": "1.1.1", "format": "pdf", "edited": 1, "of": 12, "median_delta_chars": 55}
        g = md._guidance("1.1.1", "pdf", ev)
        assert "detail" in g.lower() or "descriptive" in g.lower()

    def test_small_delta_mentions_minor(self):
        ev = {"rule": "1.1.1", "format": None, "edited": 1, "of": 12, "median_delta_chars": 5}
        g = md._guidance("1.1.1", None, ev)
        assert g  # non-empty
        assert "minor" in g.lower() or "small" in g.lower() or "close" in g.lower()

    def test_guidance_contains_rule_id(self):
        ev = {"rule": "2.4.6", "format": "docx", "edited": 0, "of": 15, "median_delta_chars": 0}
        g = md._guidance("2.4.6", "docx", ev)
        assert "2.4.6" in g

    def test_none_format_does_not_crash(self):
        ev = {"rule": "1.3.1", "format": None, "edited": 0, "of": 10, "median_delta_chars": 0}
        g = md._guidance("1.3.1", None, ev)
        assert isinstance(g, str) and g


# ══ 5. Evidence payload ══════════════════════════════════════════════════════

class TestEvidencePayload:
    def test_evidence_json_fields(self):
        org = "org@example.com"
        # 2 edits that shortened by 30 chars each
        events = [
            _event(action="approve", edited=1, ai_value="x" * 50, final_value="x" * 20)
            if i < 2
            else _event(action="approve")
            for i in range(12)
        ]
        store = _mock_store({org: events})
        md.run_derivation(store)
        ev = json.loads(store.add_org_memory.call_args.kwargs["evidence"])
        assert ev["rule"] == "1.1.1"
        assert ev["format"] == "pdf"
        assert ev["of"] == 12
        assert ev["edited"] == 2
        assert ev["window_days"] == md._WINDOW_DAYS
        assert isinstance(ev["median_delta_chars"], int)

    def test_median_delta_negative_when_shortened(self):
        org = "org@example.com"
        events = [
            _event(action="approve", edited=1, ai_value="x" * 100, final_value="x" * 50)
            if i < 1
            else _event(action="approve")
            for i in range(12)
        ]
        store = _mock_store({org: events})
        md.run_derivation(store)
        ev = json.loads(store.add_org_memory.call_args.kwargs["evidence"])
        assert ev["median_delta_chars"] < 0

    def test_no_edits_median_delta_is_zero(self):
        org = "org@example.com"
        store = _mock_store({org: _mature_events(n=12)})
        md.run_derivation(store)
        ev = json.loads(store.add_org_memory.call_args.kwargs["evidence"])
        assert ev["median_delta_chars"] == 0
        assert ev["edited"] == 0


# ══ 6. Sweeper wiring ════════════════════════════════════════════════════════

class TestSweeperWiring:
    def test_derivation_runs_after_interval(self):
        import sweeper
        import memory_derive as _md

        sweeper._last_derive_run = 0.0
        store = MagicMock()
        store.reclaim_stuck_jobs.return_value = 0
        store.sweep_exhausted_jobs.return_value = 0
        store.sweep_orphaned_scans.return_value = 0
        store.rescue_unfinalized_scans.return_value = 0

        with patch.object(_md, "run_derivation", return_value={"pairs_proposed": 2,
                                                                "pairs_skipped": 0,
                                                                "orgs_scanned": 1}) as mock_derive:
            result = sweeper.run_sweep(store, derive_interval_seconds=0)
        mock_derive.assert_called_once_with(store)
        assert result["memory_proposed"] == 2

    def test_derivation_not_run_before_interval(self):
        import sweeper
        import memory_derive as _md

        sweeper._last_derive_run = time.monotonic()  # just ran
        store = MagicMock()
        store.reclaim_stuck_jobs.return_value = 0
        store.sweep_exhausted_jobs.return_value = 0
        store.sweep_orphaned_scans.return_value = 0
        store.rescue_unfinalized_scans.return_value = 0

        with patch.object(_md, "run_derivation") as mock_derive:
            result = sweeper.run_sweep(store, derive_interval_seconds=3600)
        mock_derive.assert_not_called()
        assert result["memory_proposed"] == 0

    def test_derivation_error_does_not_crash_sweep(self):
        import sweeper
        import memory_derive as _md

        sweeper._last_derive_run = 0.0
        store = MagicMock()
        store.reclaim_stuck_jobs.return_value = 0
        store.sweep_exhausted_jobs.return_value = 0
        store.sweep_orphaned_scans.return_value = 0
        store.rescue_unfinalized_scans.return_value = 0

        with patch.object(_md, "run_derivation", side_effect=RuntimeError("db down")):
            result = sweeper.run_sweep(store, derive_interval_seconds=0)
        assert result["memory_proposed"] == 0

    def test_memory_proposed_key_always_present(self):
        import sweeper

        sweeper._last_derive_run = time.monotonic()
        store = MagicMock()
        store.reclaim_stuck_jobs.return_value = 0
        store.sweep_exhausted_jobs.return_value = 0
        store.sweep_orphaned_scans.return_value = 0
        store.rescue_unfinalized_scans.return_value = 0

        result = sweeper.run_sweep(store, derive_interval_seconds=9999)
        assert "memory_proposed" in result
