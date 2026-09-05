"""Publication: the snapshot's content, its digest, and what carries into a revision (PRD §16–17).

WHAT PUBLISHING IS. An ACR goes into a customer's procurement file and cannot be recalled. So
publication is the one irreversible act in this feature, and everything the earlier phases built —
coverage gating, freshness, the four-term vocabulary, the manual-plan seam — exists so that the
thing which becomes irreversible is true when it is frozen.

This module is pure functions over records: it builds the snapshot content, digests it, and
decides what a revision may carry forward. It does NOT decide whether publication is allowed —
`acr_validation.validate` and `acr_authz.may_publish` own that, and `routes/acr.py` calls them.
Keeping the gate out of here is deliberate: a module that both builds the artifact and judges
whether it may exist can talk itself into producing one.

THE DIGEST IS NOT A SIGNATURE. `content_digest` is a recomputable SHA-256 over the canonical
snapshot content. Anyone holding the same snapshot recomputes it and gets the same value, which
makes the published report tamper-EVIDENT. It has no key and provides no non-repudiation: it
proves the content matches what was stored, never who produced it. `api/report.py::_content_digest`
carries the same warning and the same instruction, and it is worth repeating rather than
cross-referencing, because relabelling a bare hash a "digital signature" is exactly what an
auditor checks for.

THE REVISION TRAP, which is this phase's version of the `inapplicable` mistake. PRD §19's list of
things the feature must never do ends with: *copy a previous version's "Supports" decisions
without freshness validation.* A revision exists precisely because the product moved on, so every
decision carried into it is a claim about a version nobody re-tested. `carry_forward` therefore
re-derives staleness against the NEW report and returns decisions to `needs_review` wherever the
evidence no longer supports them — see `carry_forward` for exactly which ones survive and why.
"""
from __future__ import annotations

import hashlib
import json

import acr_freshness
from acr_catalog import NEEDS_REVIEW, SUPPORTS
# The snapshot orders criteria exactly as the export preview does. Reusing its sort rather than
# writing a second one is not tidiness: two orderings that drift would give the same content two
# different digests depending on which code path built it, and a digest that changes without the
# content changing trains a reader to ignore a mismatch.
from acr_export_preview import _PRINCIPLE_ORDER, _sortkey

# What a revision resets. A carried decision is only as good as the evidence still standing behind
# it, and `Supports` is the claim that costs the most if it is wrong — it is the only one of the
# four that asserts the product HAS no barrier here.
CARRY_RESET_STATE = NEEDS_REVIEW


def snapshot_content(report: dict, criteria: list[dict], evidence_by_criterion: dict[str, list],
                     *, catalog_hash: str) -> dict:
    """The canonical, ordered content of a published ACR.

    Ordered and explicit because it is what the digest is computed over: a dict whose key order or
    membership varied between builds would produce a different digest for identical content, and a
    digest that changes without the content changing is worse than none — it trains a reader to
    ignore a mismatch.

    Evidence is included in SUMMARY form rather than in full. The snapshot records what supported
    each conformance claim at publication time: how many live records, of what kinds, and the
    identifiers, so an auditor can go back to `acr_evidence` for the detail. Copying every row in
    would make the snapshot a second source of truth that can disagree with the first.
    """
    rows = []
    for crit in sorted(criteria, key=lambda c: (_PRINCIPLE_ORDER.get(c.get("principle"), 9),
                                                _sortkey(c["criterion_num"]))):
        num = crit["criterion_num"]
        ev = evidence_by_criterion.get(num, [])
        rows.append({
            "criterion_num": num,
            "criterion_name": crit.get("criterion_name"),
            "level": crit.get("level"),
            # The four VPAT terms and nothing else. workflow_state is deliberately absent:
            # PRD §9 forbids an internal state appearing where a conformance level goes, and the
            # snapshot is the closest this feature gets to an exported VPAT table.
            "conformance_level": crit.get("final_status"),
            "remarks": crit.get("remarks") or "",
            "evaluator": crit.get("evaluator"),
            "reviewer": crit.get("reviewer"),
            "approved_at": crit.get("approved_at"),
            "evidence": {
                "total": len(ev),
                "automated": sum(1 for e in ev if getattr(e, "is_automated", False)),
                "manual": sum(1 for e in ev if not getattr(e, "is_automated", False)),
                "ids": sorted(e.id for e in ev),
            },
        })

    return {
        "schema": "acp.acr.snapshot/1",
        "catalog_hash": catalog_hash,
        "report": {k: report.get(k) for k in (
            "report_title", "product_name", "product_version", "build_id", "release_date",
            "vendor_name", "vendor_contact", "product_description", "evaluation_scope",
            "excluded_functionality", "deployment_environment", "vpat_edition", "wcag_version",
            "wcag_levels", "evaluation_methods", "browsers_tested", "operating_systems_tested",
            "assistive_technologies_tested", "automated_tools", "testing_period_start",
            "testing_period_end", "evaluators", "approver", "general_notes",
            "known_dependencies", "evidence_validity_days", "revision", "supersedes_id")},
        "criteria": rows,
        "totals": _totals(rows),
        # Stated inside the artifact, not only in the UI that renders it. A snapshot can be
        # exported, mailed and read far from this application.
        "note": ("This is ACP's structural record of a conformance evaluation. It is not the "
                 "official ITI VPAT® document. Automated testing alone never established any "
                 "conformance claim in this report."),
    }


