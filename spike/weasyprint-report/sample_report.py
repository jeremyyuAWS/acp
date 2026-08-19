"""WeasyPrint tagged-PDF spike for the conformance report (ADR 0034).

A BOUNDED spike, not the renderer migration. It ports only the representative page types the full
report is made of — a cover, a narrative page, one complex table, and one chart-heavy page — so the
hard questions (heading hierarchy, scoped table headers, chart treatment, page furniture excluded
from reading order) can be answered on a real artifact before committing the 2–4 day rewrite.

What this proves if it passes inspect_tags.py: the tag STRUCTURE is correct and our own detectors
are satisfied. What it does NOT prove: PDF/UA conformance or real screen-reader usability — those
need veraPDF/PAC and a manual NVDA/VoiceOver pass (see README, "Validation gate"). WeasyPrint's own
docs are explicit that selecting pdf/ua-1 does not guarantee a valid document.

Run:  python sample_report.py            # writes sample_report.pdf
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import weasyprint

OUT = Path(__file__).resolve().parent / "sample_report.pdf"

# ── Chart treatment (the part that is NOT "free") ────────────────────────────────────────────────
# The spike's first iteration proved an HTML chart is not accessible by default:
#   * an aria-hidden inline <svg> does NOT become an Artifact in WeasyPrint — it leaves an ORPHAN
#     /Figure marked-content (real content, neither tagged-with-alt nor artifact → PDF/UA forbids it);
#   * <svg role="img" aria-label> is likewise ignored for tagging (still orphan).
# What WORKS (verified): an <img> with a real alt tags as a /Figure WITH /Alt and no orphan. So the
# chart is delivered as three things, none automatic:
#   1. an <img alt="…"> whose alt states the chart's CONCLUSION (not "a bar chart"),
#   2. an adjacent real data <table> so the numbers are in the tag tree, not only in pixels,
#   3. the drawing carried inside that <img> (a data-URI SVG), so it is a single tagged Figure.
# The SVG is base64-encoded into the data URI: a raw `utf8,` URI truncates at the first `#` in a hex
# colour, silently blanking the image.
_CHART_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="96" viewBox="0 0 220 96">'
    '<rect x="0" y="12" width="44" height="84" fill="#A32D2D"/>'      # Critical 14
    '<rect x="58" y="42" width="44" height="54" fill="#854F0B"/>'     # Serious 9
    '<rect x="116" y="72" width="44" height="24" fill="#1F5FA8"/>'    # Moderate 4
    '<rect x="174" y="84" width="44" height="12" fill="#9a948f"/>'    # Minor 2
    '</svg>'
)
_CHART_ALT = ("Open findings by severity: Critical 14, Serious 9, Moderate 4, Minor 2 — findings "
              "concentrate in the two highest severities.")
_CHART_IMG = (
    f'<img alt="{_CHART_ALT}" width="220" height="96" '
    f'src="data:image/svg+xml;base64,{base64.b64encode(_CHART_SVG.encode()).decode()}">'
)

HTML = f"""<!doctype html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<title>mova.io Accessibility Assessment Report — sample</title>
<style>
  @page {{
    size: Letter; margin: 24mm 18mm 20mm 18mm;
    /* Running header/footer live in margin boxes. WeasyPrint marks margin-box content as
       pagination artifacts, so they must NOT enter the reading order — inspect_tags.py checks this. */
    @top-center {{ content: "mova.io · Accessibility Compliance Platform · confidential";
                   font: 8pt 'Helvetica', sans-serif; color: #9a948f; }}
    @bottom-right {{ content: "Page " counter(page) " of " counter(pages);
                     font: 8pt 'Helvetica', sans-serif; color: #9a948f; }}
  }}
  html {{ font-family: 'Helvetica', Arial, sans-serif; color: #2b2530; font-size: 10.5pt; line-height: 1.5; }}
  h1 {{ font-size: 20pt; color: #46303F; margin: 0 0 2pt; }}
  h2 {{ font-size: 13pt; color: #46303F; margin: 18pt 0 6pt; border-bottom: 1pt solid #e0dbe4; padding-bottom: 3pt; }}
  h3 {{ font-size: 11pt; color: #46303F; margin: 12pt 0 4pt; }}
  .sub {{ color: #6c6470; font-size: 9.5pt; }}
  .page-break {{ break-before: page; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 8.5pt; margin-top: 6pt; }}
  th, td {{ text-align: left; padding: 4pt 6pt; border-bottom: 0.5pt solid #e0dbe4; vertical-align: top; }}
  thead th {{ color: #6c6470; border-bottom: 1pt solid #cfc7d4; }}
  td.num, th.num {{ text-align: right; }}
  caption {{ text-align: left; color: #6c6470; font-size: 8.5pt; margin-bottom: 3pt; caption-side: top; }}
  .chartrow {{ display: flex; gap: 18pt; align-items: flex-start; margin-top: 6pt; }}
  .lead {{ color: #46303F; }}
  a {{ color: #1F5FA8; }}
</style>
</head>
<body>
  <!-- ── COVER / decision (page type 1) ── -->
  <h1>Accessibility Assessment Report</h1>
  <p class="sub">WCAG 2.1 Level AA · generated 2026-08-18 · scan <strong>selfcheck-001</strong></p>
  <p class="lead">This document reports what ACP checked, what it changed, and what it re-verified. It
     is machine-generated audit evidence, not a conformance determination.</p>
  <p><strong>12 of 20</strong> assessed documents came back with zero open blocking findings among the
     criteria ACP checked; <strong>6</strong> still carry open findings and <strong>2</strong> could not
     be opened. See <a href="#inventory">the file inventory</a> for the per-document detail.</p>

  <!-- ── NARRATIVE page (page type 2) ── -->
  <section class="page-break">
    <h2>What this report covers, and what it does not</h2>
    <p>This platform has an automated validator for a subset of WCAG 2.1 AA success criteria. For each
       document, only the criteria that have a validator for that file format are evaluated; the
       remainder are reported as <em>not evaluated</em> — no check was run, which is deliberately not the
       same as <em>not applicable</em>.</p>
    <h3>Documents this scan did not open</h3>
    <p>The scan was scoped to <code>.docx</code>, so documents of other file types were not read at all.
       They were not downloaded, opened or checked, and this report makes no statement about them
       whatsoever — neither conformant nor failing.</p>
    <h3>Estate coverage</h3>
    <p>Discovery found <strong>1,240</strong> files in this source. <strong>310</strong> are a file type
       ACP can assess; the remaining <strong>930</strong> are outside any automated accessibility
       assertion. These are three separate denominators, not one percentage.</p>
  </section>

  <!-- ── COMPLEX TABLE (page type 3) ── -->
  <section class="page-break" id="inventory">
    <h2>File inventory</h2>
    <table>
      <caption>Per-document assessment outcome. Column headers are scoped; the file name is the row header.</caption>
      <thead>
        <tr>
          <th scope="col">File</th><th scope="col">Type</th><th scope="col">Status</th>
          <th scope="col" class="num">Score</th><th scope="col" class="num">Findings</th>
          <th scope="col" class="num">Fixed</th><th scope="col" class="num">Open</th>
        </tr>
      </thead>
      <tbody>
        <tr><th scope="row">Finance-Onboarding-Form.docx</th><td>docx</td><td>open findings</td>
            <td class="num">55</td><td class="num">7</td><td class="num">2</td><td class="num">5</td></tr>
        <tr><th scope="row">Benefits-Summary-2026.docx</th><td>docx</td><td>no blocking findings</td>
            <td class="num">92</td><td class="num">3</td><td class="num">3</td><td class="num">0</td></tr>
        <tr><th scope="row">Patient-Intake.docx</th><td>docx</td><td>could not analyse</td>
            <td class="num">—</td><td class="num">—</td><td class="num">—</td><td class="num">—</td></tr>
      </tbody>
    </table>
  </section>

  <!-- ── CHART-HEAVY page (page type 4) ── -->
  <section class="page-break">
    <h2>Document status &amp; open-finding severity</h2>
    <p>Open findings concentrate in the two highest severities: <strong>CRITICAL</strong> and
       <strong>SERIOUS</strong> together account for most of the estate's open findings, which is where
       remediation effort should go first. The chart states this conclusion in its alt text; the table
       carries the exact counts.</p>
    <div class="chartrow">
      <table>
        <caption>Open findings by severity (the chart's data, in the tag tree).</caption>
        <thead><tr><th scope="col">Severity</th><th scope="col" class="num">Open findings</th></tr></thead>
        <tbody>
          <tr><th scope="row">Critical</th><td class="num">14</td></tr>
          <tr><th scope="row">Serious</th><td class="num">9</td></tr>
          <tr><th scope="row">Moderate</th><td class="num">4</td></tr>
          <tr><th scope="row">Minor</th><td class="num">2</td></tr>
        </tbody>
      </table>
      {_CHART_IMG}
    </div>
  </section>
</body>
</html>"""


def build(out: Path = OUT) -> Path:
    weasyprint.HTML(string=HTML).write_pdf(out, pdf_variant="pdf/ua-1")
    return out


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size} bytes)")
    sys.exit(0)
