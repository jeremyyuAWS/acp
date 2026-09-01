"""Tagged PDF conformance report — Chromium-based HTML→PDF pipeline.

Replaces the reportlab path for the main /scans/{sid}/report.pdf endpoint.
Chromium's --generate-tagged-pdf flag maps HTML semantic elements to a real
PDF /StructTreeRoot, so screen readers can navigate headings and tables and
the document passes the pdf.tagged (1.3.1) rule that ACP enforces on customer
files.

ReportLab 4.5.1 emits no BDC/EMC content markers, so its output has no
MCIDs for a structure tree to reference — that is the gap this module closes
(see tests/test_report_is_itself_accessible.py, test_untagged_is_still_the_open_finding).

The HTML report covers the same information as the reportlab version:
  - Scan identity and metadata
  - Certification decision
  - File inventory (score, open issues)
  - Open findings summary (by criterion)
  - Scope of assertion and methodology
  - AI governance summary (when facts available)

Charts are inline SVG with aria-label / <title> so Chromium tags them as
/Figure elements with accessible names — the bar charts and donut are
described structurally, not as pixel art.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, BaseLoader

_CHROMIUM = os.environ.get(
    "ACP_CHROMIUM",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
)

_LOGO = Path(__file__).resolve().parent / "assets" / "mova-logo.png"

REPORT_LANG = "en-US"


def _logo_data_uri() -> str:
    if _LOGO.exists():
        data = base64.b64encode(_LOGO.read_bytes()).decode()
        return f"data:image/png;base64,{data}"
    return ""


# ── Severity ordering ────────────────────────────────────────────────────────

_SEV_ORDER = {"CRITICAL": 0, "SERIOUS": 1, "MODERATE": 2, "MINOR": 3}


def _sev_label(s: str) -> str:
    return (s or "").capitalize()


# ── Inline SVG helpers ───────────────────────────────────────────────────────

def _score_ring(score: int) -> str:
    """A simple circular gauge SVG for a 0-100 score.

    The ring is a /Figure element in the tagged PDF; Chromium assigns the
    aria-label as its /Alt entry.
    """
    r = 36
    circ = 2 * 3.14159 * r
    filled = circ * max(0, min(100, score)) / 100
    color = "#3B6D11" if score >= 80 else "#854F0B" if score >= 60 else "#A32D2D"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"
  role="img" aria-label="Score: {score} out of 100"
  style="display:block;margin:0 auto">
  <title>Score: {score} out of 100</title>
  <circle cx="48" cy="48" r="{r}" fill="none" stroke="#e0dbe4" stroke-width="8"/>
  <circle cx="48" cy="48" r="{r}" fill="none" stroke="{color}" stroke-width="8"
    stroke-dasharray="{filled:.1f} {circ:.1f}"
    stroke-dashoffset="{circ * 0.25:.1f}" stroke-linecap="round"/>
  <text x="48" y="52" text-anchor="middle" font-size="18" font-weight="bold"
    fill="{color}">{score}</text>
</svg>"""


def _horiz_bars(by_crit: list[tuple[str, int, int]]) -> str:
    """Horizontal bar chart: list of (criterion_name, count, max_count).

    Each bar row is wrapped in a <g> with a descriptive aria-label.
    The outer SVG is a /Figure; the text labels inside it are also tagged.
    """
    if not by_crit:
        return ""
    row_h = 22
    label_w = 130
    bar_max_w = 220
    height = max(60, len(by_crit) * row_h + 20)
    total_w = label_w + bar_max_w + 50
    max_val = max(c for _, c, _ in by_crit) or 1
    rows = []
    for i, (name, count, _) in enumerate(by_crit):
        y = 10 + i * row_h
        bar_w = int(bar_max_w * count / max_val)
        rows.append(
            f'<g aria-label="{name}: {count} file{"s" if count != 1 else ""}">'
            f'<text x="{label_w - 6}" y="{y + 14}" text-anchor="end" font-size="10"'
            f' fill="#46303F">{name}</text>'
            f'<rect x="{label_w}" y="{y + 4}" width="{bar_w}" height="13"'
            f' fill="#854F0B" rx="2"/>'
            f'<text x="{label_w + bar_w + 4}" y="{y + 14}" font-size="9"'
            f' fill="#6B6670">{count}</text>'
            f'</g>'
        )
    rows_str = "\n".join(rows)
    summary = ", ".join(f"{name}: {count}" for name, count, _ in by_crit[:5])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{height}"
  role="img" aria-label="Open issues by criterion: {summary}"
  style="overflow:visible">
  <title>Open issues by criterion: {summary}</title>
  {rows_str}