def _totals(rows: list[dict]) -> dict:
    """Counts per conformance level. COUNTS ONLY, never a percentage.

    api/accessibility_status.py's house rule, and PRD §4.4's: a percentage needs a denominator,
    and every denominator available here ("of applicable criteria", "of the standard") reads as a
    compliance grade. The point of an ACR is the four terms, not a score.
    """
    out: dict[str, int] = {"total": len(rows), "undecided": 0}
    for row in rows:
        level = row["conformance_level"]
        if not level:
            out["undecided"] += 1
        else:
            out[level] = out.get(level, 0) + 1
    return out


def content_digest(content: dict) -> str:
    """SHA-256 over the canonical JSON of the snapshot content.

    A DIGEST, NOT A SIGNATURE. No key, no non-repudiation: it proves the snapshot's contents are
    what were stored, never who produced them. `api/report.py::_content_digest` says the same
    thing about scan reports, and the instruction there applies here — never relabel it.

    `sort_keys` and the tight separators make it recomputable by anyone holding the same content,
    which is the entire value of publishing it alongside.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify(snapshot_row: dict) -> tuple[bool, str]:
    """Recompute a stored snapshot's digest and compare.

    Called on every read of a published revision rather than on demand. A tamper-evident record
    that nobody ever verifies is a record nobody has checked — the evidence is only as good as the
    check, and the cheapest moment to run it is when someone asks to see the thing.
    """
    try:
        content = json.loads(snapshot_row.get("content_json") or "{}")
    except (ValueError, TypeError):
        return False, "the stored snapshot content is not readable JSON"

    stored = (snapshot_row.get("content_digest") or "").strip().lower()
    actual = content_digest(content)
    if not stored:
        return False, "this snapshot carries no digest, so its contents cannot be verified"
    if stored != actual:
        return False, (f"this snapshot's contents do not match its recorded digest "
                       f"(recorded {stored[:12]}…, recomputed {actual[:12]}…) — it has been "
                       f"altered since publication, or was written by a different version")
    return True, ""


def carry_forward(criteria: list[dict], evidence_by_criterion: dict[str, list],
                  *, new_report: dict) -> tuple[list[dict], list[str]]:
    """What a NEW revision inherits from the published one, and what it must re-earn.

    THE RULE PRD §19 ENDS ON: never copy a previous version's "Supports" decisions without
    freshness validation. A revision exists because the product changed; a decision carried into
    it unexamined is a conformance claim about a build nobody tested, wearing an approval someone
    granted for a different one.

    So every carried row is re-derived against the NEW report:

      · evidence that is now stale for the new version does not support anything,
      · a `Supports` claim with no live evidence left goes back to `needs_review`, unapproved,
      · the other three statuses carry with their remarks, because "Partially Supports", "Does Not
        Support" and "Not Applicable" are LIMITATION claims — carrying a known barrier forward
        understates nothing, and re-typing the remarks would lose the record of what was found.

    Returns (rows, reset_criteria). The reset list is surfaced to the person creating the revision
    rather than applied silently: they need to know what they are being asked to re-evaluate, and
    a quiet reset reads as data loss.
    """
    stale = acr_freshness.evaluate(new_report,
                                   [e for rows in evidence_by_criterion.values() for e in rows])
    stale_ids = set(stale)

    carried: list[dict] = []
    reset: list[str] = []
    for crit in criteria:
        num = crit["criterion_num"]
        row = dict(crit)
        final = crit.get("final_status")

        if final == SUPPORTS:
            live = [e for e in evidence_by_criterion.get(num, []) if e.id not in stale_ids]
            if not live:
                row["final_status"] = None
                row["workflow_state"] = CARRY_RESET_STATE
                row["approval_state"] = "unapproved"
                row["reviewer"] = None
                row["approved_at"] = None
                reset.append(num)
        # Every carried criterion re-enters the approval queue regardless of status: PRD §4.2
        # requires an approver to sign off every applicable criterion of THIS report, and an
        # approval granted against the previous revision was granted for a different product
        # version. Carrying the decision forward is a convenience; carrying the APPROVAL forward
        # would be the sign-off that never happened.
        row["approval_state"] = "unapproved"
        row["reviewer"] = None
        row["approved_at"] = None
        carried.append(row)

    return carried, reset


def projection_inputs(content: dict) -> tuple[dict, list[dict], dict[str, list]]:
    """Rehydrate a verified snapshot into the three arguments `acr_export_preview.project` takes.

    WHY REHYDRATE INSTEAD OF WRITING A SECOND RENDERER. A published revision and a draft are the
    same document at two moments, and a customer comparing them must be comparing the report
    rather than two renderers. A separate builder for published content would give the feature two
    ways to say the same thing, and the honesty rules in acr_export_preview — no workflow state in
    the conformance column, no criterion omitted, counts and never a percentage — would then be
    enforced on one path and merely intended on the other.

    So the snapshot is translated into the projection's input shape and goes through the same
    `project()` every other export uses. What that costs is this function; what it buys is that a
    published PDF cannot contain a cell the draft path would have refused.

    WHAT COMES FROM THE SNAPSHOT AND WHAT DOES NOT, which is the whole point of exporting a
    published revision rather than today's draft:

      · Every CLAIM is the snapshot's, and is covered by the digest the caller has already
        verified: the conformance level, the remarks, who evaluated and reviewed it, and all of
        the report metadata.
      · `principle` and `guideline` are NOT in the snapshot. They come from the catalog, because
        they are facts about WCAG rather than claims about the product — and because `project()`
        groups by principle, so without them a published export would come out in a different
        ORDER than the snapshot it was built from, which reads as a different document.
      · `draft_status` is forced to None. It is ACP's own suggestion for an undecided criterion; a
        published revision has none, and injecting today's would put a machine's opinion into a
        record a human signed.

    A criterion the catalog no longer carries keeps its snapshot row and loses only its grouping.
    Dropping it would be PRD §19's "conceal failures" arriving by way of a schema change: the
    claim was published and stays published after WCAG moves on.
    """
    import acr_catalog

    report = dict(content.get("report") or {})
    # `project()` reads both off the report for the header table, and a published export that
    # renders as a draft misrepresents the most consequential fact about itself.
    report["status"] = "published"
    report["catalog_hash"] = content.get("catalog_hash")

    criteria: list[dict] = []
    evidence_by_criterion: dict[str, list] = {}
    for row in content.get("criteria") or []:
        num = row.get("criterion_num")
        cat = acr_catalog.criterion(num) or {}
        criteria.append({
            "criterion_num": num,
            "criterion_name": row.get("criterion_name") or cat.get("name"),
            "level": row.get("level") or cat.get("level"),
            "principle": cat.get("principle"),
            "guideline": cat.get("guideline"),
            # The snapshot's column is already named for what it is. `project()` calls it
            # final_status and `_conformance_cell` re-validates it against the four VPAT terms —
            # exactly the check worth running again on a record read back out of storage.
            "final_status": row.get("conformance_level"),
            "remarks": row.get("remarks") or "",
            "draft_status": None,
            # Derived from the snapshot's own approved_at rather than defaulted: a published
            # criterion carries the approval it was published with, and defaulting every row to
            # "unapproved" would report an approval gap that publication had already closed.
            "approval_state": "approved" if row.get("approved_at") else "unapproved",
            "evaluator": row.get("evaluator"),
            "reviewer": row.get("reviewer"),
        })
        evidence_by_criterion[num] = _evidence_standins(row.get("evidence") or {})

    return report, criteria, evidence_by_criterion


class _SnapshotEvidence:
    """A stand-in carrying the only thing `project()` reads off an evidence record: its id.

    The snapshot stores evidence in SUMMARY form — counts and ids, never the rows — so there is
    nothing to reconstruct and nothing that should be. These exist so a published export reports
    the evidence COUNT the snapshot recorded instead of the zero an empty mapping would produce,
    which would render as a conformance claim with nothing behind it.
    """

    __slots__ = ("id",)

    def __init__(self, ident: str):
        self.id = ident


def _evidence_standins(summary: dict) -> list:
    """One stand-in per recorded evidence id, falling back to the recorded total.

    The fallback is for a snapshot written before ids were stored: the count is the fact a reader
    needs, and losing it because the identifiers are absent would understate what stood behind a
    published claim.
    """
    ids = summary.get("ids")
    if ids:
        return [_SnapshotEvidence(str(i)) for i in ids]
    return [_SnapshotEvidence(f"unrecorded-{n}") for n in range(int(summary.get("total") or 0))]
