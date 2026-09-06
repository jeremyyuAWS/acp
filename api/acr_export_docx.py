"""The ACR as a Word document — Phase 5 groundwork, without the ITI template (PRD §16).

WHAT THIS IS AND, EMPHATICALLY, WHAT IT IS NOT
-----------------------------------------------
PRD §16 requires the exported ACR to be built on the official ITI VPAT® 2.5Rev template. That
template is not here and cannot be until a licensing decision is made — vendoring a third-party
artifact under the VPAT® trademark's usage terms is a decision this repo makes in an ADR first
(see ADR 0053 — NOT ADR 0029, which this comment used to cite and which contains no licensing
reasoning). So this module renders the report's CONTENT into an
accessible .docx with the VPAT table's shape, and says on its own first page that it is not a
VPAT. When the template lands, the renderer below is what gets replaced; the projection it
consumes does not change.

Building it now rather than after the decision is the point. Everything that is hard about a Word
export — a real heading outline, a header row that repeats across pages, a declared document
language, a title in the document properties rather than only in the body — is orthogonal to which
template the tables sit in, and every one of those is a thing that ships broken when it is written
in a hurry against a deadline that starts the day the licence clears.

ONE PROJECTION, FOUR RENDERERS
-------------------------------
This consumes `acr_export_preview.project()`, exactly as the JSON, HTML and PDF exports do. It
does not read criteria rows, evidence or the store. Every honesty constraint therefore lives once,
in acr_export_preview: no workflow state in the conformance column, no draft status presented as a
decision, no criterion omitted for being inconvenient. A renderer that built its own table from
the records could drift from the one a reviewer approved, and the drift would be invisible.

THE GATE IS "NO FAIL", AND THAT IS NOT A LOWERED BAR — IT IS THE ONLY HONEST ONE
---------------------------------------------------------------------------------
PRD §16 also requires the generated document to pass ACP's own accessibility checks. Measured on
this repo: **no docx registration declares `Coverage.FULL`** (10 registrations, all `partial` or
`heuristic`), and `assessment.CAN_CERTIFY_PASS` is `frozenset({Coverage.FULL})`. `PASS` is
therefore unreachable by construction, and an "all PASS" gate would never go green no matter how
good the document was. `check()` below implements the honest alternative the PRD settles on: no
FAIL, with every REVIEW returned for a human to sign off rather than swallowed.

BOTH ANALYSER PATHS, because one of them is the one that matters
------------------------------------------------------------------
ACP judges a .docx through two paths, and they cover different criteria:

  · `rule_registry` — 10 rules (1.1.1, 1.3.5, 1.4.1, 1.4.10-12, 2.1.2, 2.4.4, 3.1.2, 4.1.2),
    reached only after `import formats.docx`, because registration is lazy;
  · `assessment_policy.RULE_FORMATS` — 14 more (1.3.1, 1.3.2, 1.3.3, 1.4.3, 1.4.5, 1.4.8, 1.4.9,
    2.4.2, 2.4.6, 2.4.9, 2.4.10, 3.1.1, 3.1.5, 3.3.2), served by
    `office_structure.docx_checks`.

The PRD's Phase 5 note names `rule_registry.evaluate` alone. Running only that would skip heading
structure, document title and document language — which are precisely the checks an accessible
Word document exists to satisfy, and precisely the ones this renderer is most able to get wrong.
`check()` runs `office_structure.docx_checks`, which is the path covering them.
"""
from __future__ import annotations

import io
from pathlib import Path

import acr_export_preview

# Stated in the document, not only here. A .docx of a conformance report is the single most
# likely artifact in this product to be mistaken for a VPAT, because that is the format a real
# VPAT arrives in — so the disclaimer is louder in this renderer than in the others.
NOT_A_VPAT = (
    "This document is not a VPAT®. It presents ACP's conformance evaluation in the shape of the "
    "VPAT table — the same rows, the same column meanings, the same four conformance terms — but "
    "it is not built on the official ITI VPAT® template and must not be submitted as one."
)