</svg>"""


# ── HTML template ────────────────────────────────────────────────────────────

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
<meta charset="UTF-8">
<title>{{ page_title }}</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
@page { size: Letter; margin: 0.7in 0.7in 0.75in 0.7in; }
body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 9.5pt;
  color: #2B2330;
  line-height: 1.45;
  background: #fff;
}
header { display: flex; align-items: center; gap: 14px; padding-bottom: 8px;
         border-bottom: 1.5px solid #46303F; margin-bottom: 10px; }
header img { width: 52px; height: auto; flex-shrink: 0; }
.header-text h1 { font-size: 15pt; color: #46303F; font-weight: 700; margin-bottom: 2px; }
.header-sub { font-size: 8pt; color: #6B6670; }
h2 { font-size: 11.5pt; color: #46303F; font-weight: 600; margin: 18px 0 6px; }
h3 { font-size: 9.5pt; color: #46303F; font-weight: 600; margin: 10px 0 4px; }
p { margin-bottom: 6px; }
.muted { color: #6B6670; font-size: 8.5pt; }

/* Decision card */
.decision-card {
  display: flex; gap: 20px; align-items: center;
  background: #f6f3f7; border: 1px solid #e4e0e8; border-radius: 4px;
  padding: 12px 16px; margin: 10px 0;
}
.decision-label { font-size: 8pt; color: #6B6670; text-transform: uppercase;
                  letter-spacing: .04em; margin-bottom: 2px; }
.decision-value { font-size: 14pt; font-weight: 700; color: #46303F; }
.certifiable { color: #3B6D11; }
.not-certifiable { color: #A32D2D; }

/* Tables */
table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 8.5pt; }
caption { text-align: left; font-weight: 600; font-size: 9pt; color: #46303F;
          padding-bottom: 4px; }
th { background: #f0edf2; color: #46303F; font-weight: 600; text-align: left;
     padding: 5px 8px; border-bottom: 1.5px solid #c8c2cc; }
td { padding: 4px 8px; border-bottom: 1px solid #e4e0e8; vertical-align: top; }
tr:last-child td { border-bottom: none; }
tr:nth-child(even) td { background: #faf8fb; }
.score-ok { color: #3B6D11; font-weight: 600; }
.score-warn { color: #854F0B; font-weight: 600; }
.score-bad { color: #A32D2D; font-weight: 600; }
.cert-yes { color: #3B6D11; }
.cert-no  { color: #A32D2D; }
.sev-critical { color: #A32D2D; font-weight: 600; }
.sev-serious  { color: #854F0B; font-weight: 600; }
.sev-moderate { color: #2B2330; }
.sev-minor    { color: #6B6670; }

figure { margin: 10px 0; }
figcaption { font-size: 8pt; color: #6B6670; margin-top: 4px; }

section { page-break-inside: avoid; }
.page-break { page-break-before: always; }
.scope-list { list-style: disc; padding-left: 18px; font-size: 8.5pt;
              color: #2B2330; line-height: 1.5; }
dl { font-size: 8.5pt; }
dt { font-weight: 600; color: #46303F; margin-top: 6px; }
dd { color: #2B2330; margin-left: 12px; }
</style>
</head>
<body>
<header>
  {% if logo_uri %}
  <img src="{{ logo_uri }}" alt="mova.io logo" width="52">
  {% endif %}
  <div class="header-text">
    <h1>Accessibility Assessment Report</h1>
    <p class="header-sub">
      {{ std }} · Assessment completed {{ assessment_completed }} UTC ·
      Report generated {{ report_generated_at }} UTC
    </p>
  </div>
</header>

<p class="muted">
  Scan <strong>{{ run_id }}</strong> · rubric {{ rubric_display }} ·
  hash <strong>{{ rubric_hash }}</strong> — results are reproducible from the rubric hash.
  Scans run read-only; documents are never retained.
</p>

<!-- Certification decision -->
<section aria-labelledby="decision-heading">
<h2 id="decision-heading">Certification Decision</h2>
<div class="decision-card" role="region" aria-label="Certification decision summary">
  <div>
    <div class="decision-label">Files certified</div>
    <div class="decision-value {{ 'certifiable' if certifiable > 0 else 'not-certifiable' }}">
      {{ certifiable }} of {{ total_files }}
    </div>
  </div>
  {% if avg_score is not none %}
  <div>
    <div class="decision-label">Average score</div>
    <div class="decision-value">{{ avg_score }}<span style="font-size:9pt;font-weight:400">%</span></div>
  </div>
  {% endif %}
  <div>
    <div class="decision-label">Open issues</div>
    <div class="decision-value {{ 'not-certifiable' if total_open > 0 else 'certifiable' }}">
      {{ total_open }}
    </div>
  </div>
  {% if avg_score is not none %}
  <figure aria-label="Score ring: {{ avg_score }} out of 100" style="margin:0">
    <figcaption class="muted" style="text-align:center;margin-bottom:4px">Score</figcaption>
    {{ score_ring | safe }}
  </figure>
  {% endif %}
</div>
<p>
  {% if certifiable == total_files and total_open == 0 %}
  All <strong>{{ total_files }}</strong> document{{ 's' if total_files != 1 else '' }}
  certified against {{ std }} criteria within scope.
  {% elif certifiable > 0 %}
  <strong>{{ certifiable }}</strong> of <strong>{{ total_files }}</strong>
  document{{ 's' if total_files != 1 else '' }} certified;
  <strong>{{ total_files - certifiable }}</strong> ha{{ 've' if (total_files - certifiable) != 1 else 's' }}
  open issues requiring remediation.
  {% else %}
  No documents certified. <strong>{{ total_open }}</strong> open
  issue{{ 's' if total_open != 1 else '' }} across
  <strong>{{ total_files }}</strong> document{{ 's' if total_files != 1 else '' }}.
  {% endif %}
  Certification means no blocking issues remain among the criteria evaluated for each file's
  format — not that the document is fully WCAG conformant. Criteria with no validator for that
  format were not evaluated.
</p>
</section>

<!-- File inventory -->
<section aria-labelledby="files-heading">
<h2 id="files-heading">File Inventory</h2>
<table>
  <caption>Files assessed in this scan</caption>
  <thead>
    <tr>
      <th scope="col">File</th>
      <th scope="col">Score</th>
      <th scope="col">Certified</th>
      <th scope="col">Open issues</th>
      <th scope="col">Status</th>
    </tr>
  </thead>
  <tbody>
  {% for f in files %}
  {% set open_n = f.issues | selectattr('blocking', 'defined') | selectattr('blocking') | list | length
                 if f.issues else
                 (f.issues | length if f.issues else 0) %}
  {% set score_cls = 'score-ok' if f.score >= 80 else 'score-warn' if f.score >= 60 else 'score-bad' %}
  {% set cert_cls = 'cert-yes' if f.compliant else 'cert-no' %}
  <tr>
    <td>{{ f.file }}</td>
    <td class="{{ score_cls }}">{{ f.score }}%</td>
    <td class="{{ cert_cls }}">{{ '✓ Yes' if f.compliant else '✗ No' }}</td>
    <td>{{ f.issues | length if f.issues else 0 }}</td>
    <td>{{ f.status | capitalize }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</section>

{% if open_by_crit %}
<!-- Open findings summary -->
<section aria-labelledby="findings-heading">
<h2 id="findings-heading">Open Issues by Criterion</h2>
{% if bars_svg %}
<figure aria-label="Bar chart: open issues by WCAG criterion">
  <figcaption>Files with open issues per criterion</figcaption>
  {{ bars_svg | safe }}
</figure>
{% endif %}
<table>
  <caption>Open issues grouped by WCAG criterion</caption>
  <thead>
    <tr>
      <th scope="col">Criterion</th>
      <th scope="col">Level</th>
      <th scope="col">Severity</th>
      <th scope="col">Files affected</th>
    </tr>
  </thead>
  <tbody>
  {% for row in open_by_crit %}
  {% set sev_cls = 'sev-' + row.severity | lower %}
  <tr>
    <td>{{ row.criterion }}</td>
    <td>{{ row.level }}</td>
    <td class="{{ sev_cls }}">{{ row.severity | capitalize }}</td>
    <td>{{ row.file_count }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</section>
{% endif %}

<!-- Scope of assertion -->
<section aria-labelledby="scope-heading">
<h2 id="scope-heading">Scope of Assertion</h2>
<p>
  This report evaluates a <strong>subset</strong> of {{ std }} criteria — those for which
  this platform has a validator for each document's file format. A 100% score means no
  blocking findings among the criteria evaluated, not full WCAG conformance. The following
  criteria were not evaluated:
</p>
{% if not_evaluated %}
<ul class="scope-list">
{% for sc in not_evaluated %}
  <li>{{ sc }}</li>
{% endfor %}
</ul>
{% else %}
<p class="muted">All criteria in scope were evaluated for at least one file in this scan.</p>
{% endif %}
</section>

<!-- Methodology -->
<section aria-labelledby="method-heading">
<h2 id="method-heading">Methodology</h2>
<dl>
  <dt>Standard</dt>
  <dd>{{ std }}</dd>
  <dt>Rubric</dt>
  <dd>{{ rubric_display }} (hash {{ rubric_hash }})</dd>
  <dt>Scan ID</dt>
  <dd>{{ run_id }}</dd>
  <dt>Assessment completed</dt>
  <dd>{{ assessment_completed }} UTC</dd>
  <dt>Report generated</dt>
  <dd>{{ report_generated_at }} UTC</dd>
  <dt>Scan approach</dt>
  <dd>Automated static analysis. Documents are analysed read-only and are never retained
      after the scan completes.</dd>
</dl>
</section>

{% if ai_summary %}
<!-- AI governance -->
<section aria-labelledby="ai-heading">
<h2 id="ai-heading">AI Governance</h2>
<p>{{ ai_summary }}</p>
</section>
{% endif %}

</body>
</html>
"""


