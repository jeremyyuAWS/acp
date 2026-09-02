"""Publication and revisions (PRD §16, §17, §21.11, §21.12) — Phase 4.

PUBLICATION IS THE ONE IRREVERSIBLE ACT IN THIS FEATURE. An ACR goes into a customer's procurement
file and cannot be recalled, so the tests that matter most here are the ones asserting what the
endpoint REFUSES, and that what it freezes is true at the moment it freezes.

The single most dangerous behaviour in the phase is not publishing — it is REVISING. PRD §19's
list of things the feature must never do ends on "copy a previous version's Supports decisions
without freshness validation", and a revision exists precisely because the product changed. A
carried decision is a claim about a build nobody re-tested, wearing an approval someone granted
for a different one.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_publish  # noqa: E402

OWNER = "owner@acp.test"
APPROVER = "approver@acp.test"
ANALYST = "analyst@acp.test"
RANDOM = "random@acp.test"


def _now():
    return datetime.now(timezone.utc)


class _Ev:
    """A minimal evidence stand-in — the rules operate on attributes, not on the store."""

    def __init__(self, id_, criterion, *, automated=False, result="pass", tested_at=None,
                 product_version="1.4.0", coverage=None):
        self.id = id_
        self.criterion_num = criterion
        self.is_automated = automated
        self.result = result
        self.tested_at = (tested_at or _now()).isoformat()
        self.product_version = product_version
        self.coverage = coverage
        self.build_id = "b-900"
        self.stale_reason = None


# ── the snapshot content and its digest ────────────────────────────────────────

def test_the_digest_is_recomputable_from_the_content():
    """The entire value of publishing a digest beside the content: anyone holding the snapshot
    recomputes it and gets the same value, which is what makes alteration detectable."""
    content = acr_publish.snapshot_content(
        {"product_name": "ACP", "revision": 1}, [], {}, catalog_hash="abc")
    assert acr_publish.content_digest(content) == acr_publish.content_digest(dict(content))


def test_the_digest_changes_when_a_conformance_level_changes():
    """A digest that did not move when a claim changed would be worse than none."""
    crit = {"criterion_num": "1.4.3", "final_status": "Supports", "principle": "Perceivable"}
    a = acr_publish.snapshot_content({}, [dict(crit)], {}, catalog_hash="abc")
    b = acr_publish.snapshot_content(
        {}, [dict(crit, final_status="Does Not Support")], {}, catalog_hash="abc")
    assert acr_publish.content_digest(a) != acr_publish.content_digest(b)


def test_the_snapshot_never_carries_an_internal_workflow_state():
    """PRD §9. The snapshot is the closest this feature gets to an exported VPAT table, and
    "not_evaluated" appearing where a conformance level goes is the exact failure that column
    split exists to prevent."""
    content = acr_publish.snapshot_content(
        {}, [{"criterion_num": "2.1.1", "final_status": None,
              "workflow_state": "needs_review", "principle": "Operable"}], {}, catalog_hash="h")
    row = content["criteria"][0]
    assert row["conformance_level"] is None
    assert "workflow_state" not in row
    assert "needs_review" not in json.dumps(content)


def test_the_snapshot_reports_counts_and_never_a_percentage():
    """PRD §4.4 and api/accessibility_status.py's house rule. Every available denominator reads as
    a compliance grade, which is what an ACR must not become."""
    content = acr_publish.snapshot_content(
        {}, [{"criterion_num": "1.4.3", "final_status": "Supports", "principle": "Perceivable"},
             {"criterion_num": "2.1.1", "final_status": None, "principle": "Operable"}],
        {}, catalog_hash="h")
    assert content["totals"] == {"total": 2, "undecided": 1, "Supports": 1}
    assert "%" not in json.dumps(content)
    assert "percent" not in json.dumps(content).lower()


def test_the_snapshot_says_on_its_face_that_it_is_not_a_vpat():
    """A snapshot can be exported, mailed and read far from this application, so the disclaimer
    has to live in the artifact rather than only in the screen that renders it."""
    content = acr_publish.snapshot_content({}, [], {}, catalog_hash="h")
    assert "not the official ITI VPAT" in content["note"]
    assert "Automated testing alone" in content["note"]


def test_verify_detects_an_altered_snapshot():
    """The property the digest exists for, exercised rather than assumed."""
    content = acr_publish.snapshot_content({"product_name": "ACP"}, [], {}, catalog_hash="h")
    row = {"content_json": json.dumps(content, sort_keys=True, separators=(",", ":")),
           "content_digest": acr_publish.content_digest(content)}
    ok, why = acr_publish.verify(row)
    assert ok, why

    tampered = dict(content)
    tampered["report"] = {"product_name": "Something Else"}
    row["content_json"] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    ok, why = acr_publish.verify(row)
    assert not ok
    assert "do not match its recorded digest" in why


def test_a_snapshot_with_no_digest_is_reported_as_unverifiable():
    """Absent is not the same as valid — a missing digest must not read as a passing check."""
    ok, why = acr_publish.verify({"content_json": "{}", "content_digest": ""})
    assert not ok and "cannot be verified" in why


def test_the_digest_is_never_described_as_a_signature():
    """A bare hash relabelled a "digital signature" over-claims non-repudiation, and is exactly
    what an auditor checks for. api/report.py carries the same rule for scan reports.

    Asserted as: the module denies it explicitly, AND nothing anywhere in the feature CLAIMS the
    digest is one. A first version of this test scanned every line containing "signature" and
    demanded a nearby negation, which failed on the docstring warning against the mistake — a
    lexical proxy flagging the very sentence that gets it right.
    """
    source = (ACP / "api" / "acr_publish.py").read_text(encoding="utf-8")
    assert "not a signature" in source.lower() or "not a digital signature" in source.lower()

    # No affirmative claim, anywhere the digest is surfaced to a caller.
    for path in ("api/acr_publish.py", "api/routes/acr.py"):
        text = (ACP / path).read_text(encoding="utf-8").lower()
        for claim in ("is a digital signature", "digitally signed", "signed by",
                      "signature of the", "cryptographic signature"):
            assert claim not in text, f"{path} claims the digest is a signature: {claim!r}"


# ── carry-forward: the rule PRD §19 ends on ────────────────────────────────────

def test_a_supports_claim_whose_evidence_went_stale_does_not_carry():
    """PRD §19's last line, and this phase's version of the `inapplicable` trap.

    A revision exists BECAUSE the product changed. Carrying "Supports" into it unexamined is a
    conformance claim about a build nobody tested.
    """
    crit = [{"criterion_num": "1.4.3", "final_status": "Supports", "remarks": "",
             "approval_state": "approved", "reviewer": APPROVER}]
    # Evidence recorded against the OLD version; the new report is a different one.
    ev = {"1.4.3": [_Ev("e1", "1.4.3", product_version="1.4.0")]}
    carried, reset = acr_publish.carry_forward(
        crit, ev, new_report={"product_version": "2.0.0", "evidence_validity_days": 180})

    assert reset == ["1.4.3"]
    assert carried[0]["final_status"] is None
    assert carried[0]["workflow_state"] == acr_publish.CARRY_RESET_STATE


def test_a_limitation_status_carries_with_its_remarks():
    """"Partially Supports", "Does Not Support" and "Not Applicable" are LIMITATION claims.
    Carrying a known barrier forward understates nothing, and re-typing the remarks would lose the
    record of what was actually found."""
    crit = [{"criterion_num": "1.4.3", "final_status": "Does Not Support",
             "remarks": "The chart legend fails at 2.9:1.", "approval_state": "approved"}]
    carried, reset = acr_publish.carry_forward(
        crit, {}, new_report={"product_version": "2.0.0"})
    assert reset == []
    assert carried[0]["final_status"] == "Does Not Support"
    assert "2.9:1" in carried[0]["remarks"]


def test_no_approval_carries_into_a_revision_at_all():
    """PRD §4.2 requires an approver to sign off every applicable criterion of THIS report. An
    approval granted against the previous revision was granted for a different product version, so
    carrying it would record a sign-off that never happened.

    Note this holds even for a decision that DID carry — the decision is a convenience, the
    approval is a claim about who reviewed what.
    """
    crit = [{"criterion_num": "1.4.3", "final_status": "Does Not Support", "remarks": "x",
             "approval_state": "approved", "reviewer": APPROVER, "approved_at": "2026-01-01"}]
    carried, _ = acr_publish.carry_forward(crit, {}, new_report={"product_version": "2.0.0"})
    assert carried[0]["approval_state"] == "unapproved"
    assert carried[0]["reviewer"] is None
    assert carried[0]["approved_at"] is None


def test_a_supports_claim_with_still_live_evidence_carries():
    """The other half. A gate that can never be satisfied is as broken as one that never fires —
    if nothing could ever carry, a revision would mean re-doing the entire evaluation."""
    crit = [{"criterion_num": "1.4.3", "final_status": "Supports", "remarks": "",
             "approval_state": "approved"}]
    ev = {"1.4.3": [_Ev("e1", "1.4.3", product_version="2.0.0")]}
    carried, reset = acr_publish.carry_forward(
        crit, ev, new_report={"product_version": "2.0.0", "evidence_validity_days": 180})
    assert reset == []
    assert carried[0]["final_status"] == "Supports"
    # …but still unapproved.
    assert carried[0]["approval_state"] == "unapproved"


def test_the_store_cannot_carry_an_approval_even_if_asked():
    """Defence in depth for the rule above, at the layer that writes.

    carry_acr_decisions has no code path to approval_state, reviewer or approved_at. Reading the
    source is the honest check here: a behavioural test would only prove the caller does not
    currently pass one.
    """
    source = (ACP / "api" / "store.py").read_text(encoding="utf-8")
    start = source.index("def carry_acr_decisions")
    body = source[start:source.index("def list_acr_snapshots", start)]
    assert "approval_state" not in body.split('"""')[2], \
        "carry_acr_decisions must not be able to write approval_state"
    for forbidden in ("reviewer=", "approved_at="):
        assert forbidden not in body, f"carry_acr_decisions writes {forbidden}"


def test_the_publish_module_does_not_decide_whether_publishing_is_allowed():
    """The gate lives in acr_validation and acr_authz, which are tested on their own. A module
    that both builds the artifact and judges whether it may exist can talk itself into producing
    one.

    Checked by IMPORTS rather than by substring: acr_publish's docstring names both modules to say
    they own the gate, and a substring scan cannot tell an explanation from a dependency. The
    first version of this test could not, and failed on its own documentation.
    """
    import ast

    tree = ast.parse((ACP / "api" / "acr_publish.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    forbidden = imported & {"acr_validation", "acr_authz", "core", "store"}
    assert not forbidden, f"acr_publish imports the gate it must not own: {sorted(forbidden)}"
