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

# ── VPAT editions (PRD delivery phase 6) ──────────────────────────────────────────────────────
#
# ITI publishes VPAT 2.5Rev in four editions, and they are not four names for one document: each
# obliges the report to carry a DIFFERENT set of requirements. The WCAG edition carries the WCAG
# success criteria alone; 508 adds the Revised Section 508 chapters (302 functional performance,
# 501-504 software, 601-602 support documentation); EU adds EN 301 549; INT carries all three.
#
# WHY THIS EXISTS AS A CLOSED VOCABULARY. `vpat_edition` was free text — required to be present,
# never checked against anything, and read by nothing. Measured on 2026-09-06 against this repo at
# c1dbe89c: a report whose author typed "VPAT 2.5Rev 508" projected `template.edition` =
# "VPAT 2.5Rev 508" over 55 WCAG 2.2 A+AA rows and ZERO Section 508 chapter rows, with
# `totals.total` = 55. The exported document declared itself the Section 508 edition and contained
# none of Section 508. That is the "unsupported compliance claim" this product's problem statement
# opens with, produced by the tool built to prevent it — and it went to a procurement file, where
# PRD §17's reasoning applies: it cannot be recalled.
#
# So an edition is a CLAIM ABOUT CONTENT, and the claim is checked. The mapping below is what makes
# it checkable; acr_validation turns it into a publication blocker.
REQ_WCAG = "wcag-2.2-aa"
REQ_SECTION_508 = "section-508"
REQ_EN_301_549 = "en-301-549"

EDITION_WCAG = "VPAT 2.5Rev WCAG"
EDITION_508 = "VPAT 2.5Rev 508"
EDITION_EU = "VPAT 2.5Rev EU"
EDITION_INT = "VPAT 2.5Rev INT"

EDITION_REQUIREMENT_SETS: dict[str, frozenset[str]] = {
    EDITION_WCAG: frozenset({REQ_WCAG}),
    EDITION_508: frozenset({REQ_WCAG, REQ_SECTION_508}),
    EDITION_EU: frozenset({REQ_WCAG, REQ_EN_301_549}),
    EDITION_INT: frozenset({REQ_WCAG, REQ_SECTION_508, REQ_EN_301_549}),
}
EDITIONS: frozenset[str] = frozenset(EDITION_REQUIREMENT_SETS)

# Human-readable names for the requirement sets, for messages a report author has to act on.
REQUIREMENT_SET_NAMES = {
    REQ_WCAG: "WCAG 2.2 Level A and AA",
    REQ_SECTION_508: "Revised Section 508 (chapters 3-6)",
    REQ_EN_301_549: "EN 301 549",
}


def requirement_sets_available() -> frozenset[str]:
    """The requirement sets this deployment can actually populate a matrix from.

    Derived from the catalogs that exist, NOT from the editions we would like to offer — which is
    the whole point. Today `config/wcag-2.2-aa.json` is the only catalog in the repo, so only the
    WCAG edition can be honestly produced, and `missing_requirement_sets` refuses the other three
    rather than emitting a document that names a standard it does not contain.

    When a Section 508 catalog lands this returns one more member and the 508 edition becomes
    offerable with no other change — the gate opens because the content arrived, which is the
    ordering that keeps the claim true.
    """
    return frozenset({REQ_WCAG})


def missing_requirement_sets(edition: str | None) -> frozenset[str]:
    """Requirement sets `edition` obliges the report to carry that this deployment cannot supply.

    Empty means the edition is honestly producible. An unknown edition is not this function's
    business — `edition_known` answers that; conflating "misspelled" with "not yet built" would
    give a report author one message for two different problems.
    """
    required = EDITION_REQUIREMENT_SETS.get(edition or "", frozenset())
    return frozenset(required - requirement_sets_available())


def edition_known(edition: str | None) -> bool:
    """Is this one of the four editions ITI publishes?"""
    return (edition or "") in EDITIONS


def offerable_editions() -> list[str]:
    """The editions a report can be created as today, in ITI's own order."""
    return [e for e in (EDITION_WCAG, EDITION_508, EDITION_EU, EDITION_INT)
            if not missing_requirement_sets(e)]


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
