"""Draft structural export preview (PRD §15 publication review, §16 without the ITI template).

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
----------------------------------------------
PRD §16 requires the exported ACR to be built on the official ITI VPAT® 2.5Rev template. That is
Phase 5, and it is gated on a decision that has not been made: vendoring a third-party template
into this repo carries the VPAT® trademark's usage terms, and this codebase's precedent for
vendoring a third-party artifact (ADR 0029, the PDF analyser) is that it gets its own ADR first.

So this module renders the report's CONTENT in the VPAT table's shape — the same rows, the same
column meanings, the same four conformance terms — and nothing else. It emits JSON and a plain
HTML table. It does not emit .docx, does not claim to be a VPAT, and its rendered output says so
in as many words. Phase 5 replaces the renderer; the projection below is what it will fill the
template's tables from, so the shape is built now and proven against real records rather than
designed around a template nobody has committed yet.

THE HONESTY CONSTRAINTS TRAVEL WITH THE CONTENT, not with the renderer
-----------------------------------------------------------------------
Three things this must never do, all of them PRD §19 non-goals, and all of them easier to get
wrong in a renderer than in a rule engine:

  * Never emit an internal workflow state ("not evaluated", "needs review") in the conformance
    column. `_conformance_cell` refuses, loudly, rather than printing one.
  * Never present a draft status as a decision. `draft_status` is ACP's suggestion; it appears in
    the preview labelled as such and never in the conformance column.
  * Never omit a criterion because it is inconvenient. Every applicable criterion in the matrix
    appears in the projection, including the undecided ones — which is what makes the preview
    usable as a publication review rather than a highlight reel.
"""
from __future__ import annotations

import html
import json

from acr_catalog import FINAL_STATUSES, WORKFLOW_STATES

# Rendered where a conformance level would go for a criterion nobody has decided yet. NOT one of
# the four VPAT terms, and deliberately not word-shaped like one — a preview reader must be unable
# to mistake it for a conformance claim, and a publication that still contains one is blocked by
# acr_validation long before it reaches here.
UNDECIDED_CELL = "— not yet evaluated —"

_PRINCIPLE_ORDER = {"Perceivable": 1, "Operable": 2, "Understandable": 3, "Robust": 4}


def _conformance_cell(criterion: dict) -> str:
    """The conformance column's text for one criterion.

    Raises rather than degrades on a workflow state that reached final_status. acr_model,
    store.save_acr_decision and acr_validation each refuse this independently; if a value still
    arrives here it means every one of those was bypassed, and the correct behaviour at the last
    layer before a customer reads it is to fail, not to print it.
    """
    final = criterion.get("final_status")
    if not final:
        return UNDECIDED_CELL
    if final in WORKFLOW_STATES:
        raise ValueError(
            f"criterion {criterion.get('criterion_num')} carries the internal workflow state "
            f"{final!r} in final_status — internal states must never be exported as a "
            f"conformance level (PRD §9)")
    if final not in FINAL_STATUSES:
        raise ValueError(
            f"criterion {criterion.get('criterion_num')} carries {final!r}, which is not a VPAT "
            f"conformance level {sorted(FINAL_STATUSES)}")
    return final


def project(report: dict, criteria: list[dict], *, evidence_by_criterion: dict[str, list] | None = None,
            stale_ids: set[str] | None = None) -> dict:
    """The report as the structure a VPAT table is filled from. Pure data; no formatting.

    This is the seam Phase 5 plugs the ITI template into: the template's tables consume exactly
    these rows. Keeping the projection separate from the renderer means the Word export inherits
    the honesty checks above rather than reimplementing them.
    """
    ev = evidence_by_criterion or {}
    stale = stale_ids or set()

    rows = []
    for c in sorted(criteria, key=lambda r: (_PRINCIPLE_ORDER.get(r.get("principle"), 9),
                                             _sortkey(r["criterion_num"]))):
        crit_ev = ev.get(c["criterion_num"], [])
        live = [e for e in crit_ev if getattr(e, "id", None) not in stale]
        rows.append({
            "criterion_num": c["criterion_num"],
            "criterion_name": c.get("criterion_name"),
            "level": c.get("level"),
            "principle": c.get("principle"),
            "guideline": c.get("guideline"),
            "conformance_level": _conformance_cell(c),
            "remarks": c.get("remarks") or "",
            "decided": bool(c.get("final_status")),
            # ACP's suggestion, carried separately and labelled. Never the conformance cell.
            "draft_status": c.get("draft_status"),
            "approval_state": c.get("approval_state", "unapproved"),
            "evaluator": c.get("evaluator"),
            "reviewer": c.get("reviewer"),
            "evidence_live": len(live),
            "evidence_stale": len(crit_ev) - len(live),
        })

    return {
        "template": {
            # Named, so a reader of the JSON knows what this is not.
            "edition": report.get("vpat_edition") or "(not selected)",
            "is_official_iti_template": False,
            "note": ("Structural preview only. The official ITI VPAT® template is integrated in "
                     "Phase 5; this output mirrors the VPAT table shape and is not a VPAT."),
        },
        "report": {k: report.get(k) for k in (
            "report_title", "product_name", "product_version", "build_id", "release_date",
            "vendor_name", "vendor_contact", "product_description", "evaluation_scope",
            "excluded_functionality", "deployment_environment", "vpat_edition", "wcag_version",
            "wcag_levels", "evaluation_methods", "browsers_tested", "operating_systems_tested",
            "assistive_technologies_tested", "automated_tools", "testing_period_start",
            "testing_period_end", "evaluators", "approver", "general_notes",
            "known_dependencies", "status", "published_at", "catalog_hash", "revision")},
        "criteria": rows,
        "totals": _totals(rows),
    }


