"""The decision layer of archive auto-fire (R9), and mostly the cases that must NOT fire.

WHAT THESE ASSERT, and why they are worth more than a happy path: every acceptance criterion in
the PRD that can be expressed without a tenant is here, and the ones that matter are refusals.
A test that a superseded document is eligible would pass against an implementation that made
everything eligible; a test that an OLD document is not is the one that fails when the safety
property breaks.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import archive_autofire as af  # noqa: E402
import archive_evidence  # noqa: E402

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _policy(**over):
    base = {"enabled": True, "dry_run": False, "archive_root": "Archive",
            "source_connections": ["sharepoint:d1"], "rule_ids": ["r1"],
            "required_evidence": [af.METADATA_LINK], "min_replacement_age_days": 30,
            "max_actions_per_run": 25, "max_actions_per_day": 100}
    base.update(over)
    return af.normalize_policy(base)


def _candidate(**over):
    base = {"source": "sharepoint", "source_connection": "sharepoint:d1",
            "path": "Policies/2024/Clinical-Access-v2.docx", "drive_file_id": "item-old",
            "drive_id": "d1", "lifecycle_rule_id": "r1", "source_modified": "2024-01-01T00:00:00Z"}
    base.update(over)
    return base


def _evidence(**over):
    base = {"type": af.METADATA_LINK, "source_item_id": "item-old",
            "replacement_item_id": "item-new",
            "replacement_path": "Policies/2025/Clinical-Access-v3.docx",
            "replacement_modified": "2025-01-01T00:00:00Z",
            "source_modified": "2024-01-01T00:00:00Z"}
    base.update(over)
    return base


# ── The core safety principle ────────────────────────────────────────────────

def test_age_alone_never_reaches_the_automatic_lane():
    """THE acceptance criterion. A candidate an age rule selected, with no evidence of any
    replacement, is a recommendation — under a policy that is enabled, funded and permissive."""
    decision = af.decide(_candidate(), policy=_policy(), evidence=[], now=NOW)
    assert decision["state"] == af.RECOMMEND_ONLY
    assert "Age, filename similarity and inactivity never authorize" in decision["reason"]


def test_filename_similarity_is_not_evidence():
    """Two documents whose names differ only by a version suffix produce nothing.

    Asserted through the derivation layer rather than by inspecting a name comparison, because
    the property is "no code path treats names as a link", not "one particular function does not".
    """
    old = _candidate()
    new = {"drive_file_id": "item-new", "drive_id": "d1",
           "path": "Policies/2025/Clinical-Access-v3.docx",
           "file": "Clinical-Access-v3.docx", "source_modified": "2025-01-01T00:00:00Z"}
    assert archive_evidence.derive(old, [new], policy=_policy()) == []


def test_evidence_without_a_stable_identifier_is_refused():
    for missing in ("source_item_id", "replacement_item_id"):
        record = _evidence(**{missing: ""})
        assert "stable identifier" in af.evidence_problem(record)


def test_a_document_family_keyed_on_a_filename_is_refused_by_name():
    cfg = archive_evidence.family_config({"auto_archive": {"family_field": "file"}})
    assert "cannot be keyed on a filename" in cfg["problem"]
    assert cfg["family_field"] == ""


def test_family_evidence_needs_a_strictly_newer_version():
    """The one evidence type that is ACP's own grouping carries the extra ordering burden."""
    assert af.evidence_problem(_evidence(type=af.RULE_FAMILY, family="Clinical Access",
                                         source_version="3.0", replacement_version="2.0"))
    assert not af.evidence_problem(_evidence(type=af.RULE_FAMILY, family="Clinical Access",
                                             source_version="2.0", replacement_version="3.0"))


def test_unorderable_versions_are_not_newer():
    """'Draft' vs '2.0' is unordered, and unordered must not round to newer."""
    assert af._strictly_newer("Draft", "2.0") is False
    assert af._strictly_newer("2.0", "Draft") is False
    assert af._strictly_newer("2.10", "2.9") is True


