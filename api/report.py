"""Branded PDF conformance report (reportlab) — the exportable audit evidence.

Renders a scan run as a designed, chart-led report: logo header, outcome
decision, plain-language verdict, outcome summary band, scope & methodology,
scope of assertion, compliance velocity, status donut + severity split, remediation
outcomes, open findings by criterion, the decisions snapshot (time-travel), the
per-document file inventory, and the per-issue remediation evidence appendix.
Reproducible from the stamped rubric hash. Footer carries page numbers and the
generation stamp on every page.

Two sections exist to stop the report over-claiming, and should not be weakened:

* `_scope_section` — the negative assurance. This platform validates a SUBSET of
  WCAG 2.1 AA, and for each document only the criteria with a validator for that
  file format are evaluated at all. A 100/100 score means "no blocking findings
  among the criteria evaluated", never "fully conformant". The section names what
  was not evaluated.
* `_content_digest` — a recomputable SHA-256 of the stored scan result. It is a
  DIGEST, not a digital signature: no key, no non-repudiation. Never relabel it.

Honesty rule enforced here: a finding is only counted as "open" (blocking) when
its document is NOT certifiable. Findings on a certifiable document were either
remediated (the file carries remediated_at) or are non-blocking below the target
threshold — either way they are reported separately, never mixed into the
"where failures concentrate" view. That keeps a 100%-certifiable estate from
also appearing to have open critical findings.

The evidence appendix (`_evidence_section`) is the audit artifact: for every
finding it shows before → after, the concrete value the AI wrote and why, the
image thumbnail, and the human sign-off. It keeps two lists strictly apart —
fixes that VERIFIABLY cleared the post-fix re-scan, and AI proposals still
awaiting approval, which are never presented as remediated. That separation is
the report's core honesty guarantee.
"""
from __future__ import annotations
import hashlib
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

_LOG = logging.getLogger(__name__)

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (HRFlowable, Image, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

import human_categories as _hc

PLUM = colors.HexColor("#46303F")
AMBER = colors.HexColor("#854F0B")
GREEN = colors.HexColor("#3B6D11")
RED = colors.HexColor("#A32D2D")
BLUE = colors.HexColor("#1F5FA8")
MUTED = colors.HexColor("#6c6470")
LINE = colors.HexColor("#e0dbe4")
ZEBRA = colors.HexColor("#faf8fb")
CARD = colors.HexColor("#f6f3f7")
GREY = colors.HexColor("#9a948f")
GREENBG = colors.HexColor("#eef5e4")

LOGO = Path(__file__).resolve().parent / "assets" / "mova-logo.png"

# The language of the REPORT's own prose, which is authored in English here — not the language
# of the documents it reports on. A scan of a Spanish estate still produces an English report,
# so this is a property of this module's strings and moves only when they are translated.
REPORT_LANG = "en-US"
REPORT_SCHEMA_VERSION = "1"

# SC id → (display name, WCAG level, one-line plain-language description). Drives the
# criteria table and keeps the report self-explanatory for a non-specialist reader.
WCAG_META = {
    "SC_1_1_1": ("1.1.1 Non-text Content", "A", "Images, charts and controls need a text alternative."),
    "SC_1_2_2": ("1.2.2 Captions (Prerecorded)", "A", "Prerecorded video needs synchronized captions."),
    "SC_1_3_1": ("1.3.1 Info & Relationships", "A", "Structure — headings, lists, tables — must be programmatically conveyed."),
    "SC_1_3_2": ("1.3.2 Meaningful Sequence", "A", "Content must expose a correct reading order."),
    "SC_1_4_3": ("1.4.3 Contrast (Minimum)", "AA", "Text must meet a 4.5:1 contrast ratio (3:1 for large text)."),
    "SC_2_2_2": ("2.2.2 Pause, Stop, Hide", "A", "Moving or auto-updating content must be pausable."),
    "SC_2_4_2": ("2.4.2 Page Titled", "A", "Each document needs a descriptive title."),
    "SC_2_4_4": ("2.4.4 Link Purpose (In Context)", "A", "Link text must convey its destination."),
    "SC_2_4_6": ("2.4.6 Headings & Labels", "AA", "Headings and labels must describe topic or purpose."),
    "SC_3_1_1": ("3.1.1 Language of Page", "A", "The document's language must be set."),
    "SC_3_1_2": ("3.1.2 Language of Parts", "AA", "Language changes within content must be marked up."),
    "SC_3_3_2": ("3.3.2 Labels or Instructions", "A", "Form fields need labels or instructions."),
    "SC_4_1_2": ("4.1.2 Name, Role, Value", "A", "UI components must expose name, role and value to assistive tech."),
}
# Back-compat alias (older callers/tests referenced CRIT for the name lookup).
CRIT = {k: v[0] for k, v in WCAG_META.items()}

# Mirrors frontend/src/docStatus.js NOT_ASSESSED — the same token on both sides so a status can
# never mean one thing in the app and another in the certified PDF.
NOT_ASSESSED = "not-assessed"
VIOLET = colors.HexColor("#3C3489")
STATUS_COLOR = {"certifiable": GREEN, "issues": AMBER, "uncertain": BLUE, "unanalysable": GREY,
                "clean": BLUE, NOT_ASSESSED: VIOLET}
# The KEY is a stored token shared with frontend/src/docStatus.js; the LABEL is what a reader
# sees. Only the label changes here — "certifiable" invited a conformance reading ACP does not
# make, and renaming the key would rewrite the meaning of every historical row to fix a word.
STATUS_LABEL = {"certifiable": "no blocking findings", "issues": "open findings",
                "uncertain": "uncertain", "unanalysable": "could not analyse",
                "clean": "no findings", NOT_ASSESSED: "not assessed"}
SEV_COLOR = {"CRITICAL": RED, "SERIOUS": AMBER, "MODERATE": BLUE, "MINOR": GREY}
SEV_ORDER = ["CRITICAL", "SERIOUS", "MODERATE", "MINOR"]


def _crit_name(c):
    return WCAG_META.get(c, (str(c).replace("SC_", "").replace("_", "."), "", ""))[0]


def _status(f):
    # Mirrors the frontend's statusOf (frontend/src/docStatus.js) so the report and the app
    # always classify a file identically.
    if f["status"] == "error":
        return "unanalysable"
    if f["status"] == "uncertain":
        return "uncertain"
    if f["compliant"]:
        return "certifiable"
    # 'issues' means OPEN FINDINGS; a not-certifiable file with zero findings is not 'issues'.
    if f.get("issues"):
        return "issues"
    # CLEAN IS NEVER INFERRED FROM MISSING DATA. 'clean' asserts this document was opened and
    # failed no rule. A NULL score means nobody scored it (Rubric.assess only returns score=None
    # together with Status.ERROR, handled above), so it cannot support that assertion — and this
    # is a CERTIFICATION document, the worst possible place to print a pass nobody measured.
    return "clean" if f.get("score") is not None else NOT_ASSESSED


def _fmt(f):
    return (f.get("file", "").rsplit(".", 1)[-1].upper() if "." in f.get("file", "") else "DOC")


def _extent(f):
    """A compact physical-size string for the inventory — pages / sheets / KB, whatever
    the scan captured (all optional, so this degrades gracefully to '—')."""
    if f.get("pages"):
        return f"{f['pages']} pp"
    if f.get("sheets"):
        return f"{f['sheets']} sheet" + ("s" if f["sheets"] != 1 else "")
    if f.get("size_kb"):
        return f"{f['size_kb']} KB"
    return "—"


def _footer(canvas, doc):
    # WCAG 2.4.2 Page Titled is two halves, and the report only ever shipped one of them. The
    # docinfo /Title has always been set (build_report's `title=`), but a viewer with
    # DisplayDocTitle unset shows the FILENAME in its window/tab regardless — so the title an
    # assistive technology announces for the certification document was "acp-report-<uuid>.pdf".
    # This is a catalog write, not graphics state, so it is unaffected by the save/restore pair
    # below and idempotent across the pages _footer runs on.
    canvas.setViewerPreference("DisplayDocTitle", "true")
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(0.7 * inch, 0.45 * inch, LETTER[0] - 0.7 * inch, 0.45 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.7 * inch, 0.31 * inch, "mova.io · Accessibility Compliance Platform · confidential")
    canvas.drawRightString(LETTER[0] - 0.7 * inch, 0.31 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _content_digest(run: dict, files: list, meta: dict) -> str:
    """SHA-256 over the canonical scan result — scan id, rubric hash, conformance target, and
    every file's score/compliance/failing criteria. Anyone holding the same scan can recompute
    it and get the same value, which is what makes the report tamper-evident.

    It deliberately EXCLUDES the generation timestamp, so the digest is stable across
    re-exports of the same scan.

    This is a DIGEST, not a signature. There is no signing key and it provides no
    non-repudiation — it proves the report's contents match the stored scan, not who produced
    it. Labelling a bare hash a "digital signature" would over-claim, which is exactly what an
    auditor checks for.
    """
    import hashlib
    import json
    payload = {
        "scan": run.get("id"),
        "rubric_hash": meta.get("hash"),
        "target": meta.get("target"),
        "files": sorted(
            ({"file": f["file"],
              "score": f.get("score"),
              "compliant": int(bool(f.get("compliant"))),
              "failing": sorted({i.get("wcag", "") for i in f.get("issues", [])})}
             for f in files), key=lambda x: x["file"]),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _qr_flowable(data: str, pts: int = 72) -> Image:
    """Render `data` as a QR code and return a reportlab Image flowable.

    Uses segno (pure-Python, no C extension). Falls back to a 1×1 transparent PNG
    so a missing/broken segno install degrades gracefully rather than failing the
    whole report export.
    """
    import io as _io
    try:
        import segno
        buf = _io.BytesIO()
        segno.make(data, error="M").save(buf, kind="png", scale=4, border=2)
        buf.seek(0)
        return Image(buf, width=pts, height=pts)
    except Exception:
        # 1×1 transparent PNG — minimal fallback so the page still builds
        _px = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
               b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
               b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
               b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        return Image(_io.BytesIO(_px), width=pts, height=pts)


def _verify_section(scan_id: str, digest: str, h2, body, note) -> list:
    """R15 — 'Verify this report' block appended at the end of the PDF.

    The QR code encodes a URL when ACP_PUBLIC_URL is configured, or a plain
    `acp://verify/{scan_id}?digest={digest}` URI when it is not (offline / private
    deploy). The note below the QR explains both uses so an auditor knows what to do
    with it without reading the docs.
    """
    el = []
    try:
        import core as _core
        base = _core.PUBLIC_URL
    except Exception:
        base = ""

    if base:
        verify_url = f"{base}/public/verify/{scan_id}"
        qr_label = verify_url
        instruction = (
            f"Scan the QR code or visit <b>{_esc(verify_url)}</b> to fetch the "
            "machine-readable scan record and recompute the digest below independently."
        )
    else:
        verify_url = f"acp://verify/{scan_id}?digest={digest}"
        qr_label = verify_url
        instruction = (
            "No public URL is configured for this deployment. The QR code encodes a "
            f"<b>acp://verify/{_esc(scan_id)}</b> URI — use it with the ACP CLI or "
            "supply ACP_PUBLIC_URL to generate a live link instead."
        )

    el.append(Paragraph("Verify this report", h2))
    qr_img = _qr_flowable(qr_label, pts=80)
    digest_para = Paragraph(
        f"Content digest (SHA-256): <b>{digest}</b><br/>"
        f"Scan ID: <b>{_esc(scan_id)}</b><br/><br/>"
        + instruction,
        note)
    row = Table([[qr_img, digest_para]], colWidths=[1.2 * inch, 5.9 * inch])
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    el.append(row)
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "The digest is a SHA-256 over the canonical scan payload (scan ID, rubric hash, "
        "conformance target, per-file score/compliance/failing criteria). It is stable "
        "across re-exports of the same scan: recompute it from the stored scan and compare "
        "to detect any alteration. This is a tamper-evidence digest, not a digital signature — "
        "there is no signing key and it provides no non-repudiation.", note))
    return el


def _esc(s) -> str:
    """Escape for reportlab's mini-HTML paragraph markup; bound the length."""
    if s is None or s == "":
        return "—"
    escaped = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(escaped) > 2000:
        return escaped[:2000] + "…"
    return escaped


def _finding_id(file: str, criterion: str, location: str = "") -> str:
    """Deterministic 8-char hex ID stable for the same (file, criterion, location) triple.

    Stable across renders, exports, and re-assessments of the same finding. Does not include
    scan_id so the same logical finding in different scans of the same document has the same ID.
    """
    key = f"{file}|{criterion}|{location or ''}".encode()
    return hashlib.sha256(key).hexdigest()[:8]


def _decision_block(run, files, meta, facts, h2, body, muted) -> list:
    """What ACP checked, fixed and verified (R2/R3).

    Answers, before anything else, the question a reader actually has: what was done to these
    documents, and what is still open? Every figure is COUNTED from stored rows; the digest is
    recomputable. The status is deliberately three-valued — an estate with open findings must
    never render as a single green word because most documents came back clear.

    THE VOCABULARY IS NOT "CERTIFIED", DELIBERATELY. ACP does not assert that a document
    conforms to WCAG; it reports what it detected, what it fixed, and what it verified after
    fixing. "Certifiable" invited the opposite reading — that a green word here was a conformance
    claim the reader could rely on — when the section immediately below spends four paragraphs
    saying it is not. The word was fighting its own footnotes.

    So the states describe what the ENGINE knows: no blocking findings among the criteria it
    checked, open findings, or a mix. `_status`'s internal key stays "certifiable" — it is a
    dict key and a stored token, not prose, and renaming it would rewrite the meaning of
    historical rows for no reader's benefit.
    """
    total = len(files)
    cert = sum(1 for f in files if _status(f) == "certifiable")
    if total and cert == total:
        status, colour = "NO BLOCKING FINDINGS", "#3B6D11"
    elif cert == 0:
        status, colour = "OPEN FINDINGS", "#A32D2D"
    else:
        status, colour = "PARTIALLY CLEARED", "#854F0B"

    remediated = (facts or {}).get("remediated_total", 0)
    approvals = (facts or {}).get("approvals_total", 0)
    digest = _content_digest(run, files, meta)

    el = [Paragraph("What ACP checked, fixed and verified", h2)]
    card = Table([[
        # meta['target'] is the full conformance target string (e.g. "WCAG 2.1 AA") — do not
        # prefix it with "WCAG 2.1" or the card reads "WCAG 2.1 · WCAG 2.1 AA".
        Paragraph(f'<font size="15" color="{colour}"><b>{status}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">{_esc(meta.get("target"))}</font>', body),
        Paragraph(f'<font size="15"><b>{cert} of {total}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">with no blocking findings</font>', body),
        Paragraph(f'<font size="15"><b>{remediated}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">fixes verified on re-scan</font>', body),
        Paragraph(f'<font size="15"><b>{approvals}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">human approvals recorded</font>', body),
    ]], colWidths=[1.85 * inch] * 4)
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.75, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ]))
    el.append(card)

    # The plain-language WHY (R3) is the executive verdict rendered just below this card —
    # it already states, from the same real counts, which documents came back clear and why.
    # Repeating it here would be noise; instead, bound what that verdict covers.
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        "<b>“No blocking findings” means no blocking finding among the criteria ACP checked — "
        "listed under ‘What this report covers’ below. It is not a statement that the document "
        "conforms to WCAG.</b>", muted))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        f"Content digest (SHA-256) <b>{digest[:32]}…</b> — recomputable from the stored scan, so "
        "this report is tamper-evident. It is a digest, <b>not a digital signature</b>: there is no "
        "signing key and it asserts nothing about who produced the report.", muted))
    return el


