"""Branded PDF compliance report (reportlab) — the exportable audit evidence.

Renders a scan run as a one/two-page report: rubric stamp, summary, per-WCAG-criterion
breakdown, and the file inventory. Reproducible from the stamped rubric hash.
"""
from __future__ import annotations
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PLUM = colors.HexColor("#46303F")
AMBER = colors.HexColor("#854F0B")
GREEN = colors.HexColor("#3B6D11")
RED = colors.HexColor("#A32D2D")
MUTED = colors.HexColor("#6c6470")
LINE = colors.HexColor("#e0dbe4")
ZEBRA = colors.HexColor("#faf8fb")

CRIT = {
    "SC_1_1_1": "1.1.1 non-text", "SC_1_3_1": "1.3.1 structure", "SC_1_3_2": "1.3.2 reading order",
    "SC_1_4_3": "1.4.3 contrast", "SC_2_2_2": "2.2.2 pause/stop", "SC_2_4_2": "2.4.2 page titled",
    "SC_2_4_4": "2.4.4 link purpose", "SC_3_1_1": "3.1.1 language", "SC_3_1_2": "3.1.2 language of parts",
    "SC_4_1_2": "4.1.2 name/role/value",
}


def _status(f):
    return "unanalysable" if f["status"] == "error" else ("certifiable" if f["compliant"] else "issues")


def build_report(run: dict, files: list, meta: dict, decisions: dict | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=f"acp report {run['id']}",
                            topMargin=0.7 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch)
    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Title"], textColor=PLUM, fontSize=19, spaceAfter=2, alignment=0)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=MUTED, fontSize=9.5, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=PLUM, fontSize=12, spaceBefore=15, spaceAfter=6)
    el = []

    el.append(Paragraph("mova.io — accessibility compliance report", H))
    el.append(Paragraph(
        f"{meta['target']} &nbsp;·&nbsp; rubric v{meta['version']} &nbsp;·&nbsp; hash {meta['hash']} "
        f"&nbsp;·&nbsp; scan {run['id']} &nbsp;·&nbsp; {run['completed_at'][:19].replace('T', ' ')} UTC", sub))

    el.append(Paragraph("Summary", h2))
    avg = "—" if run["avg_score"] is None else run["avg_score"]
    summ = [["Files", "Avg score", "Certifiable", "Uncertain", "Unanalysable"],
            [run["files"], avg, run["certifiable"], run["uncertain"], run["error"]]]
    t = Table(summ, colWidths=[1.28 * inch] * 5)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, 0), 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONTSIZE", (0, 1), (-1, 1), 17), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1), ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("TEXTCOLOR", (2, 1), (2, 1), GREEN), ("TEXTCOLOR", (3, 1), (3, 1), AMBER), ("TEXTCOLOR", (4, 1), (4, 1), RED),
    ]))
    el.append(t)

    fails = {}
    for f in files:
        for c in {i["wcag"] for i in f["issues"]}:
            fails[c] = fails.get(c, 0) + 1
    if fails:
        el.append(Paragraph("WCAG 2.1 criteria failing, by file count", h2))
        rows = [["Criterion", "Files"]] + [[CRIT.get(c, c), n] for c, n in sorted(fails.items(), key=lambda x: -x[1])]
        ct = Table(rows, colWidths=[3.6 * inch, 0.9 * inch])
        ct.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        el.append(ct)

    el.append(Paragraph("File inventory", h2))
    ordered = sorted(files, key=lambda x: x["file"])
    rows = [["File", "Status", "Score", "Findings"]]
    for f in ordered:
        rows.append([f["file"], _status(f), ("—" if f["score"] is None else str(f["score"])),
                     (f"{len(f['issues'])} issue(s)" if f["issues"]
                      else ("could not analyse" if f["status"] == "error" else "clean"))])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ]
    for r, f in enumerate(ordered, start=1):
        st = _status(f)
        style.append(("TEXTCOLOR", (1, r), (1, r), GREEN if st == "certifiable" else AMBER if st == "issues" else MUTED))
    ft = Table(rows, colWidths=[3.0 * inch, 1.1 * inch, 0.7 * inch, 1.55 * inch], repeatRows=1)
    ft.setStyle(TableStyle(style))
    el.append(ft)

    # Triage & remediation decisions (time-travel snapshot) — the operator's audit trail.
    if decisions:
        tri = {"inscope": 0, "na": 0, "defer": 0}
        actions = 0
        for m in decisions.values():
            if m.get("triage") in tri:
                tri[m["triage"]] += 1
            if m.get("action"):
                actions += 1
        if tri["inscope"] or tri["na"] or tri["defer"] or actions:
            el.append(Paragraph("Triage &amp; remediation decisions", h2))
            drows = [["In scope", "N/A", "Deferred", "Remediation decisions"],
                     [tri["inscope"], tri["na"], tri["defer"], actions]]
            dt = Table(drows, colWidths=[1.6 * inch] * 4)
            dt.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONTSIZE", (0, 1), (-1, 1), 14),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (0, 1), GREEN),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, MUTED),
            ]))
            el.append(dt)

    el.append(Spacer(1, 16))
    el.append(Paragraph(
        "Scans run read-only; documents are never retained. Results are reproducible from the stamped rubric "
        "hash. <b>Uncertain</b> = a rule could not evaluate, so the score is an upper bound; "
        "<b>unanalysable</b> = the file could not be opened. Neither is certified compliant.",
        ParagraphStyle("foot", parent=ss["Normal"], textColor=MUTED, fontSize=8, leading=11)))

    doc.build(el)
    return buf.getvalue()
