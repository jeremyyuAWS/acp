"""Branded PDF conformance report (reportlab) — the exportable audit evidence.

Renders a scan run as a designed, chart-led report: logo header, plain-language
verdict, certification summary band, scope & methodology, compliance velocity,
status donut + severity split, remediation outcomes, open findings by criterion,
the decisions snapshot (time-travel), the full file inventory, and the per-issue
remediation evidence appendix. Reproducible from the stamped rubric hash. Footer
carries page numbers and the generation stamp on every page.

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
import io
from pathlib import Path

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (HRFlowable, Image, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

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

STATUS_COLOR = {"certifiable": GREEN, "issues": AMBER, "uncertain": BLUE, "unanalysable": GREY}
STATUS_LABEL = {"certifiable": "certifiable", "issues": "open findings",
                "uncertain": "uncertain", "unanalysable": "could not analyse"}
SEV_COLOR = {"CRITICAL": RED, "SERIOUS": AMBER, "MODERATE": BLUE, "MINOR": GREY}
SEV_ORDER = ["CRITICAL", "SERIOUS", "MODERATE", "MINOR"]


def _crit_name(c):
    return WCAG_META.get(c, (str(c).replace("SC_", "").replace("_", "."), "", ""))[0]


def _status(f):
    # Mirrors the frontend's statusOf (FileDrawer.jsx) so the report and the app
    # always classify a file identically.
    if f["status"] == "error":
        return "unanalysable"
    if f["status"] == "uncertain":
        return "uncertain"
    return "certifiable" if f["compliant"] else "issues"


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
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(0.7 * inch, 0.45 * inch, LETTER[0] - 0.7 * inch, 0.45 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.7 * inch, 0.31 * inch, "mova.io · Accessibility Compliance Platform · confidential")
    canvas.drawRightString(LETTER[0] - 0.7 * inch, 0.31 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _esc(s) -> str:
    """Escape for reportlab's mini-HTML paragraph markup; bound the length."""
    if s is None or s == "":
        return "—"
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))[:400]


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
            if e.get("decision"):
                # Attribution is only ever what decision_log recorded — the authenticated
                # reviewer's email, or the literal 'reviewer' when the platform had no
                # signed-in identity to record. Never an invented name.
                sign_off = f"{e['decision']} by {e.get('reviewer') or 'reviewer'}" + (f" · {when} UTC" if when else "")
            else:
                sign_off = "auto-applied (deterministic fixer) — no human decision recorded"
            lines = [
                Paragraph(f"<b>{_esc(e['criterion'])}</b> &nbsp;<font color='#3B6D11'>✓ validated on re-scan</font>", cell),
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
            lines = [Paragraph(
                f"<b>{_esc(p['criterion'])}</b> &nbsp;<font color='#854F0B'>proposed — not remediated "
                f"({note})</font>", cell)]
            for pr in p["proposals"][:6]:
                why = f" <font color='#6c6470'>— {_esc(pr.get('rationale'))}</font>" if pr.get("rationale") else ""
                lines.append(Paragraph(f"<font color='#6c6470'>Proposed</font> &nbsp;{_esc(pr.get('proposed_value'))}{why}", cell))
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
            "documents. The remainder are available via the per-file remediation API.", muted))
    return el


def _donut(counts: dict[str, int]) -> Drawing:
    """Status split donut + legend, drawn as one Drawing so it flows as a block."""
    d = Drawing(250, 130)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 5, 15, 100, 100
    order = [k for k in ("certifiable", "issues", "uncertain", "unanalysable") if counts.get(k)]
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