# ── Data preparation ─────────────────────────────────────────────────────────

_WCAG_SC = {
    "SC_1_1_1": ("1.1.1 Non-text Content", "A"),
    "SC_1_3_1": ("1.3.1 Info and Relationships", "A"),
    "SC_1_3_2": ("1.3.2 Meaningful Sequence", "A"),
    "SC_1_4_1": ("1.4.1 Use of Colour", "A"),
    "SC_1_4_3": ("1.4.3 Contrast (Minimum)", "AA"),
    "SC_1_4_4": ("1.4.4 Resize Text", "AA"),
    "SC_1_4_11": ("1.4.11 Non-text Contrast", "AA"),
    "SC_1_4_12": ("1.4.12 Text Spacing", "AA"),
    "SC_2_4_1": ("2.4.1 Bypass Blocks", "A"),
    "SC_2_4_2": ("2.4.2 Page Titled", "A"),
    "SC_2_4_4": ("2.4.4 Link Purpose", "A"),
    "SC_2_4_6": ("2.4.6 Headings and Labels", "AA"),
    "SC_3_1_1": ("3.1.1 Language of Page", "A"),
    "SC_3_1_2": ("3.1.2 Language of Parts", "AA"),
    "SC_4_1_2": ("4.1.2 Name, Role, Value", "A"),
}


