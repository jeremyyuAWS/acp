"""Versioned WCAG catalog for the ACR workspace — read-only projection over config/wcag-2.2-aa.json.

PRD §7.5: "ACP creates the applicable criteria matrix from a versioned standards catalog." This is
that catalog's reader. It defines no policy and evaluates nothing — it answers "which criteria does
this report have to account for, and what are they called", and it stamps a hash so a published
report can say which catalog it was built from.

WHY A SECOND CATALOG EXISTS IN THIS REPO, and why it must not be merged with the first. There are
now two, and they answer different questions about different subjects:

  config/rule-catalog.json    — WCAG 2.1, per document format (docx/pptx/xlsx/pdf). "What can ACP
                                detect in a CUSTOMER'S FILE." Read by assessment_policy/scanner.
  config/wcag-2.2-aa.json     — WCAG 2.2 A+AA, no format axis. "Which criteria is ACP'S OWN WEB UI
                                evaluated against." Read by this module, and by nothing else.

docs/conformance-report.md already draws exactly this line in prose ("the conformance of the
platform's own web UI, not the conformance of customer documents it remediates"). Merging them
would let a finding about a customer's Word file become evidence for a claim about ACP's UI, which
is the "unsupported compliance claim" the PRD's problem statement opens with.

The catalog file is GENERATED from the W3C Recommendation (scripts/gen_wcag_catalog.py), not
hand-maintained, for the reason that script's docstring gives: a missing criterion or a wrong level
is invisible at every stage until a customer's procurement reviewer finds it.
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "wcag-2.2-aa.json"

# The VPAT conformance vocabulary, verbatim. PRD §9: "Do not invent additional final statuses."
SUPPORTS = "Supports"
PARTIALLY_SUPPORTS = "Partially Supports"
DOES_NOT_SUPPORT = "Does Not Support"
NOT_APPLICABLE = "Not Applicable"
FINAL_STATUSES: frozenset[str] = frozenset({SUPPORTS, PARTIALLY_SUPPORTS, DOES_NOT_SUPPORT,
                                            NOT_APPLICABLE})

# Statuses whose remarks are mandatory (PRD §10, §21.7). "Supports" is the one that does not
# require remarks — it requires EVIDENCE, which is a different gate in acr_rules.
REMARKS_REQUIRED: frozenset[str] = frozenset({PARTIALLY_SUPPORTS, DOES_NOT_SUPPORT, NOT_APPLICABLE})

# Internal workflow states. PRD §9 is explicit that these are NOT conformance levels and must never
# render as one — which is why they live in their own constant, and in their own column
# (acr_criterion.workflow_state), rather than sharing the final_status vocabulary above. One column
# holding both is how "Not evaluated" ends up printed in a VPAT table.
NOT_EVALUATED = "not_evaluated"
NEEDS_REVIEW = "needs_review"
DECIDED = "decided"
WORKFLOW_STATES: frozenset[str] = frozenset({NOT_EVALUATED, NEEDS_REVIEW, DECIDED})


@functools.lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def meta() -> dict:
    """The catalog's provenance block — standard, version, levels, source URL, counts."""
    return dict(_load()["_meta"])


def criteria() -> list[dict]:
    """Every applicable criterion, in spec order. Copies, so a caller cannot mutate the cache."""
    return [dict(r) for r in _load()["criteria"]]


def criterion(num: str) -> dict | None:
    """One criterion by its dotted number, or None when the catalog does not carry it."""
    for row in _load()["criteria"]:
        if row["num"] == num:
            return dict(row)
    return None


def numbers() -> list[str]:
    """Just the criterion numbers, in spec order."""
    return [r["num"] for r in _load()["criteria"]]


@functools.lru_cache(maxsize=1)
def catalog_hash() -> str:
    """SHA-256 over the criteria set, key-sorted and number-sorted.

    Stable across _meta edits and across a regeneration that only reorders — it identifies the SET
    OF CRITERIA, not the file's bytes. A report stamps this at creation and a snapshot freezes it,
    so a published ACR stays interpretable after the catalog advances to WCAG 2.3. Same idea as the
    rubric_hash overview_snapshots already keys on.

    Kept byte-identical to scripts/gen_wcag_catalog.py's `catalog_hash` — the generator prints it
    and tests/test_acr_catalog.py asserts the two agree, so the script and the runtime can never
    disagree about which catalog a report was built from.
    """
    payload = json.dumps(sorted(_load()["criteria"], key=lambda r: r["num"]),
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_matrix(report_id: str) -> list[dict]:
    """The initial criteria matrix for a new report — one row per applicable criterion.

    Every row starts at NOT_EVALUATED with no final status. PRD §10 is explicit that this is an
    internal draft state and that a report containing applicable criteria in it cannot be
    published; acr_validation enforces that, and this function is why the state exists at all.

    `applicable` starts True for every criterion in the catalog. Marking one Not Applicable is a
    human DECISION (with required remarks, PRD §10), not a default the system picks — so there is
    no applicability heuristic here, deliberately.
    """
    return [
        {
            "report_id": report_id,
            "criterion_num": row["num"],
            "criterion_name": row["name"],
            "level": row["level"],
            "principle": row["principle"],
            "guideline": row["guideline"],
            "applicable": True,
            "workflow_state": NOT_EVALUATED,
            "draft_status": None,
            "final_status": None,
            "remarks": None,
            "evaluator": None,
            "reviewer": None,
            "approval_state": "unapproved",
        }
        for row in _load()["criteria"]
    ]
