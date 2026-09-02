"""PDF/UA-1 conformance report — WeasyPrint HTML/CSS → tagged PDF (ADR 0034).

WHY THIS EXISTS, measured rather than assumed. The shipped renderer (`report_tagged.py`)
prints the same HTML through headless Chromium's `--generate-tagged-pdf`. That produces a real
structure tree, and it is genuinely better than the ReportLab path it replaced — but run
against veraPDF 1.30.2 it **fails PDF/UA-1** on two counts:

    clause 7.1 test 8   x1   no XMP metadata stream in the catalog (Chromium writes none)
    clause 7.1 test 3   x7   content neither marked as Artifact nor tagged as real content

The second is Chromium's own print header/footer, which also leaks a local temp path
(`file:///tmp/acp_report_.../report.html`) onto every page of a document handed to a customer's
auditor. The same HTML through WeasyPrint passes PDF/UA-1 with 0 failures, writes XMP, tags
tables as Table/THead/TBody rather than a bare Table, and has no print furniture at all.

WHAT THIS MODULE ADDS ON TOP OF SWAPPING THE ENGINE. WeasyPrint does not tag inline `<svg>`:
rendered as-is, the shipped template's two charts drop out of the structure tree entirely
(1 Figure — the logo — against Chromium's 5). Passing PDF/UA while silently losing the charts
from the reading order is the failure mode this file exists to avoid, so the charts are
reauthored to the pattern ADR 0034's spike verified:

    an <img alt="…conclusion…"> carrying the chart as a data-URI SVG, tagged as a /Figure WITH
    /Alt, beside a real data <table> holding the same numbers.

NOTHING HERE FAKES STRUCTURE. Every tag in the output is derived by WeasyPrint from HTML
semantics. There is no pikepdf post-process bolting a `/StructTreeRoot` onto an untagged file —
that is what `report.py::_tag_pdf` does today, and it is the one option ADR 0034 explicitly
rules out: an empty `/Document` element with an empty ParentTree turns our own detector green
and gives a screen-reader user nothing.

NOT WIRED IN. `ACP_REPORT_RENDERER=weasyprint` selects it; the default is unchanged. The
cutover is gated on checks that cannot run in CI — PAC 2024 and a real NVDA/VoiceOver pass —
see docs/adr/0034 and the reviewer packet built by `scripts/build_report_review_packet.py`.
"""
from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, BaseLoader

# The content model is imported, never re-derived. Two renderers computing "how many files are
# certified" from the same inputs is two chances to disagree, and the disagreement would show up
# as a customer-facing number differing between two PDFs of the same scan.
from report_tagged import (  # noqa: F401  (re-exported for tests)
    REPORT_LANG,
    _logo_data_uri,
    _prepare_context,
    _sc_label,
)


# ── Charts ───────────────────────────────────────────────────────────────────
#
# Each chart is an <img> whose alt states the CONCLUSION, not the mechanics. "Bar chart showing
# criteria" describes the picture; "1.1.1 affects the most files (1 of 3)" is what a reader who
# cannot see it actually needs. The exact numbers live in the adjacent data table, so the alt
# does not have to carry them and does not go stale against it.


def _svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def _score_ring_svg(score: int) -> str:
    r = 36
    circ = 2 * 3.14159 * r
    filled = circ * max(0, min(100, score)) / 100
    color = "#3B6D11" if score >= 80 else "#854F0B" if score >= 60 else "#A32D2D"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
        f'<circle cx="48" cy="48" r="{r}" fill="none" stroke="#e0dbe4" stroke-width="8"/>'
        f'<circle cx="48" cy="48" r="{r}" fill="none" stroke="{color}" stroke-width="8" '
        f'stroke-dasharray="{filled:.1f} {circ:.1f}" stroke-dashoffset="{circ * 0.25:.1f}" '
        f'stroke-linecap="round"/>'
        f'<text x="48" y="52" text-anchor="middle" font-size="18" font-weight="bold" '
        f'font-family="Liberation Sans, DejaVu Sans, sans-serif" fill="{color}">{score}</text>'
        f'</svg>'
    )