def _sortkey(num: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in num.split("."))


def _totals(rows: list[dict]) -> dict:
    """Counts only — never a percentage or a score.

    ADR 0016/0023's rule, which api/accessibility_status.py states as "counts only, never a
    percentage of an invented denominator". A conformance report with a "87% compliant" figure on
    it is the exact thing PRD §4.4 forbids: optimizing for a misleading compliance score instead
    of making limitations visible.
    """
    out = {"total": len(rows), "undecided": sum(1 for r in rows if not r["decided"])}
    for status in sorted(FINAL_STATUSES):
        out[status] = sum(1 for r in rows if r["conformance_level"] == status)
    return out


def to_json(projection: dict) -> str:
    return json.dumps(projection, indent=2, ensure_ascii=False)


def to_html(projection: dict) -> str:
    """An accessible HTML rendering of the projection.

    Accessible on purpose, even though it is a preview and not the deliverable: PRD §16 requires
    the exported report to be accessible, and a preview of an accessibility report that is itself
    inaccessible is the kind of thing that ships. Real <th scope>, a <caption>, a declared lang,
    a document title, and no colour-only communication — the conformance level is always the
    cell's text, never a swatch.
    """
    e = html.escape
    rep = projection["report"]
    tmpl = projection["template"]
    title = rep.get("report_title") or "Accessibility Conformance Report (draft)"

    meta_rows = "".join(
        f'<tr><th scope="row">{e(k.replace("_", " ").title())}</th><td>{e(str(v))}</td></tr>'
        for k, v in rep.items() if v)

    body_rows = ""
    for r in projection["criteria"]:
        draft = ""
        if not r["decided"] and r["draft_status"]:
            draft = (f"<br><span class='draft'>ACP draft suggestion (not a decision): "
                     f"{e(r['draft_status'])}</span>")
        stale = ""
        if r["evidence_stale"]:
            stale = (f"<br><span class='stale'>{r['evidence_stale']} stale evidence record(s), "
                     f"retained for audit history</span>")
        body_rows += (
            f'<tr><th scope="row">{e(r["criterion_num"])} {e(r["criterion_name"] or "")}</th>'
            f"<td>{e(r['level'] or '')}</td>"
            f"<td>{e(r['conformance_level'])}{draft}</td>"
            f"<td>{e(r['remarks'])}{stale}</td></tr>")

    t = projection["totals"]
    totals = ", ".join(f"{e(k)}: {v}" for k, v in t.items())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{e(title)} — structural preview</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem; color: #1a1a1a; background: #fff; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
  th, td {{ border: 1px solid #767676; padding: .5rem .6rem; text-align: left;
            vertical-align: top; }}
  caption {{ text-align: left; font-weight: 700; padding-bottom: .5rem; }}
  .notice {{ border: 2px solid #767676; padding: .75rem 1rem; margin-bottom: 1.5rem; }}
  .draft, .stale {{ font-size: .875rem; color: #595959; }}
</style>
</head>
<body>
<h1>{e(title)}</h1>
<p class="notice"><strong>Draft structural preview.</strong> {e(tmpl['note'])}</p>
<table>
  <caption>Report information</caption>
  <tbody>{meta_rows}</tbody>
</table>
<table>
  <caption>WCAG {e(str(rep.get('wcag_version') or '2.2'))} Report — {e(totals)}</caption>
  <thead>
    <tr><th scope="col">Criteria</th><th scope="col">Level</th>
        <th scope="col">Conformance Level</th><th scope="col">Remarks and Explanations</th></tr>
  </thead>
  <tbody>{body_rows}</tbody>
</table>
</body>
</html>
"""