def test_sharepoint_version_evidence_requires_an_approved_replacement():
    assert "approved" in af.evidence_problem(_evidence(type=af.SP_VERSION,
                                                       replacement_approved=False))
    assert not af.evidence_problem(_evidence(type=af.SP_VERSION, replacement_approved=True))


def test_admin_mapping_must_name_who_confirmed_it():
    assert "who confirmed" in af.evidence_problem(_evidence(type=af.ADMIN_MAPPING,
                                                            confirmed_by=""))


# ── Sources ──────────────────────────────────────────────────────────────────

def test_only_sharepoint_and_onedrive_may_auto_fire():
    assert af.source_problem("sharepoint") == ""
    assert af.source_problem("onedrive") == ""
    assert "legal hold" in af.source_problem("drive")
    assert "recommendation-only" in af.source_problem("local")


def test_a_drive_candidate_with_perfect_evidence_stays_a_recommendation():
    decision = af.decide(_candidate(source="drive"), policy=_policy(), evidence=[_evidence()],
                         now=NOW)
    assert decision["state"] == af.RECOMMEND_ONLY


# ── Policy ───────────────────────────────────────────────────────────────────

def test_the_shipped_default_is_recommendation_only():
    policy = af.normalize_policy({})
    assert policy["enabled"] is False and policy["dry_run"] is True
    assert af.decide(_candidate(), policy=policy, evidence=[_evidence()],
                     now=NOW)["state"] == af.RECOMMEND_ONLY


def test_garbage_in_a_policy_falls_back_to_the_safe_value_not_the_permissive_one():
    policy = af.normalize_policy({"enabled": "yes please", "max_actions_per_day": "lots",
                                  "required_evidence": ["not-a-type"]})
    assert policy["enabled"] is True          # an explicit truthy value is honoured
    assert policy["max_actions_per_day"] == af.POLICY_DEFAULTS["max_actions_per_day"]
    assert policy["required_evidence"] == af.POLICY_DEFAULTS["required_evidence"]


def test_enabling_a_policy_with_nowhere_to_move_files_is_refused():
    assert "archive destination" in af.policy_problem(_policy(archive_root=""))
    assert af.policy_problem(af.normalize_policy({"enabled": False})) == ""


def test_a_run_ceiling_above_the_day_ceiling_is_refused():
    assert "cannot exceed" in af.policy_problem(_policy(max_actions_per_run=200,
                                                        max_actions_per_day=10))


def test_the_snapshot_id_is_the_policy_content_and_excludes_the_kill_switch():
    """Content-addressed, so an unchanged policy keeps its id — and the kill switch is NOT in it,
    because a snapshot carrying a stale 'not killed' would outlive the operator's decision."""
    a = af.policy_snapshot(_policy())
    b = af.policy_snapshot(_policy(kill_switch=True))
    assert a["snapshot_id"] == b["snapshot_id"]
    assert af.policy_snapshot(_policy(archive_root="Other"))["snapshot_id"] != a["snapshot_id"]


def test_the_idempotency_key_covers_every_input_the_prd_names():
    args = dict(tenant="t", source_connection="sharepoint:d1", source_item_id="i",
                destination="Archive/x.docx", snapshot_id="s")
    base = af.idempotency_key(**args)
    for field in args:
        assert af.idempotency_key(**{**args, field: "different"}) != base


# ── Decision lanes ───────────────────────────────────────────────────────────

def test_evidence_plus_policy_plus_budget_is_the_only_route_to_eligible():
    decision = af.decide(_candidate(), policy=_policy(), evidence=[_evidence()], now=NOW)
    assert decision["state"] == af.ELIGIBLE_AUTO
    assert decision["destination"] == "Archive/Policies/2024/Clinical-Access-v2.docx"


def test_the_kill_switch_blocks_a_candidate_that_would_otherwise_be_eligible():
    decision = af.decide(_candidate(), policy=_policy(kill_switch=True), evidence=[_evidence()],
                         now=NOW)
    assert decision["state"] == af.BLOCKED and "kill switch" in decision["reason"]


