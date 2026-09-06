"""Draft structural export preview (PRD §15 publication review, §16 without the ITI template).

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
----------------------------------------------
PRD §16 requires the exported ACR to be built on the official ITI VPAT® 2.5Rev template. That is
Phase 5, and it is gated on a decision that has not been made: vendoring a third-party template
into this repo carries the VPAT® trademark's usage terms, and this codebase's precedent for
vendoring a third-party artifact is that it gets its own ADR first — ADR 0053, which frames the
question and deliberately does not answer it. (This comment used to cite ADR 0029 as the
precedent. It is not one: 0029 has no licensing or trademark reasoning in it at all.)

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

import acr_catalog
from acr_catalog import (FINAL_STATUSES, REQ_EN_301_549, REQ_SECTION_508, REQ_WCAG,
                         WORKFLOW_STATES)

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

    def _row(c: dict) -> dict:
        crit_ev = ev.get(c["criterion_num"], [])
        live = [e for e in crit_ev if getattr(e, "id", None) not in stale]
        return {
            "criterion_num": c["criterion_num"],
            "criterion_name": c.get("criterion_name"),
            "level": c.get("level"),
            "principle": c.get("principle"),
            "guideline": c.get("guideline"),
            "requirement_set": c.get("requirement_set") or REQ_WCAG,
            "chapter": c.get("chapter"),
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
        }

    # A row with no requirement_set is a WCAG row: every matrix built before Phase 6 was WCAG-only,
    # because build_matrix could read no other catalog. Defaulting rather than raising keeps a
    # report published then readable now, which PRD §17 requires of anything already issued.
    wcag = [c for c in criteria if (c.get("requirement_set") or REQ_WCAG) == REQ_WCAG]
    five_oh_eight = [c for c in criteria if c.get("requirement_set") == REQ_SECTION_508]
    european = [c for c in criteria if c.get("requirement_set") == REQ_EN_301_549]

    rows = [_row(c) for c in sorted(wcag, key=lambda r: (_PRINCIPLE_ORDER.get(r.get("principle"), 9),
                                                         _sortkey(r["criterion_num"])))]
    section_508 = _section_508(
        [_row(c) for c in sorted(five_oh_eight, key=lambda r: _sortkey(r["criterion_num"]))])
    en_301_549 = _en_301_549(
        [_row(c) for c in sorted(european, key=lambda r: _sortkey(r["criterion_num"]))])

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
        # Present only when the report actually carries Section 508 rows, so a WCAG report's
        # projection is byte-identical to what it was before Phase 6 and a renderer written
        # against it cannot accidentally print an empty "Revised Section 508 Report" heading.
        **({"section_508": section_508} if section_508 else {}),
        **({"en_301_549": en_301_549} if en_301_549 else {}),
        # Over EVERY row the report contains, not just the WCAG table's. Identical to the old
        # value for a WCAG-only report; for a 508 report, a total that counted 55 of 175 rows
        # would be the understatement PRD §4.4 exists to prevent.
        "totals": _totals(rows + [r for section in (section_508, en_301_549) if section
                                  for ch in section["chapters"] for r in ch["rows"]]),
    }


def _grouped_section(rows: list[dict], *, citation: str, names: dict, label: str) -> dict | None:
    """Rows grouped into the divisions their standard is organised by, or nothing at all.

    ONE IMPLEMENTATION, TWO STANDARDS. Section 508 prints Chapters 3-6 as separate tables and
    EN 301 549 prints Clauses 4-13 the same way; the only differences are what the division is
    called and where its names come from. Two copies of this would be two places for the honesty
    checks to drift apart, and the rows on both sides carry the same shape by construction —
    `acr_catalog._blank_row` builds them.

    Division NAMES come from the catalog; a row stores its NUMBER, which is the durable half. A
    division the catalog does not name still renders, under `label` and its number, rather than
    vanishing — a requirement must never disappear from a conformance report because a heading is
    missing.

    Grouped rather than left flat because the divisions ARE the document's structure. A flat list
    would have to be regrouped identically by the HTML renderer, the Word renderer and the PDF
    path, which is three chances to disagree about what the document contains.
    """
    if not rows:
        return None
    groups: list[dict] = []
    for num in sorted({r["chapter"] for r in rows if r["chapter"]}, key=_division_sortkey):
        in_group = [r for r in rows if r["chapter"] == num]
        groups.append({
            "num": num,
            "name": names.get(num) or f"{label} {num}",
            "label": label,
            "rows": in_group,
            "totals": _totals(in_group),
        })
    return {"citation": citation, "chapters": groups, "totals": _totals(rows)}


def _division_sortkey(num: str) -> tuple:
    """Numeric where the division is a number, which both standards' are. Falls back to the string
    so an unexpected value sorts predictably instead of raising in the middle of an export."""
    try:
        return (0, int(num), "")
    except (TypeError, ValueError):
        return (1, 0, str(num))


def _catalog_division_names(meta_fn, key: str) -> dict:
    """`{number: name}` from a catalog's own metadata, or empty when it cannot be read.

    Empty is a working answer, not a failure: `_grouped_section` falls back to the number, so a
    deployment whose catalog is absent still exports every row it holds.
    """
    try:
        return {k: v.get("name") for k, v in (meta_fn() or {}).get(key, {}).items()}
    except (FileNotFoundError, KeyError, ValueError, AttributeError):  # pragma: no cover
        return {}


def _section_508(rows: list[dict]) -> dict | None:
    return _grouped_section(
        rows,
        citation="36 CFR Part 1194, Appendix C (Revised Section 508 Standards)",
        names=_catalog_division_names(acr_catalog.section_508_meta, "chapters"),
        label="Chapter")


def _en_301_549(rows: list[dict]) -> dict | None:
    """The EU report. Nothing renders unless the rows are there, and they are not yet —
    `config/en-301-549.json` is committed empty while its reproduction question is open, so this
    returns None in every deployment today. It is written now so that the day the requirements
    land, the edition opens by adding one member to `acr_catalog._RENDERABLE` rather than by
    writing a renderer under time pressure."""
    return _grouped_section(
        rows,
        citation=(f"{acr_catalog.en_301_549_meta().get('citation') or 'EN 301 549'} "
                  f"({acr_catalog.en_301_549_meta().get('publisher') or 'CEN, CENELEC and ETSI'})"),
        names=_catalog_division_names(acr_catalog.en_301_549_meta, "clauses"),
        label="Clause")


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
    section_508 = _section_508_html(projection, e)
    en_301_549 = _requirement_section_html(
        projection.get("en_301_549"), "EN 301 549 Report", e)

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
{section_508}{en_301_549}</body>
</html>
"""


