"""Branded PDF conformance report (reportlab) — the exportable audit evidence.

Renders a scan run as a designed, chart-led report: logo header, certification
summary band, status donut + severity split, top-failing-criteria bar chart,
the decisions snapshot (time-travel), and the full file inventory. Reproducible
from the stamped rubric hash. Footer carries page numbers and the generation
stamp on every page.
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
from reportlab.platypus import (HRFlowable, Image, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

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

LOGO = Path(__file__).resolve().parent / "assets" / "mova-logo.png"

CRIT = {
    "SC_1_1_1": "1.1.1 Non-text Content", "SC_1_3_1": "1.3.1 Info & Relationships",
    "SC_1_3_2": "1.3.2 Meaningful Sequence", "SC_1_4_3": "1.4.3 Contrast (Minimum)",
    "SC_2_2_2": "2.2.2 Pause, Stop, Hide", "SC_2_4_2": "2.4.2 Page Titled",
    "SC_2_4_4": "2.4.4 Link Purpose", "SC_3_1_1": "3.1.1 Language of Page",
    "SC_3_1_2": "3.1.2 Language of Parts", "SC_4_1_2": "4.1.2 Name, Role, Value",
}
STATUS_COLOR = {"certifiable": GREEN, "issues": AMBER, "uncertain": BLUE, "unanalysable": GREY}
SEV_COLOR = {"CRITICAL": RED, "SERIOUS": AMBER, "MODERATE": BLUE, "MINOR": GREY}


def _status(f):
    # Mirrors the frontend's statusOf (FileDrawer.jsx) so the report and the app
    # always classify a file identically.
    if f["status"] == "error":
        return "unanalysable"
    if f["status"] == "uncertain":
        return "uncertain"
    return "certifiable" if f["compliant"] else "issues"


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(0.7 * inch, 0.45 * inch, LETTER[0] - 0.7 * inch, 0.45 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.7 * inch, 0.31 * inch, "mova.io · Accessibility Compliance Platform · confidential")
    canvas.drawRightString(LETTER[0] - 0.7 * inch, 0.31 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


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
    d.add(pie)
    total = sum(counts.values()) or 1
    y = 100
    for k in order:
        d.add(Rect(125, y, 8, 8, fillColor=STATUS_COLOR[k], strokeColor=None))
        d.add(String(139, y + 1, f"{k} · {counts[k]} ({round(counts[k] / total * 100)}%)",
                     fontName="Helvetica", fontSize=8.5, fillColor=PLUM))
        y -= 17
    return d


def _crit_bars(fails: dict[str, int], total_files: int) -> Drawing:
    """Top failing criteria as horizontal bars — the report's 'where to look first'."""
    top = sorted(fails.items(), key=lambda x: -x[1])[:8]
    names = [CRIT.get(c, c).replace("SC_", "").replace("_", ".") for c, _ in top]
    h = max(90, 22 * len(top) + 30)
    d = Drawing(440, h)
    bc = HorizontalBarChart()
    bc.x, bc.y = 150, 12
    bc.width, bc.height = 250, h - 24
    bc.data = [[n for _, n in reversed(top)]]
    bc.categoryAxis.categoryNames = list(reversed(names))
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 8
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