def test_a_replacement_younger_than_the_minimum_age_blocks():
    fresh = _evidence(replacement_modified=(NOW - timedelta(days=2)).isoformat())
    decision = af.decide(_candidate(), policy=_policy(), evidence=[fresh], now=NOW)
    assert decision["state"] == af.BLOCKED and "requires 30 days" in decision["reason"]


def test_an_unreadable_replacement_time_blocks_rather_than_counting_as_old_enough():
    decision = af.decide(_candidate(), policy=_policy(),
                         evidence=[_evidence(replacement_modified="whenever")], now=NOW)
    # The record is refused before the age question is even asked — an evidence record that
    # cannot say when the replacement changed is not evidence.
    assert decision["state"] == af.RECOMMEND_ONLY


def test_an_unauthorized_connection_or_rule_blocks():
    assert af.decide(_candidate(source_connection="sharepoint:other"), policy=_policy(),
                     evidence=[_evidence()], now=NOW)["state"] == af.BLOCKED
    assert af.decide(_candidate(lifecycle_rule_id="r9"), policy=_policy(),
                     evidence=[_evidence()], now=NOW)["state"] == af.BLOCKED


def test_evidence_of_a_type_the_policy_does_not_require_is_rejected_and_explained():
    decision = af.decide(_candidate(), policy=_policy(required_evidence=[af.ADMIN_MAPPING]),
                         evidence=[_evidence()], now=NOW)
    assert decision["state"] == af.RECOMMEND_ONLY
    assert decision["rejected_evidence"]


def test_the_ceilings_block_rather_than_silently_dropping_items():
    at_run = af.decide(_candidate(), policy=_policy(), evidence=[_evidence()], now=NOW,
                       run_used=25)
    assert at_run["state"] == af.BLOCKED and "ceiling of 25" in at_run["reason"]
    at_day = af.decide(_candidate(), policy=_policy(), evidence=[_evidence()], now=NOW,
                       day_used=100)
    assert at_day["state"] == af.BLOCKED and "Today has reached" in at_day["reason"]


def test_an_existing_execution_wins_over_a_fresh_decision():
    decision = af.decide(_candidate(), policy=_policy(), evidence=[_evidence()], now=NOW,
                         executed={"state": af.ARCHIVED, "detail": "already moved"})
    assert decision["state"] == af.ARCHIVED


# ── Destination ──────────────────────────────────────────────────────────────

def test_hierarchy_is_preserved_beneath_the_archive_root():
    assert af.destination_path("Archive", "Policies/2024/x.docx") == "Archive/Policies/2024/x.docx"


def test_flattening_is_opt_in():
    assert af.destination_path("Archive", "Policies/2024/x.docx",
                               preserve_hierarchy=False) == "Archive/x.docx"


def test_a_traversal_in_either_half_yields_no_destination():
    assert af.destination_path("Archive/../..", "a/x.docx") == ""
    assert af.destination_path("Archive", "../../x.docx") == ""


# ── Preflight ────────────────────────────────────────────────────────────────

def _live(**over):
    base = {"source_exists": True, "source_item_id": "item-old", "source_marker": "2024-01-01T00:00:00Z",
            "replacement_exists": True, "replacement_modified": "2025-01-01T00:00:00Z",
            "replacement_audience_ok": True,
            "hold": {"checked": True, "blockers": []},
            "destination_reachable": True, "destination_collision": False}
    base.update(over)
    return base


SNAP = {"source_item_id": "item-old", "source_marker": "2024-01-01T00:00:00Z",
        "source_modified": "2024-01-01T00:00:00Z"}


def test_a_clean_preflight_proceeds():
    result = af.preflight(snapshot=SNAP, live=_live(), policy=_policy())
    assert result["ok"] and result["route"] == "proceed"


def test_an_unreadable_hold_fails_closed_to_review():
    """SharePoint legal-hold or retention UNCERTAINTY fails closed — the acceptance criterion, and
    the one that separates 'we did not look' from 'we looked and it was fine'."""
    result = af.preflight(snapshot=SNAP, live=_live(hold={"checked": False, "blockers": []}),
                          policy=_policy())
    assert not result["ok"] and result["route"] == "review"
    assert "no_hold" in result["unknown"]