def _section_508_html(projection: dict, e) -> str:
    return _requirement_section_html(
        projection.get("section_508"), "Revised Section 508 Report", e)


def _requirement_section_html(section: dict | None, heading: str, e) -> str:
    """A standard's report — one table per division, or nothing at all.

    No Level column: neither a Section 508 requirement nor an EN 301 549 clause has a WCAG
    conformance level, and an empty column under that heading would read as an omission rather
    than as a category error. The divisions are separate tables, each with its own <caption>,
    because that is how each standard is organised and because a 200-row single table is unusable
    with a screen reader.

    One function for both standards, for the reason `_grouped_section` gives: two copies are two
    places for the honesty checks — the undecided cell, the labelled draft suggestion, the stale
    evidence note — to drift apart.
    """
    if not section:
        return ""
    out = [f'<h2>{e(heading)}</h2>\n'
           f'<p>Requirements from {e(section["citation"])}. '
           f'{e(", ".join(f"{k}: {v}" for k, v in section["totals"].items()))}</p>\n']
    for chapter in section["chapters"]:
        body = ""
        for r in chapter["rows"]:
            draft = ""
            if not r["decided"] and r["draft_status"]:
                draft = (f"<br><span class='draft'>ACP draft suggestion (not a decision): "
                         f"{e(r['draft_status'])}</span>")
            stale = ""
            if r["evidence_stale"]:
                stale = (f"<br><span class='stale'>{r['evidence_stale']} stale evidence record(s), "
                         f"retained for audit history</span>")
            body += (f'<tr><th scope="row">{e(r["criterion_num"])} '
                     f'{e(r["criterion_name"] or "")}</th>'
                     f"<td>{e(r['conformance_level'])}{draft}</td>"
                     f"<td>{e(r['remarks'])}{stale}</td></tr>")
        counts = ", ".join(f"{k}: {v}" for k, v in chapter["totals"].items())
        out.append(
            f'<table>\n  <caption>{e(chapter.get("label") or "Chapter")} {e(chapter["num"])}: '
            f'{e(chapter["name"])} — {e(counts)}</caption>\n'
            f'  <thead>\n    <tr><th scope="col">Criteria</th>'
            f'<th scope="col">Conformance Level</th>'
            f'<th scope="col">Remarks and Explanations</th></tr>\n  </thead>\n'
            f'  <tbody>{body}</tbody>\n</table>\n')
    return "".join(out)