# The docx counterpart of acr_export_pdf.UNRUN_GATES. Worded separately ON PURPOSE: that notice
# cites veraPDF and PDF/UA-1, neither of which says anything whatsoever about a Word file, and
# copying it here would be a conformance claim about a format it was never measured on.
UNRUN_GATES = (
    "Accessibility validation of this document is automated only. It is checked against ACP's own "
    "Word-document analyser, which reports no failures. That analyser declares partial coverage of "
    "every criterion it examines and full coverage of none, so a clean result means nothing it "
    "looks for was found — not that the document is accessible. No screen-reader pass (NVDA or "
    "VoiceOver) and no Microsoft Accessibility Checker pass has been run against it. Automated "
    "validation is necessary and not sufficient."
)

DOCUMENT_LANGUAGE = "en-US"

MISSING_RENDERER = (
    "the Word renderer is unavailable — python-docx is not importable in this deployment, so the "
    "ACR cannot be exported as a .docx. Install `python-docx` (api/requirements.txt); the JSON, "
    "HTML and PDF exports are unaffected."
)


class RendererUnavailable(RuntimeError):
    """Raised when python-docx cannot be imported. Never a fallback to an untagged document."""


def is_available() -> bool:
    """True when a .docx can actually be produced here.

    Import-only, like `acr_export_pdf.is_available()`: a caller deciding whether to offer a
    download needs the answer before rendering a whole report to find out.
    """
    try:
        import docx  # noqa: F401
        return True
    except Exception:
        return False


def _set_document_language(document, language: str = DOCUMENT_LANGUAGE) -> None:
    """Declare the language on the Normal style, which every run inherits.

    3.1.1. A screen reader with no declared language reads the document in whatever voice it
    happens to be set to, which turns an English conformance report into noise for a user whose
    synthesiser is configured for another language. python-docx has no API for this, so it is set
    on the style's rPr directly — the same place Word writes it.

    WORTH KNOWING BEFORE TESTING THIS: python-docx's default template ALREADY ships
    `<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/>` in styles.xml. So a test that only
    asserts "w:lang and en-US appear in styles.xml" passes whether or not this function is ever
    called — it is measuring the template. `test_the_document_declares_its_language` renders in a
    non-default language for exactly that reason; asserting the default is how this shipped
    untested in the first draft.

    `w:bidi` is deliberately left alone. It selects the right-to-left language, not the document's,
    and setting it to `en-US` would be a meaningless value in a slot Word gives a real one.

    BOTH PLACES, and the second is the one that was missed. Setting only the Normal style leaves
    `w:docDefaults/w:rPrDefault` still declaring the template's `en-US`, so the file answers the
    question twice with different values — Word resolves to the style and a checker reading
    docDefaults sees the stale one. Measured: rendering in `fr-CA` produced a styles.xml
    containing both `w:val="en-US"` and `w:val="fr-CA"`.
    """
    from docx.oxml.ns import qn

    targets = [document.styles["Normal"].element.get_or_add_rPr()]

    styles_root = document.styles.element
    doc_defaults = styles_root.find(qn("w:docDefaults"))
    if doc_defaults is not None:
        rpr_default = doc_defaults.find(qn("w:rPrDefault"))
        if rpr_default is not None:
            default_rpr = rpr_default.find(qn("w:rPr"))
            if default_rpr is None:
                default_rpr = rpr_default.makeelement(qn("w:rPr"), {})
                rpr_default.append(default_rpr)
            targets.append(default_rpr)

    for rpr in targets:
        for existing in rpr.findall(qn("w:lang")):
            rpr.remove(existing)
        lang = rpr.makeelement(qn("w:lang"), {})
        lang.set(qn("w:val"), language)
        lang.set(qn("w:eastAsia"), language)
        rpr.append(lang)


def _repeat_header_row(row) -> None:
    """Mark a table row as a header that repeats on every page (`<w:tblHeader/>`).

    1.3.1, and the reason a 55-row conformance table is readable at all. Without it the column
    meanings appear on page one only, and a reader on page four is holding four headings in their
    head — the same defect `acr_export_pdf`'s `thead { display: table-header-group }` fixes for
    the PDF. python-docx exposes no API for it either.
    """
    from docx.oxml.ns import qn

    trpr = row._tr.get_or_add_trPr()
    header = trpr.makeelement(qn("w:tblHeader"), {})
    trpr.append(header)