def build_report(run: dict, files: list, meta: dict, decisions: dict | None = None,
                 evidence: list | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=f"mova.io conformance report {run['id']}",
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
    when = run["completed_at"][:19].replace("T", " ")
    title_block = [
        Paragraph("Accessibility Conformance Report", H),
        Paragraph(f"{std} · generated {when} UTC", sub),
    ]
    logo = Image(str(LOGO), width=1.32 * inch, height=1.32 * inch * 264 / 800) if LOGO.exists() else Spacer(1, 1)
    head = Table([[logo, title_block]], colWidths=[1.55 * inch, 5.55 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (0, 0), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    el.append(head)
    el.append(HRFlowable(width="100%", thickness=1.2, color=PLUM, spaceBefore=6, spaceAfter=10))
    el.append(Paragraph(
        f"Scan <b>{run['id']}</b> · rubric v{meta.get('version', '—')} · stamped hash <b>{meta.get('hash', '—')}</b> — "
        "results are reproducible from this hash. Scans run read-only; documents are never retained.", sub))

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
    pct = round(cert / total * 100)
    avg = "—" if run.get("avg_score") is None else run["avg_score"]
    resolved_total = sum(resolved_crit.values())

    # ── Executive summary — plain-language verdict ───────────────────────────
    if counts.get("issues") or counts.get("uncertain") or counts.get("unanalysable"):
        verdict = (f"<b>{cert} of {total}</b> analysed document(s) meet {std} with zero "
                   f"open blocking findings and are certifiable. "
                   f"<b>{counts.get('issues', 0)}</b> document(s) still carry open findings "
                   f"({open_findings} total)")
        if counts.get("uncertain"):
            verdict += f", <b>{counts['uncertain']}</b> could not be fully evaluated"
        if counts.get("unanalysable"):
            verdict += f", and <b>{counts['unanalysable']}</b> could not be opened"
        verdict += "."
    else:
        verdict = (f"All <b>{total}</b> analysed document(s) meet {std} with zero open "
                   "blocking findings and are certifiable.")
    if remediated_docs:
        verdict += (f" {remediated_docs} document(s) were remediated by the platform, "
                    f"clearing {resolved_total} finding(s).")
    el.append(Paragraph(verdict, lead))

    # ── Certification summary band ───────────────────────────────────────────
    el.append(Paragraph("Certification summary", h2))
    el.append(_stat_band([
        Paragraph(f'<font size="22" color="#3B6D11"><b>{pct}%</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">certifiable · {cert} of {total} documents</font>', body),
        Paragraph(f'<font size="22"><b>{avg}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">average score / 100</font>', body),
        Paragraph(f'<font size="22" color="#854F0B"><b>{counts.get("issues", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">documents with open findings</font>', body),
        Paragraph(f'<font size="22" color="#9a948f"><b>{counts.get("unanalysable", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">could not be analysed</font>', body),
    ], []))

    # ── Scope & methodology ──────────────────────────────────────────────────
    fmt_counts: dict[str, int] = {}
    for f in files:
        fmt_counts[_fmt(f)] = fmt_counts.get(_fmt(f), 0) + 1
    fmt_str = " · ".join(f"{n} {k}" for k, n in sorted(fmt_counts.items(), key=lambda x: -x[1])) or "—"
    el.append(Paragraph("Scope &amp; methodology", h2))
    scope = Table([[
        Paragraph("<b>Standard</b><br/>"
                  f'<font color="#6c6470">' + std + ', the ADA / EAA reference standard</font>', cell),
        Paragraph("<b>Documents in scope</b><br/>"
                  f'<font color="#6c6470">{total} document(s) — {fmt_str}</font>', cell),
        Paragraph("<b>Method</b><br/>"
                  '<font color="#6c6470">Deterministic engine checks + AI-assisted review of '
                  'semantic criteria; read-only, documents never retained</font>', cell),
    ]], colWidths=[2.35 * inch] * 3)
    scope.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ZEBRA), ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    el.append(scope)

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
        el.append(Paragraph("Remediation outcomes · findings cleared before certification", h2))
        el.append(Paragraph(
            f'<font color="#3B6D11"><b>✓ {resolved_total} finding(s) cleared</b></font> across '
            f'{remediated_docs or cert} certifiable document(s), by criterion:', body))
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
            '<font color="#3B6D11"><b>✓ No open findings.</b></font> Every analysed document is '
            "certifiable at the target level; there are no unresolved WCAG failures to address.", body))

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

    # ── File inventory ───────────────────────────────────────────────────────
    el.append(Paragraph("File inventory", h2))
    ordered = sorted(files, key=lambda x: (_status(x) != "issues", x["file"]))   # open findings first
    rows = [["File", "Type", "Extent", "Status", "Score", "Findings"]]
    for f in ordered:
        st = _status(f)
        issues = f.get("issues") or []
        if st == "certifiable" and issues:
            find = "remediated" if (f.get("remediated_at") or f.get("drive_write_url")) else "non-blocking"
        elif issues:
            find = f"{len(issues)} open finding(s)"
        elif f["status"] == "error":
            find = "could not analyse"
        else:
            find = "clean"
        rows.append([Paragraph(f["file"], cell), _fmt(f), _extent(f), STATUS_LABEL.get(st, st),
                     ("—" if f.get("score") is None else str(f["score"])), find])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ]
    for r, f in enumerate(ordered, start=1):
        style.append(("TEXTCOLOR", (3, r), (3, r), STATUS_COLOR.get(_status(f), MUTED)))
    ft = Table(rows, colWidths=[2.7 * inch, 0.55 * inch, 0.7 * inch, 1.05 * inch, 0.5 * inch, 1.6 * inch],
               repeatRows=1)
    ft.setStyle(TableStyle(style))
    el.append(ft)

    # ── Remediation evidence appendix (backlog R1) ───────────────────────────
    # Applied-and-verified fixes vs proposals awaiting approval, kept strictly apart.
    # Sits before the conformance statement so the closing attestation is the last word.
    foot_style = ParagraphStyle("evfoot", parent=ss["Normal"], textColor=MUTED,
                                fontSize=8, leading=11.5)
    el.extend(_evidence_section(evidence or [], h2, body, cell, foot_style))

    # ── Conformance statement & how to read this report ──────────────────────
    el.append(Spacer(1, 14))
    el.append(Paragraph("Conformance statement &amp; notes", h2))
    el.append(Paragraph(
        f"Based on this scan, <b>{cert} of {total}</b> document(s) conform to {std} with no "
        "open blocking findings and may be certified. This is machine-generated audit evidence produced by "
        "an automated + AI-assisted pipeline; it supports, but does not by itself constitute, a legal "
        "conformance guarantee or a signed VPAT. A qualified reviewer should confirm AI-assisted judgements "
        "before external attestation.", body))
    el.append(Spacer(1, 8))
    el.append(Paragraph(
        "<b>Reading this report.</b> <b>Certifiable</b> = zero open blocking findings at the target level. "
        "<b>Open findings</b> = unresolved WCAG failures on a non-certifiable document. "
        "<b>Remediated</b> = the platform wrote a corrected copy and the file re-passed. "
        "<b>Uncertain</b> = a rule could not evaluate, so the score is an upper bound; "
        "<b>could not analyse</b> = the file could not be opened. Neither of the last two is certified conformant. "
        "Severity follows the axe-core impact model (user impact × reach × WCAG level). "
        "Results are reproducible from the stamped rubric hash above.", note))

    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