def _bars_svg(rows: list[tuple[str, int]]) -> str:
    row_h, label_w, bar_max_w = 22, 130, 220
    height = max(60, len(rows) * row_h + 20)
    total_w = label_w + bar_max_w + 50
    max_val = max((c for _, c in rows), default=1) or 1
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{height}" '
        f'viewBox="0 0 {total_w} {height}" '
        f'font-family="Liberation Sans, DejaVu Sans, sans-serif">'
    ]
    for i, (name, count) in enumerate(rows):
        y = 10 + i * row_h
        bar_w = int(bar_max_w * count / max_val)
        out.append(
            f'<text x="{label_w - 6}" y="{y + 14}" text-anchor="end" font-size="10" '
            f'fill="#46303F">{_x(name)}</text>'
            f'<rect x="{label_w}" y="{y + 4}" width="{bar_w}" height="13" fill="#854F0B" rx="2"/>'
            f'<text x="{label_w + bar_w + 4}" y="{y + 14}" font-size="9" fill="#6B6670">{count}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _x(s: str) -> str:
    """XML-escape for text going inside the SVG. The SVG is base64'd into a data URI, so Jinja's
    autoescaping never sees it — a criterion name containing & or < would otherwise produce an
    SVG that silently fails to parse and a chart that vanishes."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _ring_alt(score: int) -> str:
    band = "meets the 80% threshold" if score >= 80 else (
        "is below the 80% threshold" if score >= 60 else "is well below the 80% threshold")
    return f"Average score {score} out of 100, which {band}."


def _bars_alt(rows: list[tuple[str, int]], total_files: int) -> str:
    """The chart's text alternative — a sentence, read aloud, so it has to parse as one.

    The first draft built the plural by appending "s" to "criterion" and left the verb fixed,
    producing "2 further criterions also has open issues" in the /Alt of a shipped accessibility
    report. Nothing structural would ever have caught it: the Figure had an /Alt, veraPDF was
    happy, and the only reader affected is the one who cannot see the chart. Both the noun and
    the verb inflect here for that reason.
    """
    if not rows:
        return "No criteria have open issues."
    # max BY COUNT, not rows[0]. `rows` arrives sorted by severity, and reading the first row as
    # the largest made the sentence contradict the picture it describes: on a real 37-file scan
    # the alt said "1.3.1 affects the most files, 37 of 37" while the longest bar on the page was
    # 2.4.2 at 49. Both statements came from the same list. A sighted reader sees the chart; the
    # reader this sentence exists for gets the wrong criterion, and nothing structural can tell —
    # the Figure has an /Alt either way. Ties keep the earlier (higher-severity) row.
    top, top_n = max(rows, key=lambda r: r[1])
    others = len(rows) - 1
    if others == 1:
        tail = " 1 further criterion also has open issues."
    elif others > 1:
        tail = f" {others} further criteria also have open issues."
    else:
        tail = ""
    return (f"Open issues by criterion. {top} affects the most files, {top_n} of {total_files}."
            f"{tail} Exact counts follow in the table below.")


# ── Template ─────────────────────────────────────────────────────────────────
#
# Deliberately the shipped template's markup and CSS, changed only where WeasyPrint or PDF/UA
# requires it. A visual-parity rewrite that also restyled would make any difference in the page
# review ambiguous between "the engine renders it differently" and "someone changed the design".

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
<meta charset="UTF-8">
<title>{{ page_title }}</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
@page { size: Letter; margin: 0.7in 0.7in 0.75in 0.7in; }
body {
  /* Written out here rather than interpolated from a constant. A Jinja variable looked
     tidier and was a bug: this environment autoescapes, so the quotes arrived as
     &#34;Liberation Sans&#34; — invalid CSS, silently dropped, and the whole report rendered
     in WeasyPrint's default serif. Nothing structural noticed, because tagging does not
     depend on the font: veraPDF passed with zero failures and every structural test stayed
     green. Only rendering the page and looking at it caught it, which is why the regression
     test asserts the EMBEDDED FONT rather than this string.

     Liberation Sans is metric-compatible with Arial, which is what Chromium rendered with, so
     it is what holds the visual parity. It does not carry U+2713 or U+2717 — the tick and
     cross the File Inventory prints directly, measured with fontTools against the font file
     rather than assumed — so DejaVu Sans follows it purely to supply those two glyphs. Both
     embed; PDF/UA requires embedded fonts. */
  font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
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
a { color: #46303F; }

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

table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 8.5pt; }
caption { text-align: left; font-weight: 600; font-size: 9pt; color: #46303F;
          padding-bottom: 4px; }
th[scope="col"] { background: #f0edf2; color: #46303F; font-weight: 600; text-align: left;
     padding: 5px 8px; border-bottom: 1.5px solid #c8c2cc; }
/* A row header is a TH for the structure tree's sake, and must look like the TD it replaced.
   The shipped Chromium report renders this column as an ordinary cell, and the default TH
   styling above — bold, shaded, heavier rule — is a visual change PDF/UA never asked for:
   14289 wants the cell TAGGED as a header, and says nothing about its weight. Styling all TH
   alike is how a semantics fix quietly becomes a redesign. */
th[scope="row"], td { padding: 4px 8px; border-bottom: 1px solid #e4e0e8; vertical-align: top;
     font-weight: 400; text-align: left; background: none; color: inherit; }
tr:last-child th[scope="row"], tr:last-child td { border-bottom: none; }
tr:nth-child(even) th[scope="row"], tr:nth-child(even) td { background: #faf8fb; }
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

<section>
<h2>Certification Decision</h2>
<div class="decision-card">
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
  {% if ring_uri %}
  <figure style="margin:0">
    <figcaption class="muted" style="text-align:center;margin-bottom:4px">Score</figcaption>
    <img src="{{ ring_uri }}" alt="{{ ring_alt }}" width="96" height="96">
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

<section>
<h2>File Inventory</h2>
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
  {% set score_cls = 'score-ok' if f.score >= 80 else 'score-warn' if f.score >= 60 else 'score-bad' %}
  {% set cert_cls = 'cert-yes' if f.compliant else 'cert-no' %}
  <tr>
    <th scope="row">{{ f.file }}</th>
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
<section>
<h2>Open Issues by Criterion</h2>
{% if bars_uri %}
<figure>
  <figcaption>Files with open issues per criterion</figcaption>
  <img src="{{ bars_uri }}" alt="{{ bars_alt }}" width="{{ bars_w }}" height="{{ bars_h }}">
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
    <th scope="row">{{ row.criterion }}</th>
    <td>{{ row.level }}</td>
    <td class="{{ sev_cls }}">{{ row.severity | capitalize }}</td>
    <td>{{ row.file_count }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</section>
{% endif %}

<section>
<h2>Scope of Assertion</h2>
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

<section>
<h2>Methodology</h2>
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
  <dt>Standard reference</dt>
  <dd><a href="https://www.w3.org/TR/WCAG21/">Web Content Accessibility Guidelines (WCAG) 2.1</a></dd>
</dl>
</section>

{% if ai_summary %}
<section>
<h2>AI Governance</h2>
<p>{{ ai_summary }}</p>
</section>
{% endif %}

</body>
</html>
"""

_jinja_env = Environment(loader=BaseLoader(), autoescape=True)


def render_html(run: dict, files: list, meta: dict, facts: dict | None = None) -> str:
    """The HTML the PDF is made of. Exported so tests can assert on the markup directly —
    a semantic defect is far easier to read here than in a structure-tree dump, and the two
    are checked against each other by the structural tests."""
    ctx = _prepare_context(run, files, meta, facts)

    score = ctx.get("avg_score")
    ctx["ring_uri"] = _svg_data_uri(_score_ring_svg(score)) if score is not None else ""
    ctx["ring_alt"] = _ring_alt(score) if score is not None else ""

    rows = [(r["criterion"], r["file_count"]) for r in ctx.get("open_by_crit", [])[:8]]
    if rows:
        svg = _bars_svg(rows)
        ctx["bars_uri"] = _svg_data_uri(svg)
        ctx["bars_alt"] = _bars_alt(rows, ctx["total_files"])
        ctx["bars_w"] = 130 + 220 + 50
        ctx["bars_h"] = max(60, len(rows) * 22 + 20)
    else:
        ctx["bars_uri"] = ctx["bars_alt"] = ""
        ctx["bars_w"] = ctx["bars_h"] = 0

    return _jinja_env.from_string(_TEMPLATE).render(**ctx)


def build_weasy_report(run: dict, files: list, meta: dict,
                       decisions: dict | None = None,
                       evidence: list | None = None,
                       facts: dict | None = None) -> bytes:
    """Render the conformance report as a PDF/UA-1 tagged PDF.

    `pdf_variant="pdf/ua-1"` is what makes WeasyPrint emit the structure tree, the XMP
    identifier and the document-level entries the profile requires. WeasyPrint's own
    documentation is explicit that selecting the variant does NOT guarantee a conformant
    document — which is why this module ships with a veraPDF gate rather than a claim.

    The signature matches build_tagged_report / build_report so the three are drop-in
    interchangeable behind the renderer flag.
    """
    import weasyprint

    html = render_html(run, files, meta, facts)
    return weasyprint.HTML(string=html, base_url=str(Path(__file__).resolve().parent)).write_pdf(
        pdf_variant="pdf/ua-1")