def _sc_label(wcag_key: str) -> tuple[str, str]:
    """Returns (display name, level) for a WCAG SC key like 'SC_1_1_1'."""
    return _WCAG_SC.get(wcag_key, (wcag_key.replace("SC_", "").replace("_", "."), ""))


def _prepare_context(run: dict, files: list, meta: dict,
                     facts: dict | None = None) -> dict:
    target = (meta.get("target") or "Level AA").strip()
    std = target if target.upper().startswith("WCAG") else f"WCAG 2.1 {target}"

    completed_raw = run.get("completed_at") or ""
    assessment_completed = completed_raw[:19].replace("T", " ") if completed_raw else "in progress"
    report_generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rubric_name = meta.get("name") or ""
    rubric_display = (f"{rubric_name} v" if rubric_name else "v") + (meta.get("version") or "—")
    rubric_hash = (meta.get("hash") or "—")[:12]

    total_files = len(files)
    certifiable = sum(1 for f in files if f.get("compliant"))
    avg_score = run.get("avg_score")

    # Open issues: aggregate across files.
    #
    # `file_count` counts DISTINCT FILES, not findings. It used to increment once per issue,
    # which agrees with the file count whenever no document carries two findings under the same
    # criterion — true of every fixture in this repo, and of most real scans, so the error stayed
    # invisible. A 37-file scan then reported "2.4.2 Page Titled ... 49" in a column headed
    # "Files affected", because 2.4.2 fired 49 times across those 37 documents.
    #
    # It reaches the reader three ways, all of which say "files": that column, the bar chart
    # captioned "Files with open issues per criterion", and the chart's text alternative, which
    # says "affects the most files, N of M" — where an instance count makes N exceed M and the
    # sentence read aloud becomes arithmetically impossible.
    #
    # `total_open` keeps counting findings: it is the remediation backlog, and deduplicating it
    # would understate the work in the more prominent place.
    open_by_crit_map: dict[str, dict] = {}
    total_open = 0
    for idx, f in enumerate(files):
        fid = f.get("file") or f"\x00idx{idx}"      # unnamed files still count once each
        for issue in (f.get("issues") or []):
            total_open += 1
            wk = issue.get("wcag") or ""
            sev = issue.get("severity") or "MODERATE"
            if wk not in open_by_crit_map:
                name, level = _sc_label(wk)
                open_by_crit_map[wk] = {
                    "criterion": name,
                    "level": level,
                    "severity": sev,
                    "_files": set(),
                    "_sev_order": _SEV_ORDER.get(sev, 99),
                }
            open_by_crit_map[wk]["_files"].add(fid)
    for row in open_by_crit_map.values():
        row["file_count"] = len(row.pop("_files"))

    open_by_crit = sorted(open_by_crit_map.values(),
                          key=lambda r: (r["_sev_order"], r["criterion"]))

    # Bar chart: top 8 criteria
    bar_data = [(r["criterion"], r["file_count"], total_files)
                for r in open_by_crit[:8]]
    bars_svg = _horiz_bars(bar_data) if bar_data else ""

    # Not-evaluated criteria (from facts, or empty)
    not_evaluated: list[str] = []
    if facts:
        ne_set: set[str] = set()
        for fdata in facts.get("files", {}).values():
            for crit in (fdata.get("not_evaluated_criteria") or []):
                ne_set.add(crit)
        not_evaluated = sorted(ne_set)

    # AI governance summary
    ai_summary = ""
    if facts:
        ai_calls = facts.get("ai_calls_total") or 0
        if ai_calls:
            ai_summary = (
                f"This scan used AI assistance for {ai_calls} call"
                f"{'s' if ai_calls != 1 else ''}. "
                "AI-generated proposals were reviewed by a human before being applied."
            )

    return {
        "lang": REPORT_LANG,
        "page_title": f"mova.io Accessibility Assessment Report — {run.get('id', '')}",
        "logo_uri": _logo_data_uri(),
        "std": std,
        "assessment_completed": assessment_completed,
        "report_generated_at": report_generated_at,
        "run_id": run.get("id", ""),
        "rubric_display": rubric_display,
        "rubric_hash": rubric_hash,
        "total_files": total_files,
        "certifiable": certifiable,
        "avg_score": avg_score,
        "total_open": total_open,
        "score_ring": _score_ring(avg_score) if avg_score is not None else "",
        "files": files,
        "open_by_crit": open_by_crit,
        "bars_svg": bars_svg,
        "not_evaluated": not_evaluated,
        "ai_summary": ai_summary,
    }