def _scope_section(files, facts, h2, body, cell, muted) -> list:
    """Scope of assertion / negative assurance (backlog R-A).

    The single most important section for an auditor, and the report's guard against its own
    headline number. A 100/100 score means "no blocking findings among the criteria we
    actually evaluated" — NOT "fully WCAG 2.1 AA conformant". Most criteria have no validator
    for most file formats; those are reported as not-evaluated and are never asserted to
    pass — nor asserted to be inapplicable, which is a different claim we do not make. This
    section says so explicitly, and names them.
    """
    if not facts or not facts.get("documents"):
        return []
    scope = facts["scope"]
    docs = facts["documents"]
    el = [Paragraph("What this report covers · and what it does not", h2)]
    el.append(Paragraph(
        f"This platform has an automated validator for <b>{scope['catalog_size']}</b> success criteria. "
        "That is <b>not</b> the full WCAG 2.1 AA criteria set: many criteria require human or "
        "assistive-technology judgement and are routed to review rather than asserted here. For each "
        "document, only the criteria that have a validator <i>for that file format</i> are evaluated — "
        "the remainder are reported as <b>not evaluated</b>: no check was run. That is deliberately "
        "not the same as <i>not applicable</i> — some of these criteria do apply to the format (a "
        "tagged PDF has focus order and name/role/value); we simply do not check them yet. "
        "A zero finding-count on an unevaluated criterion is not a pass.", muted))
    el.append(Spacer(1, 8))

    rows = [["Document", "Evaluated", "Not evaluated", "Deterministic", "AI-assisted", "Human-only"]]
    for d in docs:
        bm = d["by_mode"]
        rows.append([Paragraph(_esc(d["file"]), cell), d["evaluated"], d["not_evaluated"],
                     bm.get("auto", 0), bm.get("ai-assisted", 0), bm.get("human-only", 0)])
    t = Table(rows, colWidths=[2.6 * inch, 0.85 * inch, 0.95 * inch, 0.95 * inch, 0.9 * inch, 0.85 * inch],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    el.append(t)
    el.append(Spacer(1, 8))

    # Criteria we never ran on these formats. Deliberately NOT called "not applicable":
    # some of them do apply (2.4.3 and 4.1.2 apply to a tagged PDF), we just don't check
    # them. This section exists so the omission is stated rather than inferred from silence.
    ne = scope.get("not_evaluated_criteria") or []
    hu = scope.get("human_only_criteria") or []
    el.append(Paragraph("<b>This report makes no assertion about:</b>", body))
    if ne:
        el.append(Paragraph(
            "<b>Not evaluated for these file formats</b> — no check was run; this is not a "
            "statement that the criterion does not apply — " +
            _esc(", ".join(f"{c['sc']} {c['name']}" for c in ne[:18]))
            + (f", and {len(ne) - 18} more." if len(ne) > 18 else "."), muted))
    if hu:
        el.append(Paragraph(
            "<b>Requires human or assistive-technology judgement</b> (routed to review, never "
            "resolved automatically) — " + _esc(", ".join(f"{c['sc']} {c['name']}" for c in hu)) + ".", muted))
    # DOCUMENTS NEVER OPENED, not merely criteria never run.
    #
    # Everything above narrows the assertion by CRITERION. None of it narrows it by DOCUMENT,
    # and the file-type scope excludes whole files from the scan — absent from this report
    # entirely: not failing, not passing, not evaluated, never read. A conformance report that
    # lists the criteria it skipped but not the documents it never saw understates its own
    # boundary in the flattering direction, which is the exact failure the rest of this section
    # exists to prevent. The auditor asking "does this cover the estate?" otherwise gets "yes"
    # from silence.
    unread = scope.get("unread_documents") or 0
    fmts = scope.get("formats_read") or []
    if unread or fmts:
        _fmt_txt = (", ".join(f".{f}" for f in fmts) if fmts else "the selected file types")
        _n = (f"<b>{unread}</b> document{'' if unread == 1 else 's'} of other file types "
              f"{'was' if unread == 1 else 'were'} not read at all"
              if unread else "Documents of other file types were not read at all")
        el.append(Paragraph(
            f"<b>Documents this scan did not open</b> — the scan was scoped to {_esc(_fmt_txt)}, "
            f"so {_n}. They were not downloaded, opened or checked, and this report makes no "
            "statement about them whatsoever — neither conformant nor failing. Anything outside "
            f"{_esc(_fmt_txt)} is outside this assertion.", muted))

    # WHOLE-ESTATE FUNNEL — the widest boundary of all. Everything above narrows within the scanned
    # source; this states how much of the DISCOVERED estate was ever an assessable format. Three
    # counts, never one percentage (estate_inventory's founding rule): discovered ≥ assessable ≥ the
    # documents this report actually covers. Rendered only when the scan recorded an inventory.
    estate = scope.get("estate")
    if estate and estate.get("discovered"):
        floor = "at least " if estate.get("truncated") else ""
        na = estate.get("not_assessable", 0)
        comp = []
        if estate.get("metadata_only"):
            comp.append(f"{estate['metadata_only']} image, audio or video (no accessibility test exists)")
        if estate.get("unsupported"):
            comp.append(f"{estate['unsupported']} of file types ACP does not parse")
        if estate.get("excluded"):
            comp.append(f"{estate['excluded']} excluded as ACP's own output or by policy")
        comp_txt = (" — " + "; ".join(comp)) if comp else ""
        scored = len(docs)
        remediated = (facts or {}).get("remediated_total", 0)
        covers = (f"This report covers the <b>{scored}</b> document{'' if scored == 1 else 's'} "
                  f"actually scored"
                  + (f", <b>{remediated}</b> of which the platform remediated." if remediated else "."))
        el.append(Spacer(1, 4))
        el.append(Paragraph(
            f"<b>Estate coverage</b> — discovery found {floor}<b>{estate['discovered']}</b> "
            f"file{'' if estate['discovered'] == 1 else 's'} in this source. "
            f"<b>{estate['assessable']}</b> {'is' if estate['assessable'] == 1 else 'are'} a file "
            f"type ACP can assess; the remaining <b>{na}</b> {'is' if na == 1 else 'are'} outside any "
            f"automated accessibility assertion{comp_txt}. " + covers + " These are deliberately three "
            "separate denominators, not one percentage: discovered, assessable, and scored are "
            "different questions and collapsing them would overstate the coverage.", muted))

    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "<b>A score of 100 therefore means: no blocking findings among the criteria ACP evaluated "
        "for that document's format.</b> It is a record of what was checked and what was fixed, not "
        "a statement that the document conforms to WCAG 2.1 AA, and it must not be represented as "
        "such.", muted))
    return el


