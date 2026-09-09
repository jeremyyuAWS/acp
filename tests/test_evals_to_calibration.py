"""The evals → calibration bridge, tested by what it REFUSES.

A converter that emits records is easy; one that emits only records it can defend is the job.
So most of this module is bite checks: a row that should be dropped is put back and the count
has to move, a corpus that should be refused is offered and the refusal has to happen. If any
of these stops biting, the bridge has started manufacturing evidence, which is worse than
producing none.

The end-to-end tests run against the CHECKED-IN reports, through the contract's own
`normalize_evaluation`, because a record that only passes a local re-implementation of the
rules is a record nobody can ingest.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.calibration import (BridgeError, build_evaluations, canonical_bytes,  # noqa: E402
                               case_ids_covered, dataset_manifest, parse_candidate,
                               parse_category, refuse_repo_corpus_as_evaluated, shortfall_table,
                               usable_rows, validator_version)

from ai_review_calibration import normalize_evaluation, wilson_lower  # noqa: E402

SHA = "a" * 64
BUILD = dict(report_sha256=SHA, dataset_sha256="b" * 64,
             evaluated_at="2026-09-07T00:00:00Z", validator="evals-graders.0123456789ab",
             version_prefix="fixture")


def row(**over):
    base = dict(candidate="anthropic:claude-sonnet-5", repeat=0, case_id="rem-a00",
                category="docx:1.1.1", suite="execution", risk_tier="medium",
                eligible=True, must_abstain=False, verified_fix=True, autonomous_action=True,
                escalated=False, abstention_correct=True, critical_violations=[],
                violations=[], usd=0.0, cached=False, parse_error="")
    base.update(over)
    return base


def report(rows, candidates=None):
    return {"results": list(rows),
            "candidates": candidates or [{"candidate": "anthropic:claude-sonnet-5",
                                          "nondeterministic": True}]}


# ── the happy path, validated by the contract and not by a copy of it ────────────────────────

def test_record_passes_the_contracts_own_validator():
    out = build_evaluations(report([row(case_id=f"c{i}", repeat=i % 3) for i in range(6)]), **BUILD)
    assert len(out["records"]) == 1
    record = normalize_evaluation(out["records"][0])
    assert record["sample_size"] == 6 and record["successes"] == 6
    assert record["reliability_lower_bound"] == wilson_lower(6, 6)
    assert record["config_id"]


def test_cohort_identity_is_format_criterion_provider_model():
    out = build_evaluations(report([row(), row(case_id="c1", category="pdf:2.4.4"),
                                    row(case_id="c2", candidate="openai:gpt-x")]), **BUILD)
    assert {(r["format"], r["change_family"], r["generator_provider"], r["generator_model"])
            for r in out["records"]} == {("docx", "1.1.1", "anthropic", "claude-sonnet-5"),
                                         ("pdf", "2.4.4", "anthropic", "claude-sonnet-5"),
                                         ("docx", "1.1.1", "openai", "gpt-x")}


def test_every_sample_is_an_objective_validator_judgment():
    # The kit has no human labeller. A sample claiming `independent_human` here would be the
    # bridge inventing an authority it does not have.
    out = build_evaluations(report([row(case_id=f"c{i}") for i in range(3)]), **BUILD)
    assert {s["judgment_origin"] for s in out["records"][0]["samples"]} == {"objective_validator"}


def test_the_absent_reviewer_is_named_not_omitted():
    out = build_evaluations(report([row()]), **BUILD)
    record = out["records"][0]
    assert record["reviewer_provider"] == "none" and record["reviewer_model"] == "none"
    # And that is load-bearing: config_id hashes it, so this cohort cannot be matched to a
    # production configuration that runs a reviewer.
    from ai_review_calibration import config_id
    reviewed = dict(record, reviewer_provider="anthropic", reviewer_model="claude-opus-5")
    assert config_id(record) != config_id(reviewed)


# ── the exclusions, each with a bite ─────────────────────────────────────────────────────────

def test_cached_rows_are_dropped_and_putting_one_back_moves_the_count():
    rows = [row(case_id="c0"), row(case_id="c1", cached=True)]
    assert len(build_evaluations(report(rows), **BUILD)["records"][0]["samples"]) == 1
    rows[1]["cached"] = False
    assert len(build_evaluations(report(rows), **BUILD)["records"][0]["samples"]) == 2


def test_ineligible_and_must_abstain_rows_are_dropped_and_censused():
    rows = [row(case_id="c0"), row(case_id="c1", eligible=False),
            row(case_id="c2", must_abstain=True), row(case_id="c3", cached=True)]
    out = build_evaluations(report(rows), **BUILD)
    assert out["census"]["dropped"] == {"not_eligible": 1, "must_abstain": 1, "cached": 1,
                                        "unroutable": 0}
    assert out["census"]["samples_out"] == 1


def test_rules_only_produces_no_cohort():
    # A deterministic rule-code baseline has no generator provider or model. A record keyed on
    # one would describe a configuration that never dispatches a model.
    out = build_evaluations(report([row(candidate="rules-only")],
                                   candidates=[{"candidate": "rules-only",
                                                "nondeterministic": False}]), **BUILD)
    assert out["records"] == [] and out["census"]["dropped"]["unroutable"] == 1


def test_deterministic_candidate_repeats_collapse_to_one_draw():
    rows = [row(candidate="stub:good", repeat=i) for i in range(3)]
    cands = [{"candidate": "stub:good", "nondeterministic": False}]
    out = build_evaluations(report(rows, cands), **BUILD)
    assert len(out["records"][0]["samples"]) == 1
    assert out["census"]["deterministic_repeats_collapsed"] == 2
    # Bite: the same rows from a NONDETERMINISTIC candidate keep all three.
    cands[0]["nondeterministic"] = True
    assert len(build_evaluations(report(rows, cands), **BUILD)["records"][0]["samples"]) == 3


def test_unroutable_categories_never_become_a_cohort():
    # `report.category_of` writes these placeholders when it cannot derive a half. A record
    # keyed on "?" or "n/a" would pool unrelated work under one config_id.
    assert parse_category("?:1.1.1") is None and parse_category("docx:n/a") is None
    assert parse_category("docx:1.1.1") == ("docx", "1.1.1")
    assert parse_candidate("rules-only") is None and parse_candidate("anthropic:") is None
    assert parse_candidate("hosted:small@https://h/v1#nano") == ("hosted", "small@https://h/v1#nano")


@pytest.mark.parametrize("over,expected", [
    ({}, True),
    ({"verified_fix": False}, False),
    ({"critical_violations": ["delete_content"]}, False),
    ({"verified_fix": True, "critical_violations": ["mark_pass"]}, False),
    ({"parse_error": "JSONDecodeError", "verified_fix": False}, False),
])
def test_passed_is_verified_fix_with_no_critical_violation(over, expected):
    out = build_evaluations(report([row(**over)]), **BUILD)
    assert out["records"][0]["samples"][0]["passed"] is expected


def test_duplicate_case_run_identity_is_refused_not_deduplicated():
    # Two rows for one (case, repeat) means the report is wrong. Silently keeping one would
    # pick a verdict at random; silently keeping both would fail normalize_evaluation later,
    # at the operator's ingest rather than here.
    with pytest.raises(BridgeError, match="duplicate sample identity"):
        build_evaluations(report([row(), row()]), **BUILD)


def test_a_report_without_result_rows_is_refused():
    # The four 2026-09-04 reports predate case_run_row and carry aggregates only. Converting
    # aggregates would mean inventing per-sample evidence refs.
    with pytest.raises(BridgeError, match="no per-case-run"):
        build_evaluations({"results": [], "candidates": []}, **BUILD)


# ── provenance the script must not invent ────────────────────────────────────────────────────

def test_records_are_synthetic_and_not_representative_by_default():
    record = build_evaluations(report([row()]), **BUILD)["records"][0]
    assert record["provenance"]["kind"] == "synthetic"
    assert record["provenance"]["representative"] is False


def test_evaluated_kind_is_refused_for_the_repos_own_generated_corpus():
    with pytest.raises(BridgeError, match="gen_remediation_eval_corpus"):
        refuse_repo_corpus_as_evaluated(ROOT / "evals" / "cases", "evaluated")
    # …and permitted elsewhere, so the guard is about THIS corpus and not about the flag.
    refuse_repo_corpus_as_evaluated(ROOT / "evals" / "cases", "synthetic")
    refuse_repo_corpus_as_evaluated(ROOT / "test-corpus", "evaluated")


def test_synthetic_provenance_is_refused_as_production_qualification(tmp_path):
    # The end of the road for every record this bridge builds from evals/cases, asserted
    # against the real gate rather than described in a comment.
    from ai_review_calibration import applicable_evaluation
    record = normalize_evaluation(build_evaluations(report([row()]), **BUILD)["records"][0])
    class _Store:
        def get_setting(self, key):
            return json.dumps(record)
    got = applicable_evaluation(_Store(), "owner", record["evaluation_version"], record,
                                {"minimum_sample_size": 1, "freshness_days": 3650})
    assert got == {"available": False, "reason": "synthetic_calibration_not_eligible",
                   "evaluation": None}


# ── the dataset artifact ─────────────────────────────────────────────────────────────────────

def test_dataset_manifest_is_deterministic_and_notices_a_changed_corpus(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([{"case_id": "x"}]))
    first = canonical_bytes(dataset_manifest(tmp_path))
    assert first == canonical_bytes(dataset_manifest(tmp_path))
    (tmp_path / "a.json").write_text(json.dumps([{"case_id": "y"}]))
    assert canonical_bytes(dataset_manifest(tmp_path)) != first


def test_manifest_covers_the_real_corpus():
    manifest = dataset_manifest(ROOT / "evals" / "cases")
    assert manifest["cases"] == len(manifest["case_ids"]) > 0
    assert len(manifest["files"]) == len(sorted((ROOT / "evals" / "cases").glob("*.json")))


def test_a_report_graded_on_another_corpus_is_detectable():
    manifest = dataset_manifest(ROOT / "evals" / "cases")
    assert case_ids_covered({"results": [{"case_id": manifest["case_ids"][0]}]}, manifest) == []
    assert case_ids_covered({"results": [{"case_id": "not-a-real-case"}]}, manifest) == \
        ["not-a-real-case"]


def test_validator_version_moves_when_the_graders_do(tmp_path):
    src = tmp_path / "evals"
    src.mkdir()
    for name in ("graders.py", "world.py", "schema.py"):
        (src / name).write_bytes(b"x")
    first = validator_version(tmp_path)
    assert first.startswith("evals-graders.") and len(first) == len("evals-graders.") + 12
    (src / "graders.py").write_bytes(b"y")
    assert validator_version(tmp_path) != first


# ── against the checked-in reports ───────────────────────────────────────────────────────────

REPORTS = sorted(p for p in (ROOT / "evals" / "reports").glob("*.json")
                 if json.loads(p.read_text()).get("results"))


@pytest.mark.parametrize("path", REPORTS, ids=lambda p: p.stem)
def test_every_record_from_every_checked_in_report_validates(path):
    payload = json.loads(path.read_text())
    manifest = dataset_manifest(ROOT / "evals" / "cases")
    assert case_ids_covered(payload, manifest) == []
    out = build_evaluations(payload, report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            dataset_sha256=hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
                            evaluated_at="2026-09-07T00:00:00Z",
                            validator="evals-graders.0123456789ab", version_prefix=path.stem)
    assert out["records"]
    for record in out["records"]:
        normalize_evaluation(record)


def test_no_checked_in_report_reaches_the_evidence_policy():
    """The finding, guarded so it cannot quietly stop being true.

    `remediation_impact_estimates.MINIMUM_SAMPLES` is 30 and the largest cohort any checked-in
    report can produce is 9 — every record the bridge builds today is valid, immutable, and
    authorises nothing. If a bigger run lands this goes red, which is the prompt to update
    docs/ai-review-calibration.md rather than a regression.
    """
    from remediation_impact_estimates import MINIMUM_SAMPLES
    manifest = dataset_manifest(ROOT / "evals" / "cases")
    largest = 0
    for path in REPORTS:
        out = build_evaluations(json.loads(path.read_text()), report_sha256=SHA,
                                dataset_sha256=hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
                                evaluated_at="2026-09-07T00:00:00Z",
                                validator="evals-graders.0123456789ab", version_prefix=path.stem)
        assert out["census"]["cohorts_meeting_minimum"] == 0
        largest = max(largest, out["census"]["largest_cohort"])
    assert 0 < largest < MINIMUM_SAMPLES
    assert largest == 9


def test_shortfall_names_the_repeats_that_would_close_the_gap():
    rows = [row(case_id=f"c{c}", repeat=r) for c in range(3) for r in range(3)]
    table = shortfall_table(build_evaluations(report(rows), **BUILD), minimum_samples=30)
    assert table[0]["samples"] == 9 and table[0]["cases"] == 3 and table[0]["repeats"] == 3
    assert table[0]["short_by"] == 21
    # 3 cases × 10 repeats = 30. The corpus fixes cases per repeat, so repeats is the lever.
    assert table[0]["repeats_required"] == 10


def test_usable_rows_census_accounts_for_every_row():
    rows = [row(case_id="c0"), row(case_id="c1", eligible=False), row(case_id="c2", cached=True),
            row(case_id="c3", candidate="rules-only"), row(case_id="c4", category="docx:n/a")]
    kept, dropped = usable_rows(rows)
    assert len(kept) + sum(dropped.values()) == len(rows)
