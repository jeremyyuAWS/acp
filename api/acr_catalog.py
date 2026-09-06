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
_SECTION_508_PATH = Path(__file__).resolve().parent.parent / "config" / "section-508.json"

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

    Derived from what this build can actually PRODUCE, NOT from the editions we would like to
    offer — which is the whole point. `missing_requirement_sets` refuses an edition this returns
    nothing for, rather than emitting a document that names a standard it does not contain.

    STILL WCAG-ONLY, THOUGH THE 508 CATALOG NOW EXISTS, and the distinction is the reason this
    function is worth reading twice. An earlier version of this docstring said that landing a
    Section 508 catalog would return one more member "with no other change". That is not true, and
    acting on it would recreate the exact defect #1532 fixed: `build_matrix` reads
    `config/wcag-2.2-aa.json` and nothing else, and `acr_export_preview` sorts rows by WCAG
    principle, so a 508 report would still project 55 WCAG rows and zero Section 508 rows — while
    now claiming a catalog backed it.

    Populating a matrix takes three things, and the catalog is one: the requirements, a matrix
    builder that emits their rows, and a projection that renders them in their own chapters. This
    returns REQ_SECTION_508 when the other two land, not before. `section_508_requirements()` is
    reachable meanwhile, so the catalog is testable rather than inert.
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


# ── Revised Section 508 requirement catalog ───────────────────────────────────────────────────
#
# config/section-508.json, generated by scripts/gen_section_508_catalog.py from 36 CFR Part 1194
# Appendix C. Read through its own functions rather than through the WCAG ones above because the
# two answer different questions and have different shapes: a WCAG criterion has a level and a
# principle, a 508 requirement has a chapter and a section, and a row that carried both would be
# one field away from a 508 requirement rendering in a WCAG table.


@functools.lru_cache(maxsize=1)
def _load_508() -> dict:
    return json.loads(_SECTION_508_PATH.read_text(encoding="utf-8"))


def section_508_available() -> bool:
    """Is the Section 508 catalog present in this deployment?

    Separate from `requirement_sets_available()` on purpose: this says the FILE is here, that says
    the whole pipeline can produce the edition. Conflating them is what the docstring there warns
    about.
    """
    return _SECTION_508_PATH.exists()


def section_508_meta() -> dict:
    """The 508 catalog's provenance block — citation, source URL, eCFR date, per-chapter counts."""
    return dict(_load_508()["_meta"])


def section_508_requirements() -> list[dict]:
    """Every requirement in Appendix C chapters 3-6, in regulation order. Copies, not the cache."""
    return [dict(r) for r in _load_508()["requirements"]]


def section_508_requirement(num: str) -> dict | None:
    """One requirement by its dotted number, or None when the catalog does not carry it."""
    for row in _load_508()["requirements"]:
        if row["num"] == num:
            return dict(row)
    return None


@functools.lru_cache(maxsize=1)
def section_508_hash() -> str:
    """SHA-256 over the 508 requirement set — the same construction as `catalog_hash`.

    Kept byte-identical to scripts/gen_section_508_catalog.py's `catalog_hash`, and asserted equal
    in tests/test_acr_section_508_catalog.py, so the generator and the runtime can never disagree
    about which requirement set a report was built from.
    """
    payload = json.dumps(sorted(_load_508()["requirements"],
                                key=lambda r: tuple(int(p) for p in r["num"].split("."))),
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
