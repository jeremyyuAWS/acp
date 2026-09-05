"""The export's own PRD §9 guard — the last layer before a customer reads the document.

WHY THIS FILE EXISTS. A mutation audit of the Phase 1–4 bite checks broke nineteen load-bearing
rules one at a time and ran the whole ACR suite against each. Eighteen turned it red. This one did
not: replacing `_conformance_cell`'s raise with `return final` — so an internal workflow state
prints where a conformance level goes — left **373 passed**.

The guard was written deliberately and reasoned about at length in its own docstring:

    acr_model, store.save_acr_decision and acr_validation each refuse this independently; if a
    value still arrives here it means every one of those was bypassed, and the correct behaviour
    at the last layer before a customer reads it is to fail, not to print it.

Every one of those three upstream refusals has tests. The last one had none, which is the wrong
one to leave unverified: the earlier layers fail loudly and in this application, while this one
fails into a document that leaves the building. `acr_export_preview` had no test file at all — it
is reached only through the PDF tests, and those all pass valid statuses, so nothing had ever fed
it a value the guard is for.

WHAT IS ASSERTED, and at which level. The private helper is exercised directly for the message,
but the load-bearing assertions go through `project()` and through the published-snapshot path,
because those are how a bad value would actually arrive — one from live rows, one read back out
of storage. A guard tested only through its own private function is a guard nobody proved the
callers reach.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402
import acr_export_preview  # noqa: E402
import acr_publish  # noqa: E402

REPORT = {"report_title": "ACP ACR", "product_name": "ACP", "product_version": "1.4.0"}


def _crit(final_status):
    return {"criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)", "level": "AA",
            "principle": "Perceivable", "final_status": final_status, "remarks": ""}


# The vocabulary comes from the module that defines it. Typing the three states here would let the
# test keep passing for a state added later — exactly the drift that puts an unexported value in
# front of a customer.
@pytest.mark.parametrize("state", sorted(acr_catalog.WORKFLOW_STATES))
def test_no_internal_workflow_state_can_be_exported_as_a_conformance_level(state):
    """PRD §9. `decided` is the one that matters most: it is the state of a criterion somebody
    really did finish, so it is the value most likely to look reasonable in the column and the
    least likely to be questioned by whoever reads the exported table."""
    with pytest.raises(ValueError, match="internal workflow state"):
        acr_export_preview.project(REPORT, [_crit(state)])


def test_the_refusal_names_the_criterion_and_the_rule():
    """A raise that does not say which criterion sends whoever hits it through 55 rows by hand."""
    with pytest.raises(ValueError) as exc:
        acr_export_preview.project(REPORT, [_crit(acr_catalog.DECIDED)])
    message = str(exc.value)
    assert "1.4.3" in message
    assert "PRD §9" in message


def test_a_value_outside_the_vpat_vocabulary_is_refused_too():
    """The second branch of the same guard. `acr_validation` catches this on the publish path and
    is tested there; the export is reached by `/preview` without publishing, so a draft with a
    junk status in the column would render for a reviewer with nothing having refused it."""
    with pytest.raises(ValueError, match="not a VPAT"):
        acr_export_preview.project(REPORT, [_crit("Mostly Supports")])


def test_an_undecided_criterion_renders_a_placeholder_instead_of_raising():
    """The branch that must NOT fail. Every applicable criterion appears in the projection,
    including the ones nobody has decided — that is what makes the preview a publication review
    rather than a highlight reel, and a guard that swallowed this would empty the table."""
    projection = acr_export_preview.project(REPORT, [_crit(None)])
    cell = projection["criteria"][0]["conformance_level"]
    assert cell == acr_export_preview.UNDECIDED_CELL
    assert projection["criteria"][0]["decided"] is False


def test_the_placeholder_cannot_be_mistaken_for_a_conformance_claim():
    """It sits in the conformance column, so it has to be unmistakably not one of the four terms —
    and not word-shaped like one either."""
    assert acr_export_preview.UNDECIDED_CELL not in acr_catalog.FINAL_STATUSES
    assert acr_export_preview.UNDECIDED_CELL not in acr_catalog.WORKFLOW_STATES
    assert not acr_export_preview.UNDECIDED_CELL[0].isalnum()


def test_the_guard_still_stands_on_the_published_snapshot_path():
    """The path that reads a value back OUT of storage, which is the one the guard's own docstring
    is about — 'a value that reached the database another way'. A published snapshot is rendered
    months later by `projection_inputs`, long after the upstream refusals ran, so it is the last
    place a bad value can surface and the only place left to refuse it.
    """
    content = {
        "schema": "acp.acr.snapshot/1", "catalog_hash": "abc",
        "report": dict(REPORT),
        "criteria": [{"criterion_num": "1.4.3", "criterion_name": "Contrast (Minimum)",
                      "level": "AA", "conformance_level": acr_catalog.NEEDS_REVIEW,
                      "remarks": "", "evidence": {"total": 0, "ids": []}}],
        "totals": {"total": 1},
    }
    report, criteria, ev = acr_publish.projection_inputs(content)
    with pytest.raises(ValueError, match="internal workflow state"):
        acr_export_preview.project(report, criteria, evidence_by_criterion=ev, stale_ids=set())