def build_report(run: dict, files: list, meta: dict, decisions: dict | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=f"mova.io conformance report {run['id']}",
                            topMargin=0.6 * inch, bottomMargin=0.75 * inch,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch)
    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Title"], textColor=PLUM, fontSize=20, spaceAfter=1,
                       alignment=0, leading=24)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=MUTED, fontSize=9.5, spaceAfter=0, leading=13)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=PLUM, fontSize=12.5, spaceBefore=18, spaceAfter=7)
    body = ParagraphStyle("body", parent=ss["Normal"], textColor=PLUM, fontSize=9.5, leading=14)
    cell = ParagraphStyle("cell", parent=ss["Normal"], textColor=PLUM, fontSize=8.5, leading=10.5)
    el = []

    # ── Header band: logo + title ────────────────────────────────────────────
    when = run["completed_at"][:19].replace("T", " ")
    title_block = [
        Paragraph("Accessibility Conformance Report", H),
        Paragraph(f"WCAG 2.1 · {meta['target']} · generated {when} UTC", sub),
    ]
    logo = Image(str(LOGO), width=1.32 * inch, height=1.32 * inch * 264 / 800) if LOGO.exists() else Spacer(1, 1)
    head = Table([[logo, title_block]], colWidths=[1.55 * inch, 5.55 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (0, 0), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    el.append(head)
    el.append(HRFlowable(width="100%", thickness=1.2, color=PLUM, spaceBefore=6, spaceAfter=10))
    el.append(Paragraph(
        f"Scan <b>{run['id']}</b> · rubric v{meta['version']} · stamped hash <b>{meta['hash']}</b> — "
        "results are reproducible from this hash. Scans run read-only; documents are never retained.", sub))

    # ── Certification summary ────────────────────────────────────────────────
    counts: dict[str, int] = {}
    sev_counts: dict[str, int] = {}
    for f in files:
        counts[_status(f)] = counts.get(_status(f), 0) + 1
        for i in f["issues"]:
            s = (i.get("severity") or "MINOR").upper()
            sev_counts[s] = sev_counts.get(s, 0) + 1
    cert = counts.get("certifiable", 0)
    total = len(files) or 1
    pct = round(cert / total * 100)
    avg = "—" if run["avg_score"] is None else run["avg_score"]

    el.append(Paragraph("Certification summary", h2))
    band = Table([[
        Paragraph(f'<font size="22" color="#3B6D11"><b>{pct}%</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">certifiable today · {cert} of {total} documents</font>', body),
        Paragraph(f'<font size="22"><b>{avg}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">average score / 100</font>', body),
        Paragraph(f'<font size="22" color="#854F0B"><b>{counts.get("issues", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">documents with blocking findings</font>', body),
        Paragraph(f'<font size="22" color="#9a948f"><b>{counts.get("unanalysable", 0)}</b></font><br/>'
                  f'<font size="8.5" color="#6c6470">could not be analysed</font>', body),
    ]], colWidths=[1.85 * inch] * 4)
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.75, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ]))
    el.append(band)

    # ── Charts row: status donut + severity split ───────────────────────────
    sev_rows = [["Severity", "Findings"]] + [
        [s.title(), n] for s, n in sorted(sev_counts.items(),
                                          key=lambda x: ["CRITICAL", "SERIOUS", "MODERATE", "MINOR"].index(x[0])
                                          if x[0] in ("CRITICAL", "SERIOUS", "MODERATE", "MINOR") else 9)]
    sev_t = Table(sev_rows, colWidths=[1.35 * inch, 0.85 * inch])
    sev_style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for r, (s, _) in enumerate(sorted(sev_counts.items(),
                                      key=lambda x: ["CRITICAL", "SERIOUS", "MODERATE", "MINOR"].index(x[0])
                                      if x[0] in ("CRITICAL", "SERIOUS", "MODERATE", "MINOR") else 9), start=1):
        sev_style.append(("TEXTCOLOR", (0, r), (0, r), SEV_COLOR.get(s, GREY)))
        sev_style.append(("FONTNAME", (0, r), (0, r), "Helvetica-Bold"))
    sev_t.setStyle(TableStyle(sev_style))
    charts = Table([[_donut(counts), sev_t]], colWidths=[3.6 * inch, 3.5 * inch])
    charts.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 8)]))
    el.append(Paragraph("Document status &amp; finding severity", h2))
    el.append(charts)

    # ── Top failing criteria ─────────────────────────────────────────────────
    fails: dict[str, int] = {}
    for f in files:
        for c in {i["wcag"] for i in f["issues"]}:
            fails[c] = fails.get(c, 0) + 1
    if fails:
        el.append(Paragraph("Where failures concentrate · WCAG 2.1 criteria by affected documents", h2))
        el.append(_crit_bars(fails, total))
        rows = [["Criterion", "Documents affected", "% of estate"]] + [
            [CRIT.get(c, c), n, f"{round(n / total * 100)}%"]
            for c, n in sorted(fails.items(), key=lambda x: -x[1])]
        ct = Table(rows, colWidths=[3.4 * inch, 1.6 * inch, 1.0 * inch])
        ct.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        el.append(Spacer(1, 6))
        el.append(ct)

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
    ordered = sorted(files, key=lambda x: x["file"])
    rows = [["File", "Status", "Score", "Findings"]]
    for f in ordered:
        rows.append([Paragraph(f["file"], cell), _status(f),
                     ("—" if f["score"] is None else str(f["score"])),
                     (f"{len(f['issues'])} finding(s)" if f["issues"]
                      else ("could not analyse" if f["status"] == "error" else "clean"))])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ]
    for r, f in enumerate(ordered, start=1):
        style.append(("TEXTCOLOR", (1, r), (1, r), STATUS_COLOR.get(_status(f), MUTED)))
    ft = Table(rows, colWidths=[3.55 * inch, 1.05 * inch, 0.6 * inch, 1.6 * inch], repeatRows=1)
    ft.setStyle(TableStyle(style))
    el.append(ft)

    el.append(Spacer(1, 14))
    el.append(Paragraph(
        "<b>Reading this report.</b> <b>Certifiable</b> = zero blocking findings at the target level. "
        "<b>Uncertain</b> = a rule could not evaluate, so the score is an upper bound; "
        "<b>unanalysable</b> = the file could not be opened. Neither is certified conformant. "
        "Severity follows the axe-core impact model (user impact × reach × WCAG level).",
        ParagraphStyle("foot", parent=ss["Normal"], textColor=MUTED, fontSize=8, leading=11.5)))

    doc.build(el, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