# ── HTML rendering ───────────────────────────────────────────────────────────

_jinja_env = Environment(loader=BaseLoader(), autoescape=True)
_jinja_env.filters["selectattr"] = lambda seq, attr, *_: [
    item for item in seq if item.get(attr) is not None
]


def _render_html(run: dict, files: list, meta: dict,
                 facts: dict | None = None) -> str:
    ctx = _prepare_context(run, files, meta, facts)
    tmpl = _jinja_env.from_string(_TEMPLATE)
    return tmpl.render(**ctx)


# ── Chromium PDF generation ──────────────────────────────────────────────────

def build_tagged_report(run: dict, files: list, meta: dict,
                        decisions: dict | None = None,
                        evidence: list | None = None,
                        facts: dict | None = None) -> bytes:
    """Generate an accessible (tagged) PDF from an HTML template via Chromium.

    The --generate-tagged-pdf flag maps HTML semantic elements to a real
    /StructTreeRoot with /MarkInfo Marked=true, so the output passes the
    pdf.tagged check (WCAG 1.3.1) that ACP enforces on customer PDFs.

    Raises RuntimeError if Chromium is unavailable or returns a non-zero
    exit code; the caller should fall back to build_report() from report.py.
    """
    if not Path(_CHROMIUM).exists():
        raise RuntimeError(f"Chromium not found at {_CHROMIUM}")

    html = _render_html(run, files, meta, facts)

    with tempfile.TemporaryDirectory(prefix="acp_report_") as td:
        html_path = Path(td) / "report.html"
        pdf_path = Path(td) / "report.pdf"
        html_path.write_text(html, encoding="utf-8")

        result = subprocess.run(
            [
                _CHROMIUM,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--generate-tagged-pdf",
                f"--print-to-pdf={pdf_path}",
                "--print-to-pdf-no-header",
                str(html_path),
            ],
            timeout=45,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Chromium exited {result.returncode}: {result.stderr[:400]}"
            )
        if not pdf_path.exists():
            raise RuntimeError("Chromium produced no output file")

        return pdf_path.read_bytes()