# What a holder of the published Word document needs in order to check it themselves, and the
# sentence that stops the digest being read as something it is not. Kept in step with
# `acr_export_pdf.DIGEST_IS_NOT_A_SIGNATURE` deliberately: the two documents make the same claim
# about the same digest, and a reader comparing a PDF and a Word file of one revision must not
# find them saying different things about it.
DIGEST_IS_NOT_A_SIGNATURE = (
    "This digest is a SHA-256 over the published snapshot's contents. It is recomputable by "
    "anyone holding the same snapshot, which makes an alteration detectable. It is not a digital "
    "signature: it carries no key and identifies no signer, so it establishes what the content is "
    "and never who produced it."
)


def render(projection: dict, *, language: str = DOCUMENT_LANGUAGE,
           provenance: dict | None = None) -> bytes:
    """One accessible .docx from the same projection every other export renders.

    Deliberately plain. There is no colour anywhere in this document: the conformance level is
    the cell's text and nothing else carries meaning (1.4.1), which is also why the table needs no
    legend and survives being printed in black and white.

    `provenance`, when given, is a published revision's `{revision, digest, published_at,
    published_by, verified}` — see `render_published`. It is a parameter rather than a second
    renderer for the reason `acr_export_pdf.published_html` exists: two call sites assembling the
    same document differently is how one of them ends up missing a disclosure.
    """
    try:
        from docx import Document
        from docx.shared import Pt
    except Exception as exc:                                # pragma: no cover - env-dependent
        raise RendererUnavailable(MISSING_RENDERER) from exc

    report = projection["report"]
    title = report.get("report_title") or "Accessibility Conformance Report"

    document = Document()
    _set_document_language(document, language)

    # 2.4.2 — the document's title in its PROPERTIES, not only as text on page one. A screen
    # reader and a file browser both announce this; a heading in the body is not a substitute.
    document.core_properties.title = title
    document.core_properties.language = language

    document.add_heading(title, level=1)

    document.add_paragraph(NOT_A_VPAT)
    document.add_paragraph(UNRUN_GATES)

    if provenance:
        # After the two caveats and before the tables, so a reader who stops on page one has seen
        # what has not been validated AND which frozen record this is. The digest is printed in
        # full: a truncated one cannot be recomputed and compared, which is the only thing it is
        # for.
        checked = ("verified against its contents when this document was produced"
                   if provenance.get("verified")
                   else "NOT verified — this document was produced without checking the digest")
        document.add_paragraph(
            f"Published revision {provenance.get('revision')}. "
            f"Published {provenance.get('published_at') or 'unknown'} "
            f"by {provenance.get('published_by') or 'unknown'}. "
            f"This is an immutable published record and is not the current draft. "
            f"Content digest (SHA-256): {provenance.get('digest') or ''}, {checked}. "
            f"{DIGEST_IS_NOT_A_SIGNATURE}")

    document.add_heading("Report information", level=2)
    meta = [(k.replace("_", " ").title(), str(v)) for k, v in report.items() if v]
    if meta:
        meta_table = document.add_table(rows=1, cols=2)
        meta_table.style = "Table Grid"
        head = meta_table.rows[0]
        head.cells[0].text = "Field"
        head.cells[1].text = "Value"
        _repeat_header_row(head)
        for name, value in meta:
            row = meta_table.add_row()
            row.cells[0].text = name
            row.cells[1].text = value

    wcag_version = str(report.get("wcag_version") or "2.2")
    document.add_heading(f"WCAG {wcag_version} Report", level=2)

    totals = ", ".join(f"{k}: {v}" for k, v in projection["totals"].items())
    # Counts, never a percentage — ADR 0016/0023 and PRD §4.4. A "% compliant" figure on a
    # conformance report is the exact thing the feature exists not to produce.
    document.add_paragraph(totals)

    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    header = table.rows[0]
    for index, label in enumerate(
            ("Criteria", "Level", "Conformance Level", "Remarks and Explanations")):
        header.cells[index].text = label
    _repeat_header_row(header)

    for crit in projection["criteria"]:
        row = table.add_row()
        row.cells[0].text = f"{crit['criterion_num']} {crit.get('criterion_name') or ''}".strip()
        row.cells[1].text = crit.get("level") or ""
        cell = crit["conformance_level"]
        if not crit["decided"] and crit.get("draft_status"):
            # Labelled, and never in the conformance column on its own — PRD §19 forbids a draft
            # suggestion being presented as a decision.
            cell = (f"{cell}\nACP draft suggestion (not a decision): {crit['draft_status']}")
        row.cells[2].text = cell
        remarks = crit.get("remarks") or ""
        if crit.get("evidence_stale"):
            remarks = (f"{remarks}\n{crit['evidence_stale']} stale evidence record(s), retained "
                       f"for audit history").strip()
        row.cells[3].text = remarks

    _add_requirement_section(document, projection.get("section_508"),
                             "Revised Section 508 Report")
    _add_requirement_section(document, projection.get("en_301_549"), "EN 301 549 Report")

    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            if run.font.size is None:
                run.font.size = Pt(11)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_requirement_section(document, section: dict | None, heading: str) -> None:
    """A standard's report — one table per division, or nothing at all.

    Three columns, not four: neither a Section 508 requirement nor an EN 301 549 clause has a WCAG
    level, and an empty Level column would read as a missing value rather than as a category that
    does not apply. Each division is its own table with its own heading, matching how the standard
    is organised and how a screen-reader user navigates a long Word document — by heading, not by
    scrolling one 120-row table.

    One function for both standards. The accessibility gate in `check()` runs over whatever this
    produces, unchanged: heading structure, table header rows and repeat-header are the very things
    it inspects, so a second copy of this would be a second chance to emit a table it fails on.
    """
    if not section:
        return

    document.add_heading(heading, level=2)
    document.add_paragraph(f"Requirements from {section['citation']}.")
    document.add_paragraph(", ".join(f"{k}: {v}" for k, v in section["totals"].items()))

    for chapter in section["chapters"]:
        label = chapter.get("label") or "Chapter"
        document.add_heading(f"{label} {chapter['num']}: {chapter['name']}", level=3)
        document.add_paragraph(", ".join(f"{k}: {v}" for k, v in chapter["totals"].items()))
        table = document.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        header = table.rows[0]
        for index, label in enumerate(
                ("Criteria", "Conformance Level", "Remarks and Explanations")):
            header.cells[index].text = label
        _repeat_header_row(header)

        for req in chapter["rows"]:
            row = table.add_row()
            row.cells[0].text = f"{req['criterion_num']} {req.get('criterion_name') or ''}".strip()
            cell = req["conformance_level"]
            if not req["decided"] and req.get("draft_status"):
                cell = f"{cell}\nACP draft suggestion (not a decision): {req['draft_status']}"
            row.cells[1].text = cell
            remarks = req.get("remarks") or ""
            if req.get("evidence_stale"):
                remarks = (f"{remarks}\n{req['evidence_stale']} stale evidence record(s), retained "
                           f"for audit history").strip()
            row.cells[2].text = remarks