def _pour_bars(principles) -> Drawing:
    """The per-principle pass rate as horizontal bars — the visual twin of the POUR table, on the
    exact same numbers. Only principles with something evaluated get a bar (a 0-evaluated principle
    has no rate to draw, and the table already shows it as '—')."""
    rows = [p for p in principles if p.get("evaluated", 0)]
    h = max(60, 24 * len(rows) + 16)
    d = Drawing(440, h)
    bar_x, bar_w = 118, 232
    y = h - 18
    for p in rows:
        ev, ps = p["evaluated"], p["passed"]
        frac = ps / ev if ev else 0
        d.add(String(0, y + 2, p.get("principle", ""), fontName="Helvetica", fontSize=8.5, fillColor=PLUM))
        d.add(Rect(bar_x, y, bar_w, 10, fillColor=CARD, strokeColor=LINE, strokeWidth=0.5))
        if frac:
            d.add(Rect(bar_x, y, bar_w * frac, 10, fillColor=GREEN, strokeColor=None))
        d.add(String(bar_x + bar_w + 6, y + 2, f"{ps}/{ev} ({round(100 * frac)}%)",
                     fontName="Helvetica", fontSize=8, fillColor=MUTED))
        y -= 24
    return d


def _pour_section(facts, h2, body, cell, muted) -> list:
    """Pass rate by WCAG principle — POUR (backlog R8).

    WCAG groups its success criteria under four principles (Perceivable / Operable /
    Understandable / Robust), split here by the leading digit of each SC number. Per principle,
    this shows how many of the criteria ACP actually EVALUATED (a validator ran and returned PASS
    or FAIL) passed. Deterministic and honest by construction: not-evaluated and review-only
    criteria are excluded, so this is a pass rate among evaluated checks — NOT a conformance
    percentage. Rendered only when something was evaluated; a principle with nothing evaluated
    shows "—" rather than a misleading 0%.
    """
    principles = (facts or {}).get("principles") or []
    if sum(p.get("evaluated", 0) for p in principles) == 0:
        return []
    el = [Paragraph("Pass rate by WCAG principle", h2)]
    el.append(Paragraph(
        "WCAG groups its criteria under four principles — Perceivable, Operable, Understandable, "
        "Robust. Of the criteria ACP <i>evaluated</i> for these documents (a validator ran and "
        "returned pass or fail), the share that passed, per principle. Not-evaluated and "
        "review-only criteria are excluded, so this is a pass rate among evaluated checks — "
        "<b>not</b> a statement of WCAG 2.1 AA conformance.", muted))
    el.append(Spacer(1, 8))
    rows = [["Principle", "Evaluated", "Passed", "Pass rate"]]
    for p in principles:
        ev, ps = p.get("evaluated", 0), p.get("passed", 0)
        rate = f"{ps}/{ev} ({round(100 * ps / ev)}%)" if ev else "—"
        rows.append([Paragraph(_esc(p.get("principle", "")), cell), ev, ps, rate])
    t = Table(rows, colWidths=[2.4 * inch, 1.1 * inch, 1.0 * inch, 1.5 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    el.append(t)
    el.append(Spacer(1, 6))
    el.append(_pour_bars(principles))       # the same rates, drawn — a reviewer reads bars faster
    el.append(Spacer(1, 8))
    return el


# GENERIC, per-format independent-verification steps (backlog R13). Deliberately NOT doc-specific:
# these tell an auditor how to confirm the result themselves with a mainstream tool, and must stay
# true of every document of that format — so they name the tool and the checks, never a claim about
# a particular file. Keyed by the uppercased extension _fmt() returns.
_MANUAL_VERIFY = {
    "DOCX": ("Microsoft Word → Review → Check Accessibility",
             "Confirm no errors under Missing Alternative Text, Table Header Row, or Document Title; "
             "the checker should report no errors under these headings."),
    "PPTX": ("Microsoft PowerPoint → Review → Check Accessibility",
             "Confirm each slide's reading order (Home → Arrange → Selection Pane) and that every "
             "image carries alt text."),
    "XLSX": ("Microsoft Excel → Review → Check Accessibility",
             "Confirm each data table has a header row and that sheet tabs have meaningful names."),
    "PDF": ("Adobe Acrobat Pro → Accessibility → Accessibility Check (or read it with NVDA on "
            "Windows / VoiceOver on macOS)",
            "Confirm the document is Tagged and declares a Title, a Language and a logical reading "
            "order; with a screen reader, confirm headings and alt text are announced."),
    "HTML": ("Browser DevTools → Accessibility panel, or install the axe DevTools extension "
             "(Chrome/Edge/Firefox)",
             "Confirm every image has a non-empty alt attribute, form inputs have associated labels, "
             "the page has a main landmark, headings form a logical outline with no skipped levels, "
             "and the axe / DevTools checker reports no critical violations."),
}


def _manual_verification_section(files, h2, body, cell, muted) -> list:
    """How to independently verify this result (backlog R13). For each document format actually in
    this scan, the mainstream tool and the checks that let an auditor confirm the finding themselves
    — generic per format, never a claim about a specific document. Rendered only for formats present."""
    fmts = []
    for f in files:
        k = _fmt(f)
        if k in _MANUAL_VERIFY and k not in fmts:
            fmts.append(k)
    if not fmts:
        return []
    el = [Paragraph("How to verify this independently", h2)]
    el.append(Paragraph(
        "This report is machine-generated evidence; it is stronger when you can reproduce it. For "
        "each document format in this scan, here is how to confirm the result with a mainstream "
        "tool — the steps are generic to the format, not tied to any one document.", muted))
    el.append(Spacer(1, 6))
    label = {"DOCX": "Word", "PPTX": "PowerPoint", "XLSX": "Excel", "PDF": "PDF", "HTML": "HTML"}
    rows = [["Format", "Tool", "What to confirm"]]
    for k in fmts:
        tool, steps = _MANUAL_VERIFY[k]
        rows.append([Paragraph(f"<b>{label.get(k, k)}</b>", cell),
                     Paragraph(_esc(tool), cell), Paragraph(_esc(steps), cell)])
    t = Table(rows, colWidths=[0.9 * inch, 2.5 * inch, 3.0 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    el.append(t)
    el.append(Spacer(1, 8))
    return el


def _limitations_section(facts, unassessed, unanalysable, h2, body, muted) -> list:
    """P-13 — Material limitations of this assessment, near the executive summary.

    Lists the high-level constraints on what this report asserts: criteria deferred to human
    review, criteria with no automated validator for these formats, and documents that could
    not be fully assessed. The detailed criterion lists appear in 'What this report covers'
    below; this section names the constraints so an auditor reading the executive summary
    does not have to scroll to find them.

    Password-protection cause, OCR status, and ownership metadata are not yet recorded in
    the scan record; the unanalysable count absorbs all three without distinguishing them.
    """
    scope = (facts or {}).get("scope") or {}
    human_only = scope.get("human_only_criteria") or []
    not_eval = scope.get("not_evaluated_criteria") or []

    def _sc(c: object) -> str:
        return c["sc"] if isinstance(c, dict) else str(c)

    parts = []
    if human_only:
        n = len(human_only)
        sc_list = ", ".join(_sc(c) for c in human_only[:8])
        suffix = f" and {n - 8} more" if n > 8 else ""
        parts.append(
            f"<b>{n} success {'criterion requires' if n == 1 else 'criteria require'} "
            f"human or assistive-technology review</b> and cannot be resolved automatically "
            f"({sc_list}{suffix}). Findings in these lanes are queued for a qualified reviewer "
            "and are never auto-cleared."
        )
    if not_eval:
        n = len(not_eval)
        parts.append(
            f"<b>{n} {'criterion has' if n == 1 else 'criteria have'} no automated validator "
            f"for the file {'format' if n == 1 else 'formats'} in this scan</b> and "
            f"{'was' if n == 1 else 'were'} not evaluated. This is not the same as inapplicable — "
            "some of these criteria do apply to the formats; ACP does not yet check them."
        )
    if unanalysable:
        parts.append(
            f"<b>{unanalysable} document(s) could not be opened or analysed</b>. Common causes "
            "include password protection, an unsupported format variant, or content that requires "
            "OCR to read. This report makes no accessibility assertion about "
            f"{'this file' if unanalysable == 1 else 'these files'}."
        )
    if unassessed:
        parts.append(
            f"<b>{unassessed} document(s) were in scope but never assessed</b> — not opened, "
            f"not scored. This report makes no assertion about "
            f"{'it' if unassessed == 1 else 'them'}."
        )

    if not parts:
        return []

    el = [Paragraph("Limitations of this assessment", h2)]
    el.append(Paragraph(
        "The following constraints bound the claims in this report. Full criterion lists and "
        "document-level breakdowns appear under 'What this report covers' below.", muted))
    el.append(Spacer(1, 5))
    for p in parts:
        el.append(Paragraph("• " + p, muted))
        el.append(Spacer(1, 3))
    el.append(Spacer(1, 5))
    return el


def _criterion_compliance_section(files, h2, body, cell, muted) -> list:
    """Per-criterion compliance summary (backlog R14). Scoped to criteria that fired at least
    one finding — open (still blocking on a non-certifiable document) or cleared (finding present
    on a certifiable document, either remediated or no longer blocking). A full 87-criterion dump
    of everything that was evaluated would be noise; only the ones with evidence appear here.

    A criterion can be open in some documents and cleared in others — both columns are shown.
    Criteria that ran and found nothing are never listed (clean runs are silent in the appendix).
    """
    crit_data: dict[str, dict] = {}
    for f in files:
        fname = f.get("file", "")
        st = _status(f)
        for i in (f.get("issues") or []):
            c = i.get("wcag") or ""
            name = _crit_name(c) if c else ""
            if not name:
                continue
            if name not in crit_data:
                crit_data[name] = {"open": set(), "cleared": set(), "rules": set()}
            rule = i.get("ruleId") or ""
            if rule:
                crit_data[name]["rules"].add(rule)
            if st == "certifiable":
                crit_data[name]["cleared"].add(fname)
            else:
                crit_data[name]["open"].add(fname)

    if not crit_data:
        return []

    def _sc_sort_key(name: str) -> list:
        parts = name.split(" ")[0].split(".")
        try:
            return [int(p) for p in parts]
        except ValueError:
            return [99, 99, 99]

    ordered = sorted(
        crit_data.items(),
        key=lambda kv: (0 if kv[1]["open"] else 1, _sc_sort_key(kv[0])),
    )

    el = [Paragraph("Criteria with findings", h2)]
    el.append(Paragraph(
        "Every criterion that fired at least one finding in this scan — open (blocking) or "
        "cleared (remediated or no longer blocking). Criteria the engine ran and found nothing "
        "are not listed.", muted))
    el.append(Spacer(1, 6))

    hdr_style = ParagraphStyle("ch", parent=cell.parent if hasattr(cell, "parent") else cell,
                                textColor=MUTED, fontSize=8)
    rows = [[Paragraph(h, hdr_style) for h in ("Criterion", "Open", "Cleared", "Rule(s)")]]
    for name, data in ordered:
        open_n = len(data["open"])
        cleared_n = len(data["cleared"])
        rules_str = ", ".join(sorted(r for r in data["rules"] if r))
        if len(rules_str) > 52:
            rules_str = rules_str[:49] + "…"
        open_cell = (Paragraph(f'<font color="#A32D2D"><b>{open_n}</b></font>', cell)
                     if open_n else Paragraph("—", muted))
        cleared_cell = (Paragraph(f'<font color="#3B6D11"><b>{cleared_n}</b></font>', cell)
                        if cleared_n else Paragraph("—", muted))
        rows.append([
            Paragraph(f"<b>{_esc(name)}</b>", cell),
            open_cell,
            cleared_cell,
            Paragraph(_esc(rules_str) if rules_str else "—", muted),
        ])

    t = Table(rows, colWidths=[2.8 * inch, 0.65 * inch, 0.75 * inch, 2.9 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    el.append(t)
    el.append(Spacer(1, 8))
    return el


def _provenance_section(run, facts, meta, diff, cert, total, h2, body, cell, muted) -> list:
    """How this result was produced — method, pipeline & reproducibility (backlog R11 / R12 / R-D /
    R-E). Every figure is COUNTED from the same facts the rest of the report uses; a stage whose
    count is not derivable is named without a number, never with a fabricated one. The reproduce
    line renders only with a stamped rubric hash, the supersedes line only when a previous scan of
    this estate exists — otherwise each is silently omitted (ADR 0016)."""
    f = facts or {}
    docs = f.get("documents") or []
    evaluated = sum(d.get("evaluated", 0) for d in docs)
    findings = sum(d.get("findings", 0) for d in docs)
    by_mode = (f.get("scope") or {}).get("by_mode") or {}
    auto, ai = by_mode.get("auto", 0), by_mode.get("ai-assisted", 0)
    approvals, remediated = f.get("approvals_total", 0), f.get("remediated_total", 0)
    if not evaluated and not findings:
        return []                       # nothing was measured — there is no method to narrate
    el = [Paragraph("How this result was produced", h2)]
    # R11 — the method, carried by THIS scan's real counts.
    el.append(Paragraph(
        "Each document was checked by ACP's deterministic engine, with AI-assisted review for the "
        "semantic criteria a rule cannot decide alone; every applied fix was re-checked by "
        "re-scanning the corrected file, and AI-generated content was queued for human approval "
        "before it counted. For this scan: "
        f"<b>{evaluated}</b> criteria evaluated across <b>{len(docs)}</b> document(s) — "
        f"<b>{auto}</b> by the deterministic engine, <b>{ai}</b> AI-assisted; "
        f"<b>{approvals}</b> human approval(s); <b>{remediated}</b> fix(es) applied and "
        "re-scan-validated.", body))
    el.append(Spacer(1, 6))
    # R12 — the pipeline in order, each count from the same sources as above.
    stages = [f"scanned <b>{len(docs)}</b>", f"evaluated <b>{evaluated}</b>",
              f"<b>{findings}</b> finding(s)", f"<b>{ai}</b> AI-assisted",
              f"<b>{approvals}</b> approval(s)", f"<b>{remediated}</b> remediated &amp; re-validated",
              f"<b>{cert}</b>/<b>{total}</b> certifiable"]
    el.append(Paragraph("<b>Pipeline.</b> " + "  →  ".join(stages), cell))
    el.append(Spacer(1, 6))
    # R-D — actionable reproduce instructions: three steps, not a prose assertion.
    # The full hash is included (not truncated) because the auditor must verify it exactly.
    rubric = meta.get("hash") if meta else None
    if rubric:
        try:
            import core as _core
            _rd_base = (_core.PUBLIC_URL or "").rstrip("/")
        except Exception:
            _rd_base = ""
        src_val = run.get("source") or ""
        src_param = f"?source={_esc(src_val)}" if src_val else "?source=&lt;source&gt;"
        sid = _esc(str(run.get("id", "—")))
        rd_rows = [
            ["1", Paragraph(
                f"<b>Verify the rubric.</b> <font name='Courier' size='7'>"
                f"GET {_esc(_rd_base)}/rubric</font> → confirm the response carries "
                f"<font name='Courier' size='7'>{_esc(str(rubric))}</font> "
                "as its <b>hash</b> field. A mismatch means a different ruleset is active — "
                "findings will diverge regardless of the document set.", muted)],
            ["2", Paragraph(
                f"<b>Re-run the scan.</b> <font name='Courier' size='7'>"
                f"POST {_esc(_rd_base)}/scans{src_param}</font> against the same document "
                f"set used for scan <b>{sid}</b>. The scan must complete successfully "
                "(status: complete, not error or cancelled).", muted)],
            ["3", Paragraph(
                f"<b>Compare findings.</b> The new scan's failing WCAG criteria and per-file "
                f"scores must match scan <b>{sid}</b>. Any divergence indicates a rubric "
                "version change, a document change, or a non-deterministic AI step — "
                "each is a distinct fact about the pipeline, not a test failure.", muted)],
        ]
        num_style = ParagraphStyle("rdnum", parent=muted, fontSize=8, alignment=1)
        rd_t = Table(
            [[Paragraph(n, num_style), cell_p] for n, cell_p in rd_rows],
            colWidths=[0.22 * inch, 6.38 * inch])
        rd_t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("BACKGROUND", (0, 0), (-1, -1), ZEBRA), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ]))
        el.append(Paragraph("<b>Reproduce this result.</b>", muted))
        el.append(Spacer(1, 3))
        el.append(rd_t)
    # R-E — supersedes, only when a previous scan of this estate exists.
    # Include the previous scan ID so auditors can trace the custody chain by ID, not just date.
    prev_at = (diff or {}).get("prev_at")
    prev_sid = (diff or {}).get("prev_id")
    if prev_at:
        date_str = _esc(str(prev_at)[:10])
        if prev_sid:
            prev_ref = (f"scan <font name='Courier' size='7'>{_esc(str(prev_sid))}</font>"
                        f" ({date_str})")
        else:
            prev_ref = date_str
        el.append(Paragraph(
            f"<b>Supersedes.</b> This result supersedes {prev_ref}.", muted))
    el.append(Spacer(1, 8))
    return el


def _mode_bar(by_mode: dict, total: int) -> Drawing:
    """Stacked horizontal bar — deterministic | AI-assisted | human-only criteria (R10).
    Same 440pt width as _pour_bars for visual consistency across the report."""
    MODES = [
        ("auto",        GREEN, "Deterministic"),
        ("ai-assisted", AMBER, "AI-assisted"),
        ("human-only",  PLUM,  "Human-only"),
        ("unknown",     GREY,  "Unknown"),
    ]
    W = 440
    d = Drawing(W, 36)
    x = 0.0
    leg_x = 0
    for key, color, label in MODES:
        n = by_mode.get(key, 0)
        if not n or not total:
            continue
        w = W * n / total
        d.add(Rect(x, 20, w, 12, fillColor=color, strokeColor=None))
        pct = round(100 * n / total)
        d.add(Rect(leg_x, 4, 8, 8, fillColor=color, strokeColor=None))
        d.add(String(leg_x + 11, 5, f"{label}  {n} ({pct}%)",
                     fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
        x += w
        leg_x += 140
    return d


def _assurance_section(facts, h2, body, cell, muted, hitl=None) -> list:
    """Human review & assurance (backlog R9 / R10). Every figure has a real denominator: review
    outcomes counted from the immutable decision_log; the mode split as real per-mode counts
    (deterministic / AI-assisted / human-only); the effort figure as fixes-cleared ÷ findings
    with that basis named. NO "% effort saved" and NO "cleared ÷ attempted" — the attempted
    denominator is not tracked (only re-scan-cleared fixes are recorded), so that ratio is
    omitted, not invented (ADR 0016). Omitted entirely when nothing was reviewed, remediated or
    evaluated.

    hitl: optional hitl_analytics() result — adds avg review time (if real timestamps) and the
    edited-draft count (how many approved reviews included a human correction to the AI text)."""
    f = facts or {}
    review = f.get("review") or {}
    docs = f.get("documents") or []
    evaluated = sum(d.get("evaluated", 0) for d in docs)
    findings = sum(d.get("findings", 0) for d in docs)
    by_mode = ((f.get("scope") or {}).get("by_mode")) or {}
    auto = by_mode.get("auto", 0)
    remediated = f.get("remediated_total", 0)
    reviewed = review.get("reviewed", 0)
    if not reviewed and not remediated and not evaluated:
        return []
    h = hitl or {}
    edited = (h.get("by_action") or {}).get("edit", 0)
    avg_ms = h.get("avg_review_ms")
    el = [Paragraph("Human review &amp; assurance", h2)]
    # R9 — the review outcomes, from the immutable log (approved/rejected + what the platform cleared).
    band = _stat_band([
        Paragraph(f'<font size="20"><b>{reviewed}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">findings human-reviewed</font>', body),
        Paragraph(f'<font size="20" color="#3B6D11"><b>{review.get("approved", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">approved</font>', body),
        Paragraph(f'<font size="20" color="#854F0B"><b>{review.get("rejected", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">rejected</font>', body),
        Paragraph(f'<font size="20"><b>{remediated}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">remediated &amp; re-validated</font>', body),
    ], [])
    el.append(band)
    el.append(Spacer(1, 8))
    # R10 — stacked bar + prose showing all three decision modes on a real denominator.
    if evaluated:
        el.append(_mode_bar(by_mode, evaluated))
        el.append(Spacer(1, 4))
        ai_n = by_mode.get("ai-assisted", 0)
        hu_n = by_mode.get("human-only", 0)
        clauses = [f"<b>{auto}</b> of <b>{evaluated}</b> ({round(100 * auto / evaluated)}%) "
                   "decided by the deterministic engine"]
        if ai_n:
            clauses.append(f"<b>{ai_n}</b> ({round(100 * ai_n / evaluated)}%) used AI-assisted review")
        if hu_n:
            clauses.append(f"<b>{hu_n}</b> ({round(100 * hu_n / evaluated)}%) required human-only action")
        el.append(Paragraph(
            "<b>Assurance.</b> Of the evaluated criteria: " + "; ".join(clauses) +
            ". Every remediation counted here re-cleared the post-fix re-scan.", muted))
    # R9 effort — only as the honest ratio, basis named; never a modelled time saving.
    if findings:
        edited_clause = (f" Of the approved reviews, <b>{edited}</b> included human edits to the AI draft."
                         if edited else "")
        el.append(Paragraph(
            f"<b>Effort.</b> <b>{remediated}</b> of <b>{findings}</b> finding(s) were cleared by an "
            f"applied, re-validated fix (<b>{round(100 * remediated / findings)}%</b>) — basis: "
            f"fixes-cleared ÷ findings, not a modelled hours-saved figure.{edited_clause}", muted))
    # R9 avg review time — only when real timestamps exist (never estimated or defaulted).
    if avg_ms is not None:
        avg_s = round(avg_ms / 1000, 1)
        el.append(Paragraph(
            f"<b>Avg review time.</b> <b>{avg_s} s</b> per finding — measured from reviewer "
            "action timestamps recorded at decision time.", muted))
    el.append(Spacer(1, 8))
    return el


def _work_by_category_section(evidence: list, h2, body, cell, muted) -> list:
    """What changed, grouped the way a person reads a document — Images, Tables, Reading Order —
    not by WCAG id (backlog: the human-task view). An executive or the ops person who did the
    work can read this; "1.3.1 Passed" they cannot.

    Every count is the SAME verified-applied evidence the detailed appendix below lists — this
    is a roll-up of that list, not a second source, so the summary and the detail can never
    disagree. Only fixes that cleared the post-fix re-scan are counted; proposals awaiting
    approval are excluded exactly as they are everywhere else in this report. The WCAG ids stay,
    demoted to a parenthetical, because an auditor still needs them.
    """
    el: list = []
    # One row per verified fix, tagged with its human category. Unknown criteria (no mapping)
    # are skipped rather than shown under a wrong heading — the contract test guarantees every
    # catalog criterion is mapped, so nothing real is dropped.
    counts: dict[str, int] = {}
    names: dict[str, dict[str, int]] = {}
    for doc in evidence or []:
        for e in doc.get("applied", []):
            cat = _hc.category_of(e.get("sc") or "")
            if not cat:
                continue
            counts[cat] = counts.get(cat, 0) + 1
            hn = _hc.human_name(e.get("sc") or "") or e.get("criterion") or e.get("sc")
            bucket = names.setdefault(cat, {})
            bucket[hn] = bucket.get(hn, 0) + 1
    if not counts:
        return el

    el.append(Paragraph("What we fixed · by section of your documents", h2))
    el.append(Paragraph(
        "Grouped the way you would find it in the document itself, not by standard. Each line is "
        "a count of fixes that were re-scanned and verified — the detailed evidence, with before "
        "&amp; after and who approved each one, follows. WCAG identifiers are kept in parentheses "
        "for auditors.", muted))
    el.append(Spacer(1, 8))

    rows = []
    for cat in sorted(counts, key=lambda k: _hc.CATEGORIES[k]["order"]):
        c = _hc.CATEGORIES[cat]
        n = counts[cat]
        # The human names of the criteria fixed in this category, with the WCAG ids that back
        # them, so the parenthetical is honest rather than decorative.
        detail = ", ".join(
            f"{hn}" + (f" ×{k}" if k > 1 else "")
            for hn, k in sorted(names[cat].items(), key=lambda kv: (-kv[1], kv[0])))
        wcags = ", ".join(sorted({sc for doc in evidence for e in doc.get("applied", [])
                                  if _hc.category_of(e.get("sc") or "") == cat
                                  for sc in [e.get("sc")] if sc}))
        rows.append([
            # No emoji here: reportlab's Helvetica has no emoji glyphs, so an icon would render
            # as a tofu box in the PDF. The icon lives in human_categories for the web inbox,
            # where the browser can draw it; the formal report uses the plain label.
            Paragraph(f"<b>{_esc(c['label'])}</b>", cell),
            Paragraph(f"<font color='#3B6D11'>✓ {n} fix{'es' if n != 1 else ''}</font>", cell),
            Paragraph(f"{_esc(detail)} <font color='#6c6470'>(WCAG {_esc(wcags)})</font>", cell),
        ])
    t = Table(rows, colWidths=[1.9 * inch, 0.8 * inch, 4.4 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ZEBRA]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    el.append(t)
    el.append(Spacer(1, 6))
    return el


def _thumb_flowable(thumb: str | None, edge: float = 0.62 * inch):
    """A base64 data-URL thumbnail (`applied_fixes.thumb`) → a reportlab Image, or None.
    Best-effort: an undecodable thumbnail must never break the report."""
    if not thumb or "base64," not in thumb:
        return None
    try:
        import base64
        raw = base64.b64decode(thumb.split("base64,", 1)[1])
        img = Image(io.BytesIO(raw))
        w, h = img.imageWidth or 1, img.imageHeight or 1
        scale = edge / max(w, h)
        img.drawWidth, img.drawHeight = w * scale, h * scale
        return img
    except Exception:
        return None


# Cap the appendix so a large estate can't produce a 400-page PDF. Whatever is dropped is
# ALWAYS disclosed in the report — a silent truncation would read as "this is everything",
# exactly the over-claim this section exists to prevent.
_EVIDENCE_MAX_FILES = 25
_EVIDENCE_MAX_PER_FILE = 20


def _evidence_section(evidence: list, h2, body, cell, muted) -> list:
    """Per-issue remediation evidence — the audit artifact (backlog R1).

    Two DELIBERATELY separate parts per document:
      * Applied & verified — from `remediation_diff`, which the worker only writes for fixes
        that cleared the post-fix re-scan. Every row here is genuinely validated.
      * Proposed, awaiting approval — AI drafts a human has not yet accepted. These are NOT
        remediations and are never shown as PASS. Merging the two would let the report claim
        work the platform has not actually done.
    """
    el: list = []
    if not evidence:
        return el

    el.append(Paragraph("Remediation evidence · what changed, and on whose authority", h2))
    el.append(Paragraph(
        "Each entry is one finding. <b>Applied &amp; verified</b> fixes were re-scanned after the "
        "change and the criterion no longer fails — that re-scan is the only thing that promotes a "
        "fix into this list. <b>Proposed</b> entries are AI drafts still awaiting human approval; "
        "they are <b>not</b> remediations and are counted as fixed nowhere in this report.", muted))
    el.append(Spacer(1, 8))

    for doc in evidence[:_EVIDENCE_MAX_FILES]:
        el.append(Spacer(1, 6))
        el.append(Paragraph(f"<b>{_esc(doc['file'])}</b>", body))

        for e in doc["applied"][:_EVIDENCE_MAX_PER_FILE]:
            when = (e.get("reviewed_at") or "")[:19].replace("T", " ")
            # R-C — four assurance cases, from highest to lowest certainty.
            # Tier 1a: deterministic fixer, no AI, no human decision (fully automatic).
            # Tier 1b: deterministic fixer, no AI, but a human also confirmed it.
            # Tier 2:  AI-generated + human-approved + re-scan-validated (highest trust for AI).
            # Tier 3:  AI-generated + re-scan-validated, no human approval recorded.
            has_ai = bool(e.get("value"))
            has_decision = bool(e.get("decision"))
            decision_str = (f"{e['decision']} by {e.get('reviewer') or 'reviewer'}"
                            + (f" · {when} UTC" if when else ""))
            if has_ai and has_decision:
                badge = "<font color='#3B6D11'>&#x25CF; AI &middot; human-confirmed</font>"
                sign_off = decision_str
            elif has_ai:
                badge = "<font color='#854F0B'>&#x25CF; AI &middot; re-scan-validated</font>"
                sign_off = "AI-generated fix · validated on re-scan · no human approval recorded"
            elif has_decision:
                badge = "<font color='#3B6D11'>&#x25CF; Deterministic &middot; human-confirmed</font>"
                sign_off = decision_str
            else:
                badge = "<font color='#3B6D11'>&#x25CF; Deterministic</font>"
                sign_off = "deterministic fixer · auto-applied · no human decision needed"
            _fid = _finding_id(doc["file"], e.get("criterion", ""),
                               e.get("location") or e.get("before", "")[:60])
            lines = [
                Paragraph(f"{badge} &nbsp;<b>{_esc(e['criterion'])}</b>"
                          f" &nbsp;<font color='#3B6D11'>&#x2713; validated on re-scan</font>"
                          f" &nbsp;<font color='#6c6470' size='7'>FND-{_fid}</font>", cell),
                Paragraph(f"<font color='#6c6470'>Before</font> &nbsp;{_esc(e.get('before'))}", cell),
                Paragraph(f"<font color='#6c6470'>After</font> &nbsp;<b>{_esc(e.get('after'))}</b>", cell),
            ]
            if e.get("value"):
                src = f" <font color='#6c6470'>({_esc(e['source'])})</font>" if e.get("source") else ""
                lines.append(Paragraph(f"<font color='#6c6470'>AI wrote</font> &nbsp;{_esc(e['value'])}{src}", cell))
            if e.get("note"):
                lines.append(Paragraph(f"<font color='#6c6470'>Why</font> &nbsp;{_esc(e['note'])}", cell))
            lines.append(Paragraph(f"<font color='#6c6470'>Decision</font> &nbsp;{_esc(sign_off)}", cell))

            thumb = _thumb_flowable(e.get("thumb"))
            row = [[thumb, lines]] if thumb else [[lines]]
            widths = [0.75 * inch, 6.35 * inch] if thumb else [7.1 * inch]
            t = Table(row, colWidths=widths)
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            el.append(t)
            el.append(Spacer(1, 4))

        dropped = len(doc["applied"]) - _EVIDENCE_MAX_PER_FILE
        if dropped > 0:
            el.append(Paragraph(f"…and {dropped} further verified fix(es) on this document, omitted for length.", muted))

        for p in doc["proposed"]:
            note = ("validated on re-scan — awaiting approval" if p.get("validated")
                    else "awaiting human approval")
            _pfid = _finding_id(doc["file"], p.get("criterion", ""))
            lines = [Paragraph(
                f"<b>{_esc(p['criterion'])}</b> &nbsp;<font color='#854F0B'>proposed — not remediated "
                f"({note})</font> &nbsp;<font color='#6c6470' size='7'>FND-{_pfid}</font>", cell)]
            for pr in p["proposals"][:6]:
                why = f" <font color='#6c6470'>— {_esc(pr.get('rationale'))}</font>" if pr.get("rationale") else ""
                src = (f" <font color='#6c6470'>({_esc(pr['source'])})</font>"
                       if pr.get("source") else "")
                lines.append(Paragraph(
                    f"<font color='#6c6470'>Proposed</font> &nbsp;{_esc(pr.get('proposed_value'))}{why}{src}", cell))
                if pr.get("why_review"):
                    lines.append(Paragraph(
                        f"<font color='#6c6470'>Basis</font> &nbsp;{_esc(pr['why_review'])}", cell))
            t = Table([[lines]], colWidths=[7.1 * inch])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, AMBER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            el.append(Spacer(1, 2))
            el.append(t)

    if len(evidence) > _EVIDENCE_MAX_FILES:
        el.append(Spacer(1, 6))
        el.append(Paragraph(
            f"Evidence shown for the first {_EVIDENCE_MAX_FILES} of {len(evidence)} remediated "
            "documents; the remainder are omitted from this PDF for length.", muted))
    return el


def _donut(counts: dict[str, int]) -> Drawing:
    """Status split donut + legend, drawn as one Drawing so it flows as a block."""
    d = Drawing(250, 130)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 5, 15, 100, 100
    order = [k for k in ("certifiable", "issues", "clean", NOT_ASSESSED, "uncertain",
                         "unanalysable") if counts.get(k)]
    pie.data = [counts[k] for k in order] or [1]
    pie.labels = None
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    pie.innerRadiusFraction = 0.55
    for i, k in enumerate(order):
        pie.slices[i].fillColor = STATUS_COLOR[k]
    if not order:                       # empty estate → a single neutral ring
        pie.slices[0].fillColor = LINE
    d.add(pie)
    total = sum(counts.values()) or 1
    y = 100
    for k in order:
        d.add(Rect(125, y, 8, 8, fillColor=STATUS_COLOR[k], strokeColor=None))
        d.add(String(139, y + 1, f"{STATUS_LABEL[k]} · {counts[k]} ({round(counts[k] / total * 100)}%)",
                     fontName="Helvetica", fontSize=8.5, fillColor=PLUM))
        y -= 17
    return d


def _crit_bars(fails: dict[str, int], total_files: int) -> Drawing:
    """Top failing criteria as horizontal bars — the report's 'where to look first'."""
    top = sorted(fails.items(), key=lambda x: -x[1])[:8]
    names = [_crit_name(c) for c, _ in top]
    h = max(90, 22 * len(top) + 30)
    d = Drawing(440, h)
    bc = HorizontalBarChart()
    bc.x, bc.y = 175, 12
    bc.width, bc.height = 225, h - 24
    bc.data = [[n for _, n in reversed(top)]]
    bc.categoryAxis.categoryNames = list(reversed(names))
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 7.5
    bc.categoryAxis.labels.fillColor = PLUM
    bc.categoryAxis.strokeColor = LINE
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max(total_files, max((n for _, n in top), default=1))
    bc.valueAxis.labels.fontSize = 7.5
    bc.valueAxis.labels.fillColor = MUTED
    bc.valueAxis.strokeColor = LINE
    bc.bars[0].fillColor = PLUM
    bc.bars[0].strokeColor = None
    bc.barWidth = 11
    d.add(bc)
    return d


def _stat_band(cells, styles) -> Table:
    """The 4-up stat card row used by the certification summary."""
    band = Table([cells], colWidths=[1.85 * inch] * len(cells))
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.75, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ] + list(styles)))
    return band


def _ai_governance_section(run, h2, body, cell, muted) -> list:
    """AI governance & provenance for this scan (ADR 0019 §4/§7): a real, per-scan aggregate
    of the recorded ai_calls — how many AI-assisted operations ran, where they were processed
    (network boundary), and what they cost. Every figure is measured, never a fabricated score
    (ADR 0016); the keyless local build's $0 IS the governance headline. Best-effort — the
    report must never fail because the rollup is unavailable, so any error drops the section."""
    try:
        import core
        r = core.store.ai_cost_rollup(scan_id=run["id"])
    except ImportError:
        return []      # no core in test/offline context — expected, not a bug
    except Exception:
        _LOG.warning("ai_governance_section: rollup failed for scan %s", run.get("id"), exc_info=True)
        return []
    if not r or not r.get("calls"):
        # Nothing to attest AND nothing to hide: an all-deterministic scan needed no model.
        return [Paragraph("AI governance &amp; provenance", h2),
                Paragraph("No AI-assisted operations were needed for this scan — every finding was "
                          "resolved by the deterministic engine. Nothing was sent to any model.", body)]
    zones = {g["key"]: g for g in r.get("by_zone", [])}
    local = zones.get("local", {}).get("calls", 0)
    off_network = r["calls"] - local
    cost = r.get("cost_usd", 0) or 0
    el = [Paragraph("AI governance &amp; provenance", h2)]
    # The plain-language attestation an enterprise buyer's governance checklist asks for:
    # what ran, whether documents left the network, and the real cost.
    if off_network == 0:
        el.append(Paragraph(
            f"<b>{r['calls']}</b> AI-assisted operation(s) supported this scan. "
            '<font color="#3B6D11"><b>All were processed locally</b></font> — no document or image '
            "left your network, and the total external AI cost was "
            f'<font color="#3B6D11"><b>${cost:.2f}</b></font>.', body))
    else:
        el.append(Paragraph(
            f"<b>{r['calls']}</b> AI-assisted operation(s) supported this scan: <b>{local}</b> processed "
            f"locally and <b>{off_network}</b> escalated to a cloud provider under the configured "
            f"governance policy, at a recorded cost of <b>${cost:.2f}</b>.", body))
    el.append(_stat_band([
        Paragraph(f'<font size="18"><b>{r["calls"]}</b></font><br/>'
                  f'<font size="8" color="#6c6470">AI operations</font>', body),
        Paragraph(f'<font size="18" color="#3B6D11"><b>{local}</b></font><br/>'
                  f'<font size="8" color="#6c6470">local · 🟢 on-network</font>', body),
        Paragraph(f'<font size="18"><b>${cost:.2f}</b></font><br/>'
                  f'<font size="8" color="#6c6470">external AI cost</font>', body),
        Paragraph(f'<font size="18"><b>{r.get("avg_latency_ms", 0)}</b></font><br/>'
                  f'<font size="8" color="#6c6470">avg latency (ms)</font>', body),
    ], []))
    prov = r.get("by_provider") or []
    if prov:
        prov_str = " · ".join(f'{g["calls"]} {g["key"]}' + (f' ${g["cost_usd"]:.2f}' if g["cost_usd"] else "")
                              for g in prov)
        el.append(Paragraph(
            f'<font color="#6c6470">By provider: {prov_str}. Every AI operation is recorded with its '
            "model, processing zone, latency and cost, and is auditable per finding.</font>", muted))
    return el


def _assessment_scope_block(run: dict, meta: dict, facts: dict | None,
                            fmt_str: str, h2, body, cell, muted,
                            rendered_at: str = "") -> list:
    """Assessment scope declaration (P-12) + report provenance (P-16).

    A concise block near the top of the report stating exactly what was in scope: source,
    file types, scan window, rubric + conformance target, AI-assisted flag. Placed after
    the decision card so the reader sees the scope before interpreting any percentage.

    P-16 adds two further rows: report-generated timestamp (when this PDF was rendered),
    scan ID, report schema version, and application build commit.
    """
    scope = (facts or {}).get("scope") or {}
    estate = scope.get("estate") or {}
    by_mode = scope.get("by_mode") or {}
    ai_flag = by_mode.get("ai-assisted", 0) > 0

    source_map = {"drive": "Google Drive", "folder": "Local folder", "upload": "Direct upload"}
    source_label = source_map.get(run.get("source", ""), run.get("source") or "—")

    started = (run.get("started_at") or "")[:16].replace("T", " ")
    completed = (run.get("completed_at") or "")[:16].replace("T", " ")
    window = (f"{started} — {completed} UTC" if started and started != completed
              else f"{completed} UTC" if completed else "—")

    excluded = estate.get("excluded", 0)
    excl_note = f" · {excluded} file(s) excluded by policy" if excluded else ""

    rubric_str = (f"v{meta.get('version', '—')} · hash {(meta.get('hash') or '—')[:12]}…"
                  if meta.get("version") else "—")
    ai_note = ("Deterministic + AI-assisted checks" if ai_flag
               else "Deterministic checks only — no AI operations")

    build_sha = (os.environ.get("ACP_BUILD_SHA") or "").strip()
    build_str = build_sha[:12] if build_sha else "—"

    el = [Paragraph("Assessment scope", h2)]
    rows = [
        [Paragraph("<b>Source</b>", cell), Paragraph(_esc(source_label), cell),
         Paragraph("<b>Scan window</b>", cell), Paragraph(_esc(window), cell)],
        [Paragraph("<b>File types assessed</b>", cell), Paragraph(_esc(fmt_str or "—"), cell),
         Paragraph("<b>Method</b>", cell), Paragraph(_esc(ai_note), cell)],
        [Paragraph("<b>Standard &amp; target</b>", cell),
         Paragraph(_esc((meta.get("target") or "WCAG 2.1 AA") + excl_note), cell),
         Paragraph("<b>Rubric</b>", cell), Paragraph(_esc(rubric_str), cell)],
        # P-16: report provenance rows
        [Paragraph("<b>Report generated</b>", cell),
         Paragraph(_esc(rendered_at or "—"), cell),
         Paragraph("<b>Scan ID</b>", cell),
         Paragraph(_esc(str(run.get("id") or "—")), cell)],
        [Paragraph("<b>Report schema</b>", cell),
         Paragraph(_esc(f"v{REPORT_SCHEMA_VERSION}"), cell),
         Paragraph("<b>Build</b>", cell),
         Paragraph(_esc(build_str), cell)],
    ]
    t = Table(rows, colWidths=[1.3 * inch, 2.25 * inch, 1.3 * inch, 2.25 * inch])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED), ("TEXTCOLOR", (2, 0), (2, -1), MUTED),
        ("BACKGROUND", (0, 0), (-1, -1), ZEBRA), ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    el.append(t)
    el.append(Spacer(1, 4))
    return el


def build_report(run: dict, files: list, meta: dict, decisions: dict | None = None,
                 evidence: list | None = None, facts: dict | None = None) -> bytes:
    # P-16: capture render time once so all sections share a consistent timestamp
    _rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    buf = io.BytesIO()
    # `lang` reaches the PDF catalog as /Lang (WCAG 3.1.1) — without it a screen reader guesses
    # the language of the certification document from the user's locale. `title` is already the
    # docinfo /Title (2.4.2); _footer sets the ViewerPreferences half of that criterion.
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=f"mova.io conformance report {run['id']}",
                            lang=REPORT_LANG,
                            topMargin=0.6 * inch, bottomMargin=0.75 * inch,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch)
    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Title"], textColor=PLUM, fontSize=20, spaceAfter=1,
                       alignment=0, leading=24)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=MUTED, fontSize=9.5, spaceAfter=0, leading=13)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=PLUM, fontSize=12.5, spaceBefore=18, spaceAfter=6)
    lead = ParagraphStyle("lead", parent=ss["Normal"], textColor=PLUM, fontSize=10.5, leading=15.5, spaceBefore=2)
    body = ParagraphStyle("body", parent=ss["Normal"], textColor=PLUM, fontSize=9.5, leading=14)
    cell = ParagraphStyle("cell", parent=ss["Normal"], textColor=PLUM, fontSize=8.5, leading=10.5)
    cellm = ParagraphStyle("cellm", parent=ss["Normal"], textColor=MUTED, fontSize=8, leading=10)
    note = ParagraphStyle("note", parent=ss["Normal"], textColor=MUTED, fontSize=8, leading=11.5)
    el = []

    target = meta.get("target") or "Level AA"
    # Normalise the standard string: the rubric's conformance_target may already be a full
    # "WCAG 2.1 AA" or just a level like "Level AA" — present one clean phrase either way,
    # never a doubled "WCAG 2.1 WCAG 2.1 AA".
    std = target.strip() if target.strip().upper().startswith("WCAG") else f"WCAG 2.1 {target.strip()}"

    # ── Header band: logo + title ────────────────────────────────────────────
    report_generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _completed_raw = run.get("completed_at") or ""
    if _completed_raw:
        assessment_completed = _completed_raw[:19].replace("T", " ")
        _snapshot_label = ""
    else:
        assessment_completed = "in progress"
        _snapshot_label = " · SNAPSHOT — scan still running"
    build_commit = os.environ.get("BUILD_COMMIT", "")
    _commit_str = f" · build {build_commit[:8]}" if build_commit else ""
    title_block = [
        # NOT "Conformance Report". This document reports what ACP checked, what it changed
        # and what it re-verified; it does not determine conformance, and the title was the
        # largest claim on a page that spends three paragraphs declining to make one.
        #
        # Note this is the SCAN report, about a customer's documents. ACP's own VPAT-style ACR
        # (frontend pdfReport.js) is a genuine conformance report about the mova.io product and
        # keeps its name — the distinction is who is asserting what about whom.
        Paragraph("Accessibility Assessment Report", H),
        Paragraph(
            f"{std} · Assessment completed {assessment_completed} UTC"
            f" · Report generated {report_generated_at} UTC{_snapshot_label}", sub),
    ]
    logo = Image(str(LOGO), width=1.32 * inch, height=1.32 * inch * 264 / 800) if LOGO.exists() else Spacer(1, 1)
    head = Table([[logo, title_block]], colWidths=[1.55 * inch, 5.55 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (0, 0), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    el.append(head)
    el.append(HRFlowable(width="100%", thickness=1.2, color=PLUM, spaceBefore=6, spaceAfter=10))
    _rubric_name = meta.get("name") or ""
    _rubric_display = (f"{_rubric_name} v" if _rubric_name else "v") + (meta.get("version") or "—")
    el.append(Paragraph(
        f"Scan <b>{run['id']}</b>"
        f" · rubric {_esc(_rubric_display)}"
        f" · hash <b>{(meta.get('hash') or '—')[:12]}</b>"
        f" · schema v{REPORT_SCHEMA_VERSION}{_commit_str} — "
        "results are reproducible from the rubric hash. Scans run read-only; documents are never retained.", sub))

    # ── P-16: Snapshot notice — if the scan is still in progress ─────────────
    _DONE_STATUSES = {None, "done", "completed", "certifiable"}
    if run.get("status") not in _DONE_STATUSES:
        el.append(Paragraph(
            '<font color="#854F0B"><b>⚠ Snapshot only — </b></font>'
            '<font color="#854F0B">this report was generated while the scan was still in progress '
            f'(status: {_esc(str(run.get("status") or "unknown"))}). '
            "Findings and scores may change before the scan completes.</font>",
            lead))

    # ── Certification decision (R2) ──────────────────────────────────────────
    # Answers "can I ship this?" before any chart. The plain-language WHY (R3) is the
    # executive verdict below — this card carries the decision, the counts and the digest,
    # and deliberately does not repeat that prose.
    _muted = ParagraphStyle("rmuted", parent=ss["Normal"], textColor=MUTED, fontSize=8, leading=11.5)
    el.extend(_decision_block(run, files, meta, facts, h2, body, _muted))

    # ── Reconcile the estate: open (blocking) vs certifiable/remediated ──────
    counts: dict[str, int] = {}
    open_sev: dict[str, int] = {}          # severity of OPEN findings only (non-certifiable files)
    open_fails: dict[str, int] = {}        # docs affected per criterion, OPEN only
    resolved_crit: dict[str, int] = {}     # findings cleared/non-blocking on certifiable files
    remediated_docs = 0
    open_findings = 0
    for f in files:
        st = _status(f)
        counts[st] = counts.get(st, 0) + 1
        issues = f.get("issues") or []
        if st == "certifiable":
            if f.get("remediated_at") or f.get("drive_write_url"):
                remediated_docs += 1
            for i in issues:
                resolved_crit[i.get("wcag")] = resolved_crit.get(i.get("wcag"), 0) + 1
        else:
            open_findings += len(issues)
            for i in issues:
                s = (i.get("severity") or "MINOR").upper()
                open_sev[s] = open_sev.get(s, 0) + 1
            for c in {i.get("wcag") for i in issues}:
                open_fails[c] = open_fails.get(c, 0) + 1
    cert = counts.get("certifiable", 0)
    total = len(files) or 1
    unassessed = counts.get(NOT_ASSESSED, 0)
    unanalysable = counts.get("unanalysable", 0)
    assessed = total - unassessed
    pct = round(cert / assessed * 100) if assessed else 0
    avg = "—" if run.get("avg_score") is None else run["avg_score"]
    resolved_total = sum(resolved_crit.values())
    total_eval = sum(d.get("evaluated", 0) for d in ((facts or {}).get("documents") or []))

    # ── Executive summary — plain-language verdict ───────────────────────────
    # `total` counts every document in the estate, INCLUDING any nobody scored, so it is not the
    # denominator for a conformance claim. Both branches below said "analysed document(s)" about
    # it, and the else-branch went further: with an estate of unscored rows the only non-zero
    # count was 'clean', so the report read "All 2 analysed document(s) meet WCAG 2.1 AA with
    # zero open blocking findings" about two spreadsheets nobody had opened. In a document a
    # customer files as evidence, that sentence is the whole liability.
    if counts.get("issues") or counts.get("uncertain") or counts.get("unanalysable") or unassessed:
        verdict = (f"<b>{cert} of {assessed}</b> assessed document(s) came back with zero open "
                   f"blocking findings among the {std} criteria ACP checked. "
                   f"<b>{counts.get('issues', 0)}</b> document(s) still carry open findings "
                   f"({open_findings} total)")
        if counts.get("uncertain"):
            verdict += f", <b>{counts['uncertain']}</b> could not be fully evaluated"
        if counts.get("unanalysable"):
            verdict += f", and <b>{counts['unanalysable']}</b> could not be opened"
        verdict += "."
        # Stated as its own sentence, not folded into the list above: an unassessed document is
        # not a weaker finding, it is the ABSENCE of a measurement, and this report asserts
        # nothing whatsoever about it.
        if unassessed:
            verdict += (f" <b>{unassessed} of {total}</b> document(s) in scope were never "
                        f"assessed — they were listed from the source but not opened or scored, "
                        f"so this report makes no conformance claim about them either way. "
                        f"Run Assess over them before drawing any conclusion about this "
                        f"estate as a whole.")
    else:
        verdict = (f"No automated failures detected — all <b>{total}</b> assessed document(s) "
                   f"returned no blocking findings among the <b>{std}</b> criteria ACP evaluated.")
    if remediated_docs:
        verdict += (f" {remediated_docs} document(s) were remediated by the platform, "
                    f"clearing {resolved_total} finding(s).")
    el.append(Paragraph(verdict, lead))

    # ── P-9: Partial-assessment notice ───────────────────────────────────────
    # Make it impossible to miss that some files were not scored. The verdict above already
    # mentions this inline, but a reader skimming for a percentage can miss the caveat buried
    # in a dense paragraph. A stand-alone notice breaks that pattern.
    if unassessed or unanalysable:
        _parts = []
        if unassessed:
            _parts.append(f"<b>{unassessed}</b> document(s) were listed in scope but never assessed")
        if unanalysable:
            _parts.append(f"<b>{unanalysable}</b> document(s) could not be opened or analysed")
        el.append(Paragraph(
            '<font color="#854F0B"><b>⚠ Partial assessment — </b></font>'
            '<font color="#854F0B">' + " and ".join(_parts) +
            " — this report makes no conformance claim about those files.</font>",
            lead))

    # ── P-13: Limitations of this assessment ─────────────────────────────────
    el.extend(_limitations_section(facts, unassessed, unanalysable, h2, body, _muted))

    # ── Certification summary band ───────────────────────────────────────────
    el.append(Paragraph("Outcome summary", h2))
    el.append(_stat_band([
        Paragraph(f'<font size="22" color="#3B6D11"><b>{pct}%</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">no blocking findings · {cert} of {assessed} assessed</font>', body),
        Paragraph(f'<font size="22"><b>{avg}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">average score / 100'
                  + (f' · {total_eval} criteria evaluated' if total_eval else '')
                  + '</font>', body),
        Paragraph(f'<font size="22" color="#854F0B"><b>{counts.get("issues", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">documents with open findings</font>', body),
        Paragraph(f'<font size="22" color="#9a948f"><b>{counts.get("unanalysable", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">could not be analysed</font>', body),
    ], []))

    # ── P-11: Criteria outcome breakdown ─────────────────────────────────────
    # Complements the document-level stat band above: shows how many WCAG criteria were
    # handled by the deterministic/AI engine vs. deferred to humans vs. skipped entirely.
    _scope_facts = (facts or {}).get("scope") or {}
    _catalog_size = _scope_facts.get("catalog_size", 0)
    _not_eval_ct = len(_scope_facts.get("not_evaluated_criteria") or [])
    _human_only_ct = len(_scope_facts.get("human_only_criteria") or [])
    _with_findings = len(set(open_fails) | set(resolved_crit))
    _passed_auto = max(0, _catalog_size - _not_eval_ct - _human_only_ct - _with_findings)
    if _catalog_size:
        el.append(_stat_band([
            Paragraph(f'<font size="18" color="#3B6D11"><b>{_passed_auto}</b></font><br/>'
                      f'<font size="8.5" color="#6c6470">criteria — no findings</font>', body),
            Paragraph(f'<font size="18"><b>{_with_findings}</b></font><br/>'
                      f'<font size="8.5" color="#6c6470">criteria with findings</font>', body),
            Paragraph(f'<font size="18" color="#6c6470"><b>{_human_only_ct}</b></font><br/>'
                      f'<font size="8.5" color="#6c6470">require human review</font>', body),
            Paragraph(f'<font size="18" color="#9a948f"><b>{_not_eval_ct}</b></font><br/>'
                      f'<font size="8.5" color="#6c6470">not evaluated for these formats</font>', body),
        ], []))

    # ── P-12: Assessment scope declaration ───────────────────────────────────
    fmt_counts: dict[str, int] = {}
    for f in files:
        fmt_counts[_fmt(f)] = fmt_counts.get(_fmt(f), 0) + 1
    fmt_str = " · ".join(f"{n} {k}" for k, n in sorted(fmt_counts.items(), key=lambda x: -x[1])) or "—"
    el.extend(_assessment_scope_block(run, meta, facts, fmt_str, h2, body, cell, _muted,
                                      rendered_at=_rendered_at))

    # ── Compliance velocity — trend vs the caller's previous scan ────────────
    # Best-effort and lazy: rendering must never fail because history is absent,
    # and build_report stays callable with plain dicts (tests, previews).
    diff = None
    try:
        import core
        owner = run.get("owner_email")
        ids = [s["id"] for s in core.store.list_scans(owner=owner)]
        i = ids.index(run["id"]) if run["id"] in ids else -1
        prev = ids[i + 1] if 0 <= i and i + 1 < len(ids) else None
        diff = core.store.get_scan_diff(run["id"], prev, owner=owner) if prev else None
    except Exception:
        diff = None
    if diff:
        s = diff["summary"]
        el.append(Paragraph(
            f"Compliance velocity · since the previous scan ({(diff.get('prev_at') or '')[:10]})", h2))
        vt = Table([[f"▲ {s['improved']} improved", f"▼ {s['regressed']} regressed",
                     f"+ {s['new']} new files", f"− {s['removed']} removed"]],
                   colWidths=[1.85 * inch] * 4)
        vt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10.5), ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (0, 0), GREEN), ("TEXTCOLOR", (1, 0), (1, 0), RED),
            ("TEXTCOLOR", (2, 0), (2, 0), BLUE), ("TEXTCOLOR", (3, 0), (3, 0), MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ]))
        el.append(vt)
        if diff.get("regressed"):
            rr = [["Regressed file", "Prev", "Now", "Δ"]] + [
                [Paragraph(x["file"], cell), x["prev"], x["cur"], x["delta"]]
                for x in diff["regressed"][:5]]
            rt = Table(rr, colWidths=[4.35 * inch, 0.8 * inch, 0.8 * inch, 0.8 * inch])
            rt.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("TEXTCOLOR", (3, 1), (3, -1), RED), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            el.append(Spacer(1, 6))
            el.append(rt)

    # ── Charts row: status donut + OPEN-severity split ───────────────────────
    sev_present = [(s, open_sev[s]) for s in SEV_ORDER if open_sev.get(s)]
    sev_rows = [["Open finding severity", "Count"]] + (
        [[s.title(), n] for s, n in sev_present] or [["No open findings", 0]])
    sev_t = Table(sev_rows, colWidths=[1.55 * inch, 0.85 * inch])
    sev_style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for r, (s, _) in enumerate(sev_present, start=1):
        sev_style.append(("TEXTCOLOR", (0, r), (0, r), SEV_COLOR.get(s, GREY)))
        sev_style.append(("FONTNAME", (0, r), (0, r), "Helvetica-Bold"))
    if not sev_present:
        sev_style.append(("TEXTCOLOR", (0, 1), (0, 1), GREEN))
    sev_t.setStyle(TableStyle(sev_style))
    charts = Table([[_donut(counts), sev_t]], colWidths=[3.6 * inch, 3.5 * inch])
    charts.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 8)]))
    el.append(Paragraph("Document status &amp; open-finding severity", h2))
    el.append(charts)

    # ── Remediation outcomes — what the platform already cleared ─────────────
    if resolved_total:
        el.append(Paragraph("Remediation outcomes · findings ACP cleared and re-verified", h2))
        el.append(Paragraph(
            f'<font color="#3B6D11"><b>✓ {resolved_total} finding(s) cleared</b></font> across '
            f'{remediated_docs or cert} document(s) with no blocking findings, by criterion:', body))
        rows = [["Criterion", "Level", "Findings cleared"]] + [
            [_crit_name(c), WCAG_META.get(c, ("", "", ""))[1] or "—", n]
            for c, n in sorted(resolved_crit.items(), key=lambda x: -x[1])]
        rmt = Table(rows, colWidths=[4.2 * inch, 0.9 * inch, 1.4 * inch])
        rmt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TEXTCOLOR", (2, 1), (2, -1), GREEN), ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, -1), GREENBG),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        el.append(Spacer(1, 6))
        el.append(rmt)

    # ── Open findings by criterion (with WCAG level + description) ───────────
    el.append(Paragraph("Where open findings concentrate · WCAG 2.1 criteria by affected documents", h2))
    if open_fails:
        el.append(_crit_bars(open_fails, total))
        rows = [["Criterion", "Level", "What it requires", "Docs", "% of estate"]] + [
            [_crit_name(c), WCAG_META.get(c, ("", "", ""))[1] or "—",
             Paragraph(WCAG_META.get(c, ("", "", ""))[2] or "", cellm), n, f"{round(n / total * 100)}%"]
            for c, n in sorted(open_fails.items(), key=lambda x: -x[1])]
        ct = Table(rows, colWidths=[2.05 * inch, 0.5 * inch, 2.85 * inch, 0.5 * inch, 0.8 * inch])
        ct.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        el.append(Spacer(1, 6))
        el.append(ct)
    else:
        el.append(Paragraph(
            '<font color="#3B6D11"><b>✓ No open findings.</b></font> Every analysed document '
            "came back clear at the target level: no unresolved failure remains among the "
            "criteria ACP checked.", body))

    # ── Triage & remediation decisions (time-travel snapshot) ────────────────
    if decisions:
        tri = {"inscope": 0, "na": 0, "defer": 0}
        actions = 0
        for m in decisions.values():
            if m.get("triage") in tri:
                tri[m["triage"]] += 1
            if m.get("action"):
                actions += 1
        if tri["inscope"] or tri["na"] or tri["defer"] or actions:
            el.append(Paragraph("Triage &amp; remediation decisions · operator audit trail", h2))
            drows = [["In scope", "N/A", "Deferred", "Remediation decisions"],
                     [tri["inscope"], tri["na"], tri["defer"], actions]]
            dt = Table(drows, colWidths=[1.85 * inch] * 4)
            dt.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, 0), 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONTSIZE", (0, 1), (-1, 1), 15), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (0, 1), GREEN),
                ("BACKGROUND", (0, 0), (-1, -1), CARD), ("BOX", (0, 0), (-1, -1), 0.75, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ]))
            el.append(dt)

    # ── File inventory (R6) ──────────────────────────────────────────────────
    # Per document: what was found, what was verifiably fixed, what is still open, and
    # whether a human signed anything off — instead of a bare finding count.
    el.append(Paragraph("File inventory", h2))
    ordered = sorted(files, key=lambda x: (_status(x) != "issues", x["file"]))   # open findings first
    by_file = {d["file"]: d for d in (facts or {}).get("documents", [])}
    rows = [["File", "Type", "Extent", "Status", "Score", "Findings", "Fixed", "Open", "Approvals"]]
    for f in ordered:
        st = _status(f)
        issues = f.get("issues") or []
        if st == "certifiable" and issues:
            find = "remediated" if (f.get("remediated_at") or f.get("drive_write_url")) else "non-blocking"
        elif issues:
            find = f"{len(issues)} open finding(s)"
        elif f["status"] == "error":
            find = "could not analyse"
        elif st == NOT_ASSESSED:
            # Same fall-through as the app's inventory row: with no findings and no score, this
            # cell printed "clean" beside a "—" score, in the certified PDF. A document that was
            # never opened has no findings COUNT; that is not the same as having no findings.
            find = "not assessed"
        else:
            find = "clean"
        # Counted per document (R6): verifiably-cleared fixes, criteria still failing, and
        # human sign-offs. A separate "validation" column would be redundant — a document is
        # validated exactly when Open is 0, and it can never read clear while findings remain.
        d = by_file.get(f["file"])
        if f["status"] == "error" or not d:
            fixed = still_open = approvals = "—"
        else:
            fixed, still_open, approvals = str(d["remediated"]), str(d["remaining"]), str(d["approvals"])
        rows.append([Paragraph(f["file"], cell), _fmt(f), _extent(f), STATUS_LABEL.get(st, st),
                     ("—" if f.get("score") is None else str(f["score"])), find,
                     fixed, still_open, approvals])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ]
    for r, f in enumerate(ordered, start=1):
        style.append(("TEXTCOLOR", (3, r), (3, r), STATUS_COLOR.get(_status(f), MUTED)))
    ft = Table(rows, colWidths=[1.85 * inch, 0.45 * inch, 0.6 * inch, 0.95 * inch, 0.45 * inch,
                                1.15 * inch, 0.5 * inch, 0.5 * inch, 0.65 * inch], repeatRows=1)
    ft.setStyle(TableStyle(style))
    el.append(ft)

    # ── Scope of assertion / negative assurance (R-A) ────────────────────────
    el.extend(_scope_section(files, facts, h2, body, cell, _muted))

    # ── Pass rate by WCAG principle / POUR (R8) ──────────────────────────────
    el.extend(_pour_section(facts, h2, body, cell, _muted))

    # ── Per-criterion compliance table (backlog R14) ──────────────────────────
    # Scoped to criteria that fired at least one finding — a 87-row dump of every evaluated
    # criterion would be noise. Only the ones with evidence land here.
    el.extend(_criterion_compliance_section(files, h2, body, cell, _muted))

    # ── Remediation evidence appendix (backlog R1) ───────────────────────────
    # Applied-and-verified fixes vs proposals awaiting approval, kept strictly apart.
    # Sits before the conformance statement so the closing attestation is the last word.
    foot_style = ParagraphStyle("evfoot", parent=ss["Normal"], textColor=MUTED,
                                fontSize=8, leading=11.5)
    # The human-task roll-up leads: what changed, by section of the document, in plain language.
    # The per-finding detail (with WCAG ids, before/after and sign-off) follows for the auditor.
    el.extend(_work_by_category_section(evidence or [], h2, body, cell, _muted))
    el.extend(_evidence_section(evidence or [], h2, body, cell, foot_style))

    # ── How this result was produced — method, pipeline & reproducibility (R11/R12/R-D/R-E) ──
    el.extend(_provenance_section(run, facts, meta, diff, cert, total, h2, body, cell, _muted))

    # ── Human review & assurance (R9/R10) ────────────────────────────────────
    _hitl: dict | None = None
    try:
        import core as _core
        _hitl = _core.store.hitl_analytics(run["id"])
    except Exception:
        pass
    el.extend(_assurance_section(facts, h2, body, cell, _muted, hitl=_hitl))

    # ── How to verify this independently (R13) ───────────────────────────────
    el.extend(_manual_verification_section(files, h2, body, cell, _muted))

    # ── AI governance & provenance (ADR 0019 §4/§7) ──────────────────────────
    # The network-boundary + cost attestation enterprise procurement asks for, from the real
    # per-scan ai_calls record — placed before the closing statement so the governance story
    # is part of the certification evidence, not an afterthought.
    el.extend(_ai_governance_section(run, h2, body, cell, _muted))

    # ── Conformance statement & how to read this report ──────────────────────
    el.append(Spacer(1, 14))
    el.append(Paragraph("What this report is, and is not", h2))
    el.append(Paragraph(
        f"Based on this scan, <b>{cert} of {assessed}</b> assessed document(s) returned no "
        f"automated failures among the <b>{std}</b> criteria ACP evaluated. This is a record of "
        "what was detected, what was changed and what was re-checked afterwards — "
        "machine-generated audit evidence produced by an automated + AI-assisted pipeline. It is not a conformance "
        "determination: ACP does not assert that a document satisfies WCAG, and this report does "
        "not constitute a legal conformance guarantee or a signed VPAT. A qualified reviewer "
        "should confirm AI-assisted judgements before any external attestation.", body))
    el.append(Spacer(1, 8))
    el.append(Paragraph(
        "<b>Reading this report.</b> <b>No blocking findings</b> = nothing blocking fired among "
        "the criteria ACP checked at the target level — not a statement that the document "
        "conforms. <b>Open findings</b> = unresolved failures ACP detected and did not clear. "
        "<b>Remediated</b> = the platform wrote a corrected copy and re-checked it, and the "
        "finding no longer fires. <b>Uncertain</b> = a rule could not evaluate, so the score is "
        "an upper bound; <b>could not analyse</b> = the file could not be opened. ACP asserts "
        "nothing about either of the last two. "
        "Severity follows the axe-core impact model (user impact × reach × WCAG level). "
        "Results are reproducible from the stamped rubric hash above.", note))

    # ── Verify this report (R15) ─────────────────────────────────────────────
    el.extend(_verify_section(run["id"], _content_digest(run, files, meta), h2, body, note))

    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