def test_a_declared_record_blocks():
    held = {"checked": True, "blockers": [{"code": "declared_record",
                                           "message": "declared as a record"}]}
    result = af.preflight(snapshot=SNAP, live=_live(hold=held), policy=_policy())
    assert result["route"] == "review" and "no_hold" in result["failed"]


def test_a_source_changed_since_evaluation_cancels_rather_than_asking_a_person():
    result = af.preflight(snapshot=SNAP, live=_live(source_marker="2026-08-01T00:00:00Z"),
                          policy=_policy())
    assert result["route"] == "cancel"


def test_a_missing_replacement_cancels_the_automatic_action():
    result = af.preflight(snapshot=SNAP, live=_live(replacement_exists=False), policy=_policy())
    assert result["route"] == "cancel"


def test_a_destination_collision_routes_to_review_and_never_proceeds():
    result = af.preflight(snapshot=SNAP, live=_live(destination_collision=True), policy=_policy())
    assert result["route"] == "review" and "destination_free" in result["failed"]


def test_every_unknown_routes_to_review_and_none_of_them_proceed():
    """Swept rather than spot-checked: the property is that NO unknown proceeds, and a per-field
    test would pass while a newly added field defaulted to permissive."""
    for field in ("source_exists", "replacement_exists", "replacement_audience_ok",
                  "destination_reachable", "destination_collision"):
        result = af.preflight(snapshot=SNAP, live=_live(**{field: None}), policy=_policy())
        assert not result["ok"], f"{field}=None proceeded"


def test_an_already_executed_action_never_proceeds():
    result = af.preflight(snapshot=SNAP, live=_live(), policy=_policy(), already_executed=True)
    assert not result["ok"] and "not_already_executed" in result["failed"]


# ── Outcome ──────────────────────────────────────────────────────────────────

def test_only_a_verified_move_is_archived():
    state, _ = af.classify_outcome({"verified": True, "destination_item_id": "new",
                                    "destination_path": "Archive/x.docx"})
    assert state == af.ARCHIVED


def test_an_unverified_or_ambiguous_move_is_never_completed():
    assert af.classify_outcome({"verified": False})[0] == af.RECOVERY_REQUIRED
    assert af.classify_outcome({"verified": None})[0] == af.RECOVERY_REQUIRED
    assert af.classify_outcome(None)[0] == af.RECOVERY_REQUIRED


def test_a_verified_flag_without_a_destination_id_is_not_completed():
    """`verified: True` with nothing at the destination is a contradiction, and the safe reading
    of a contradiction is the one that asks a person."""
    assert af.classify_outcome({"verified": True})[0] == af.RECOVERY_REQUIRED


def test_only_rate_limiting_is_retryable():
    retryable = [k for k, (_, route) in af.FAILURE_ROUTES.items() if route == "retry"]
    assert retryable == ["rate_limited"]


def test_backoff_is_bounded_in_both_directions():
    assert af.backoff_seconds(1) == 2.0
    assert af.backoff_seconds(50) == 60.0


# ── Events ───────────────────────────────────────────────────────────────────

def test_an_event_carries_no_key_outside_the_allow_list():
    payload = af.event_payload({"source_path": "a/b.docx", "token": "secret",
                                "document_text": "patient name", "completed": 3})
    assert payload == {"source_path": "a/b.docx", "completed": 3}


def test_a_credential_inside_an_allowed_key_is_withheld_rather_than_stored():
    payload = af.event_payload({"detail": "GET https://x/y?sv=2024&sig=abcd failed"})
    assert "sig=" not in payload["detail"] and "withheld" in payload["detail"]


def test_run_progress_states_measured_counts_only():
    assert af.run_progress({"eligible": 12, "completed": 4, "blocked": 1}) == (
        "12 eligible · 4 completed · 1 blocked · 7 remaining")