def check(docx_bytes: bytes, *, tmp_dir: Path | None = None) -> dict:
    """Run ACP's own Word analyser over a rendered document. PRD §16's export gate.

    Returns `{"ok": bool, "failures": [...], "reviews": [...]}`.

    `ok` is **no FAIL**, not "all PASS", and the module docstring explains why that is the only
    reachable bar: no docx registration declares `Coverage.FULL`, so `PASS` cannot be produced for
    any Word document by any analyser in this repo. Calling that a lowered standard gets it exactly
    backwards — an "all PASS" gate would be one that can never go green, which is a gate nobody
    can act on and everybody eventually disables.

    REVIEW findings are RETURNED rather than counted as failures, because that is what they are: a
    human has to look. Swallowing them would turn "ACP found nothing it can decide" into "ACP
    approved it", which is the shape PRD §4.4 forbids.

    IT CLEANS UP AFTER ITSELF. The first version of this fell back to `tempfile.mkdtemp()` with no
    cleanup, so every caller that did not pass `tmp_dir` leaked one directory and one .docx per
    call — and the export route is a caller that runs on every download. #1499 had to wrap the
    call site in a `TemporaryDirectory` to contain it, which is the tell: a function whose callers
    must remember to clean up after it has put the obligation in the wrong place. `tmp_dir` stays
    for the tests that want to inspect what was written.
    """
    if tmp_dir is not None:
        return _check_in(docx_bytes, Path(tmp_dir))

    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        return _check_in(docx_bytes, Path(scratch))


def _unreadable_reason(path: Path) -> str | None:
    """Why this file is not a Word document ACP can inspect, or None when it is one.

    THE HOLE THIS CLOSES. `office_structure.docx_checks` catches every exception, logs it through
    `swallowed()`, and returns the findings it had accumulated — which for a file it could not open
    is none at all. `_check_in` then read "no findings" as "no failures" and the gate answered
    ok=True. So the one document state the export gate must never wave through — one nobody can
    open — was the state it was least able to see.

    Measured on 2026-09-06 before the fix, with `check(b"PK\\x03\\x04 not a docx at all")`:

        BadZipFile logged by swallowed(), findings == [], ok == True

    Two conditions, and both are needed. A file that is not a zip fails the first. A file that IS a
    zip — which `PK\\x03\\x04` alone is enough to start looking like — but carries no
    `word/document.xml` fails the second, and that is the shape a truncated or half-written render
    takes. `docx_checks` itself returns `[]` early for exactly that second case, so it too reads as
    a pass.
    """
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            if "word/document.xml" not in zf.namelist():
                return ("the file is a zip archive but carries no word/document.xml, so it is not "
                        "a Word document")
    except zipfile.BadZipFile:
        return "the file is not a valid Word document (it is not a readable zip archive)"
    except OSError as exc:                                   # pragma: no cover — unreadable path
        return f"the file could not be read: {exc}"
    return None


def _check_in(docx_bytes: bytes, directory: Path) -> dict:
    """The analyser pass itself, against a directory whose lifetime the caller owns."""
    import office_structure

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "acr-export.docx"
    path.write_bytes(docx_bytes)

    unreadable = _unreadable_reason(path)
    if unreadable:
        # A FAILURE, not an empty pass. The route refuses to serve a document that fails this gate,
        # and a document nobody can open is the clearest case there is for refusing — PRD §16 asks
        # whether the export is accessible, and an unopenable file answers no.
        return {"ok": False,
                "failures": [{"ruleId": "acr.export.unreadable", "severity": "FAIL",
                              "wcag": "", "detail": unreadable}],
                "reviews": []}

    findings = office_structure.docx_checks(path) or []
    failures = [f for f in findings if str(f.get("severity", "")).upper() != "REVIEW"]
    reviews = [f for f in findings if str(f.get("severity", "")).upper() == "REVIEW"]
    return {"ok": not failures, "failures": failures, "reviews": reviews}


def render_published(projection: dict, *, revision, digest: str, published_at, published_by,
                     verified: bool, language: str = DOCUMENT_LANGUAGE) -> bytes:
    """A published revision as a Word document, carrying its provenance.

    The counterpart of `acr_export_pdf.render_published`, and it exists for the same reason that
    one does: a customer sent "the published ACR" must receive the frozen record, not whatever the
    draft says today. Without this, a report could be sent as a published PDF but only ever as a
    draft .docx — an asymmetry nobody would notice until the two documents disagreed.
    """
    return render(projection, language=language, provenance={
        "revision": revision, "digest": digest, "published_at": published_at,
        "published_by": published_by, "verified": verified})


def filename_for(report: dict) -> str:
    """A download name a person can find again, matching `acr_export_pdf.filename_for`'s rules.

    BOTH SPELLINGS OF THE ID, for the reason that module records: the store row calls it `id` and
    the projection calls it `report_id`, and reading only one is how every report in the system
    downloaded under a single name.
    """
    rid = str(report.get("id") or report.get("report_id") or "report").strip() or "report"
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in rid)
    rev = report.get("revision")
    suffix = f"-rev{rev}" if rev else ""
    return f"acr-{safe}{suffix}.docx"
