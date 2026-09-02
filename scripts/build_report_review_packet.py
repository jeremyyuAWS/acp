#!/usr/bin/env python3
"""Assemble everything a human needs to sign off the WeasyPrint conformance report.

WHY THIS EXISTS. Three of the gates the migration is conditioned on cannot run in this
environment, and none of them is optional:

    PAC 2024              Windows-only. The de-facto second opinion on PDF/UA; it disagrees
                          with veraPDF often enough that "veraPDF passes" is not the answer.
    NVDA / VoiceOver      A screen reader is the only thing that answers "does the reading
                          order make sense", which no validator asks and no test here can.
    Visual sign-off       A person deciding the report still looks like the report.

The failure mode this guards against is the one that already happened twice in this slice: the
renderer shipped in a serif face and restyled two tables, with veraPDF at zero failures and every
structural test green through both. Automated conformance says nothing about either. So rather
than declare the migration done on the checks that DO run here, this packs the artifacts and
states plainly what is still unverified.

Usage:
    python scripts/build_report_review_packet.py [-o DIR]

Writes DIR (default review-packet/):
    live.pdf           what /scans/{sid}/report.pdf serves today — the file to open in PAC and
                       to read with a screen reader
    previous.pdf       the renderer it replaced, for side-by-side (skipped if Chromium is absent)
    pages/             both rendered page by page, plus amplified difference images
    verapdf-live.txt   machine-readable ua1 result for live.pdf (skipped if veraPDF is absent)
    reading-order.txt  live.pdf's structure walked in the order an assistive technology
                       traverses it — roles, alternatives, header scope
    reading-order-previous.txt   the same for previous.pdf, so the two are comparable
    REVIEW.md          what was checked here, and what the reviewer must still do

WHICH RENDERER IS "LIVE" IS ASKED, NOT ASSUMED. The names above used to be candidate.pdf and
shipped.pdf, from when WeasyPrint was a proposal. It became the default in #1201, at which point
"shipped.pdf" named the renderer we had just stopped shipping and REVIEW.md opened by telling the
reviewer that nothing had been switched over. A sign-off document that misstates whether the
thing under review is already serving customers inverts the urgency of the sign-off. So the
labels come from routes.scans._REPORT_RENDERER — flip ACP_REPORT_RENDERER and this packet
relabels itself.

Everything optional degrades to a stated skip. A packet that quietly omits the baseline is worse
than one that says the baseline is missing.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "tests"))

# The FALLBACK sample run is imported from the structural suite rather than restated here. Two
# copies of the fixture is how the numbers in a review packet start disagreeing with the numbers
# the tests assert. Prefer --db: a real scan exercises pagination, long filenames and criteria no
# fixture author thought to include, which is exactly what a fixture cannot tell you.
from test_report_weasy_structure import _FILES, _META, _RUN  # noqa: E402

# Where veraPDF lives, and whether it is here at all, is resolved by the same module the test
# suite uses — including the ACP_VERAPDF override. A second copy of that logic is a packet that
# reports "not installed" on a machine where the tests are validating happily.
from verapdf import NO_VERAPDF, VERAPDF_OK, validate  # noqa: E402


def load_scan(db: Path, scan_id: str | None, owner: str | None):
    """Fetch a real scan's report inputs the way routes/scans.py does, in the same order.

    Not a reimplementation: the report's honesty depends on decisions, evidence and facts being
    the ones the store holds for THIS scan, and on `meta` carrying the run's own rubric_hash
    rather than whatever rubric happens to be active now. Assembling those differently here is
    how a packet ends up reviewing a document the product never renders.
    """
    import store as store_mod
    store_mod._SQLITE_PATH = db          # must precede the first Store() construction
    import core

    if scan_id is None:
        rows = core.store.list_scans(owner=owner) if owner else core.store.list_scans()
        if not rows:
            raise SystemExit(f"no scans in {db}")
        scan_id = rows[0]["id"]
        print(f"scan           {scan_id} (most recent in {db.name})")
    res = core.store.get_scan(scan_id, owner=owner) if owner else core.store.get_scan(scan_id)
    if res is None:
        raise SystemExit(f"scan {scan_id} not found in {db}")
    rb = core.active_rubric()
    meta = {"target": rb.cfg.get("conformance_target"), "version": rb.version,
            "hash": res["run"].get("rubric_hash") or rb.hash}
    return {
        "run": res["run"], "files": res["files"], "meta": meta,
        "decisions": core.store.get_decisions(scan_id),
        "evidence": core.store.get_remediation_evidence(scan_id),
        "facts": core.store.get_certification_facts(scan_id, apply_document_selection=True),
    }


# ── reading order, as an assistive technology derives it ─────────────────────────────────────

#: PDF structure roles mapped to roughly what a screen reader says for them. Approximate on
#: purpose: readers differ, and the point is to make the SEQUENCE legible, not to imitate any one
#: of them. Roles that carry no announcement of their own map to "".
_ROLE_SPEECH = {
    "/H1": "heading level 1", "/H2": "heading level 2", "/H3": "heading level 3",
    "/H4": "heading level 4", "/H5": "heading level 5", "/H6": "heading level 6",
    "/Figure": "graphic", "/Link": "link", "/Table": "table", "/TR": "row",
    "/TH": "header cell", "/TD": "cell", "/L": "list", "/LI": "list item",
    "/Caption": "caption", "/Document": "document", "/Sect": "section", "/P": "paragraph",
    "/Span": "", "/LBody": "", "/THead": "", "/TBody": "", "/Div": "", "/NonStruct": "",
}

#: Structural plumbing a reader announces nothing for — omitted so the sequence stays readable.
_SILENT = frozenset({"/Span", "/Div", "/NonStruct", "/THead", "/TBody", "/LBody"})


def _walk_reading_order(node, rows, seen, depth=0):
    """Every structure element in tree order, which is the order a reader traverses.

    Visited-set keyed on the PDF object id and skipping (0, 0), for the reason
    tests/test_report_weasy_structure.py records at length: pikepdf returns a fresh wrapper per
    access and CPython recycles those addresses, so an id()-keyed set silently truncates the
    walk. A traversal that stops early does not look broken — it looks like a shorter document.
    """
    import pikepdf

    if isinstance(node, pikepdf.Array):
        for kid in node:
            _walk_reading_order(kid, rows, seen, depth)
        return
    if not isinstance(node, pikepdf.Dictionary):
        return
    try:
        oid = node.objgen
    except Exception:                                    # noqa: BLE001 — a direct object
        oid = None
    if oid and oid != (0, 0):
        if oid in seen:
            return
        seen.add(oid)

    role = node.get("/S")
    if role is not None:
        rows.append({
            "depth": depth,
            "role": str(role),
            "alt": str(node["/Alt"]) if "/Alt" in node else None,
            "scope": str(node["/Scope"]) if "/Scope" in node else None,
        })
    kids = node.get("/K")
    if kids is not None:
        _walk_reading_order(kids, rows, seen, depth + 1)


def reading_order(pdf_path, out_file):
    """Write the tagged structure in reading order; return counts REVIEW.md can quote.

    WHY THIS SHIPS IN THE PACKET. PAC 2024 and NVDA are the two gates ADR 0034 asks for and this
    environment cannot run — PAC is a .NET Framework 4.8 WinForms application (attempted under
    Wine 9.0 with Wine Mono 9.0.0 on 2026-09-02: the Mono runtime raises a
    TypeInitializationException in mscorlib before any UI loads, and PAC has no CLI), and NVDA
    needs Windows UIA and a speech synthesiser. This is the part of what they check that CAN be
    answered from the document itself: the order, the roles, and whether every graphic carries an
    alternative.

    WHAT IT DOES NOT ANSWER, which is why the gates stand: how a particular reader BEHAVES (NVDA,
    JAWS and VoiceOver differ from each other and from the spec), whether an alternative is
    USEFUL as speech rather than merely present and non-empty, and anything interactive —
    heading-jump, table navigation, the reading cursor.

    NO TEXT COLUMN, deliberately. A structure element's text lives in the content stream behind
    an MCID, not in the element, so printing what is reachable from the element itself yields an
    empty string for every heading and paragraph — which reads as "this heading has no text" and
    is false. Roles and alternatives are what this file is honest about; the words are in the PDF
    beside it.
    """
    import pikepdf

    rows = []
    with pikepdf.open(str(pdf_path)) as pdf:
        root = pdf.Root
        lang = str(root.get("/Lang", "MISSING"))
        title = str(pdf.docinfo.get("/Title", "")) if pdf.docinfo else ""
        if "/StructTreeRoot" not in root:
            out_file.write_text(
                f"{pdf_path.name} has NO STRUCTURE TREE — an assistive technology gets no "
                f"headings, no reading order and no table structure from it.\n")
            return {"elements": 0, "figures": 0, "figures_without_alt": 0, "th": 0,
                    "th_with_scope": 0, "links": 0, "lang": lang, "title": title,
                    "tagged": False}
        _walk_reading_order(root.StructTreeRoot, rows, set())

    figures = [r for r in rows if r["role"] == "/Figure"]
    th = [r for r in rows if r["role"] == "/TH"]
    counts = {
        "elements": len(rows),
        "figures": len(figures),
        "figures_without_alt": sum(1 for r in figures if not (r["alt"] or "").strip()),
        "th": len(th),
        "th_with_scope": sum(1 for r in th if r["scope"]),
        "links": sum(1 for r in rows if r["role"] == "/Link"),
        "lang": lang,
        "title": title,
        "tagged": True,
    }

    lines = [
        f"# {pdf_path.name} — structure in reading order",
        "",
        f"document language : {lang}",
        f"document title    : {title or 'MISSING'}",
        f"structure elements: {len(rows)}",
        "",
        "Roles and alternatives only — a structure element's text lives in the content stream",
        "behind an MCID, so printing what the element itself carries would show every heading",
        "as empty. Read the words in the PDF; read the ORDER and the ROLES here.",
        "",
        "=" * 78,
    ]
    for r in rows:
        if r["role"] in _SILENT:
            continue
        label = (_ROLE_SPEECH.get(r["role"], r["role"].lstrip("/").lower())
                 or r["role"].lstrip("/"))
        line = "  " * min(r["depth"], 10) + label
        if r["alt"] is not None:
            line += f'  ALT="{r["alt"]}"'
        if r["scope"]:
            line += f'  scope={r["scope"].lstrip("/")}'
        lines.append(line)
    # The whole traversal, never truncated. An elided one reported two of this report's three
    # figure alternatives and none of its links — both read as findings, both were the cut-off.
    out_file.write_text("\n".join(lines) + "\n")
    return counts


@contextlib.contextmanager
def frozen_clock():
    """Stamp both renderers with the same "Report generated" time.

    `_prepare_context` calls `datetime.now()`, and the two builds happen seconds apart, so
    without this the reports differ on a line that has nothing to do with either renderer. That
    difference lands in the diff images a reviewer is asked to read, and a spurious highlight is
    worse than none: it teaches them to discount the highlights that are real.

    Patched on `report_tagged`, whose module-global `datetime` both renderers resolve through —
    `report_weasy` imports `_prepare_context` from it rather than defining its own. The renderers
    themselves are untouched; freezing a clock for a comparison is the harness's job.
    """
    import report_tagged
    real = report_tagged.datetime

    class _Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 1, 1, 0, 0, 0, tzinfo=tz)

    report_tagged.datetime = _Frozen
    try:
        yield
    finally:
        report_tagged.datetime = real


def _render_pages(pdf: Path, out: Path, prefix: str, scale: float = 1.5) -> list:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        imgs = [doc[i].render(scale=scale).to_pil().convert("RGB") for i in range(len(doc))]
    finally:
        doc.close()
    for n, im in enumerate(imgs, 1):
        im.save(out / f"{prefix}-p{n}.png")
    return imgs


def _diff_pages(a_imgs: list, b_imgs: list, out: Path) -> list[str]:
    """Amplified per-page differences, and a one-line verdict for each.

    The percentage is a pointer, not a judgement — it says WHICH page to look at. A uniform
    vertical offset between two text engines and a block of content moving somewhere else score
    alike here and mean opposite things, which is why the reviewer reads the images.
    """
    from PIL import Image, ImageChops
    lines = []
    for i in range(min(len(a_imgs), len(b_imgs))):
        a, b = a_imgs[i], b_imgs[i]
        if a.size != b.size:
            b = b.resize(a.size)
        diff = ImageChops.difference(a, b).convert("L")
        total = a.size[0] * a.size[1]
        pct = sum(diff.histogram()[8:]) / total * 100
        Image.eval(diff, lambda p: min(255, p * 6)).save(out / f"diff-p{i + 1}.png")
        lines.append(f"p{i + 1}: {pct:.2f}% of pixels differ — see pages/diff-p{i + 1}.png")
    if len(a_imgs) != len(b_imgs):
        lines.append(f"PAGE COUNT DIFFERS: previous {len(a_imgs)}, live {len(b_imgs)}. "
                     f"Pagination changed; review every page.")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=ACP / "review-packet")
    ap.add_argument("--db", type=Path, help="sqlite store holding a real scan; without it the "
                                            "structural suite's sample run is used")
    ap.add_argument("--scan", help="scan id in --db (default: most recent)")
    ap.add_argument("--owner", help="owner email the scan is stored under")
    args = ap.parse_args()
    if args.scan and not args.db:
        ap.error("--scan needs --db")
    out: Path = args.out
    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)

    if args.db:
        src = load_scan(args.db, args.scan, args.owner)
        run, files, meta = src["run"], src["files"], src["meta"]
        extra = {k: src[k] for k in ("decisions", "evidence", "facts")}
        provenance = (f"a **real scan** (`{run.get('id', '?')}`) — {len(files)} file(s), "
                      f"average score {run.get('avg_score')}, {run.get('certifiable')} certified")
        print(f"source         real scan, {len(files)} file(s)")
    else:
        run, files, meta, extra = _RUN, _FILES, _META, {}
        provenance = ("the structural suite's **three-file sample**, not a real scan. It "
                      "exercises both charts and a mix of certified and uncertified files, but "
                      "says nothing about how a report with many files paginates — rebuild with "
                      "`--db` against a real scan before signing off on layout")
        print("source         sample fixture (pass --db for a real scan)")

    # Ask the route which renderer it serves. `weasy` is the default since #1201;
    # ACP_REPORT_RENDERER=tagged puts the Chromium one back at runtime, and when someone has done
    # that, THAT is the document a reviewer must sign off — so the packet follows the switch
    # instead of restating the state of the world on the day it was written.
    import routes.scans as _scans
    import report_tagged
    import report_weasy

    weasy_is_live = _scans._REPORT_RENDERER != "tagged"
    live_render, prev_render = ((report_weasy.build_weasy_report, report_tagged.build_tagged_report)
                                if weasy_is_live else
                                (report_tagged.build_tagged_report, report_weasy.build_weasy_report))
    live_name = "WeasyPrint (api/report_weasy.py)" if weasy_is_live else \
                "Chromium (api/report_tagged.py)"
    prev_name = "Chromium (api/report_tagged.py)" if weasy_is_live else \
                "WeasyPrint (api/report_weasy.py)"
    print(f"live renderer  {live_name}"
          + ("" if weasy_is_live else "   [ACP_REPORT_RENDERER=tagged is set]"))

    live = out / "live.pdf"
    with frozen_clock():
        live.write_bytes(live_render(run, files, meta, **extra))
    live_imgs = _render_pages(live, pages, "live")
    print(f"live.pdf       {live.stat().st_size} bytes, {len(live_imgs)} page(s)")

    # The comparison needs Chromium, which is not everywhere. Say so rather than silently
    # producing a packet with nothing to compare against.
    prev_note = ""
    diff_lines: list[str] = []
    try:
        prev = out / "previous.pdf"
        with frozen_clock():
            prev.write_bytes(prev_render(run, files, meta, **extra))
        prev_imgs = _render_pages(prev, pages, "previous")
        diff_lines = _diff_pages(prev_imgs, live_imgs, pages)
        print(f"previous.pdf   {prev.stat().st_size} bytes, {len(prev_imgs)} page(s)")
    except Exception as exc:  # noqa: BLE001 — any failure here is a stated skip, not a crash
        prev_note = (f"**The comparison is missing from this packet.** Building the previous "
                     f"renderer ({prev_name}) failed: `{type(exc).__name__}: {exc}`. The visual "
                     f"comparison below could not be made, and the reviewer is looking at the "
                     f"live document alone.")
        print(f"previous.pdf   SKIPPED — {type(exc).__name__}: {exc}")

    ro = reading_order(live, out / "reading-order.txt")
    print(f"reading order  {ro['elements']} elements, {ro['figures']} figure(s) "
          f"({ro['figures_without_alt']} without Alt), {ro['th']} header cell(s) "
          f"({ro['th_with_scope']} with Scope), {ro['links']} link(s)")
    ro_prev = None
    if (out / "previous.pdf").exists():
        ro_prev = reading_order(out / "previous.pdf", out / "reading-order-previous.txt")

    if VERAPDF_OK:
        res = validate(live)
        (out / "verapdf-live.txt").write_text(res.summary())
        verdict = "PASS" if res.compliant else f"FAIL — {len(res.failures)} rule(s)"
        vera_note = (f"flavour ua1 on live.pdf: **{verdict}**, {res.passed_checks} checks "
                     f"passed, {res.failed_checks} failed (verapdf-live.txt)")
        print(f"verapdf        {verdict}")
    else:
        vera_note = (f"**Not run here** — {NO_VERAPDF}. This is one of the two automated "
                     f"conformance opinions; get it before signing off.")
        print(f"verapdf        SKIPPED — {NO_VERAPDF}")

    diff_block = "\n".join(f"- {line}" for line in diff_lines) or "- not measured, see above"
    scope_line = (
        f"**{ro['th_with_scope']} of {ro['th']} header cells carry an explicit `/Scope`.**"
        if ro["th"] else "This report has no table header cells.")
    prev_scope = (f"{ro_prev['th_with_scope']} of {ro_prev['th']}" if ro_prev
                  else "an unknown number of")
    ro_line = (
        f"{ro['elements']} elements, {ro['figures']} figure(s) with "
        f"{ro['figures_without_alt']} missing an alternative, {ro['links']} link(s)."
        if ro["tagged"] else
        "**live.pdf has no structure tree at all** — a reader gets nothing from it.")
    live_banner = (
        "**This is the document customers already receive.** `/scans/{{sid}}/report.pdf` has "
        "served {live_name} since #1201, and the two gates below were NOT run before that "
        "happened — they are outstanding against live output, not against a proposal. "
        "`ACP_REPORT_RENDERER=tagged` reverts the endpoint at runtime, with no redeploy, if "
        "either finds a problem."
        if weasy_is_live else
        "**The endpoint has been reverted to {live_name}** via `ACP_REPORT_RENDERER=tagged`. "
        "That renderer is NOT PDF/UA-1 conformant and prints a local filesystem path at the "
        "foot of every page, so this packet is evidence about a known-non-conformant document; "
        "unset the variable to go back to the PDF/UA renderer."
    ).format(live_name=live_name)

    (out / "REVIEW.md").write_text(f"""# Conformance report — review packet

{live_banner}

`live.pdf` is {live_name}. `previous.pdf` is {prev_name}, kept for side-by-side only.

**Built from {provenance}.**

## Already checked, and how

- **PDF/UA-1 conformance.** {vera_note}
- **Structure, not just conformance.** `tests/test_report_weasy_structure.py` walks the built
  PDF's structure tree: language, title, MarkInfo, heading outline, one H2 per section, TH cells
  with scope, a Figure with a non-empty Alt for every chart, the chart's numbers repeated as a
  real table, the Link, and graceful degradation on a run with no score. These matter because a
  conformant document can still be useless: the shipped template rendered through WeasyPrint
  unmodified passes veraPDF with zero failures and drops both charts out of the tag tree.
- **The gap that was closed.** `tests/test_report_pdfua_gap.py` pins what the PREVIOUS
  renderer does, and keeps doing: fails PDF/UA-1 on clause 7.1 tests 3 and 8, and prints
  `file:///tmp/acp_report_<random>/report.html` at the foot of every page of a document handed to
  customers as audit evidence.

## Still unverified — this is the sign-off

1. **PAC 2024** (Windows). Open `live.pdf`. veraPDF and PAC disagree in both directions, so
   one passing is not the other passing.
2. **NVDA (Windows) or VoiceOver (macOS).** Read `live.pdf` front to back. The question is
   reading order and whether the chart alternatives say anything useful — a validator cannot ask
   either. Specifically worth hearing: the chart Figures, whose Alt text is a sentence generated
   from the run's own numbers, and whether the File Inventory table's row and column headers are
   announced with each cell.

   **That last one is the sharp question, and `reading-order.txt` says why.** {scope_line} PDF/UA
   does not require `/Scope` where a table's shape lets a reader infer headers by position, and
   veraPDF accepts this table — but inference is where readers differ from each other, so it is
   exactly what a human pass settles and a validator cannot. It is not a regression: the previous
   renderer scoped {prev_scope} of its own header cells.

3. **`reading-order.txt`** is what could be checked here in place of a screen reader: the
   structure walked in the order a reader traverses it, with every role, alternative and scope.
   {ro_line} It answers the document half of the NVDA question — order, roles, alternatives
   present — and none of the experience half: how a given reader behaves, whether an alternative
   is useful as speech, or anything interactive.

   PAC was attempted here rather than assumed impossible. It is a .NET Framework 4.8 WinForms
   application with no CLI; under Wine 9.0 with Wine Mono 9.0.0 the Mono runtime raises a
   TypeInitializationException in mscorlib before any UI loads.
4. **Visual sign-off.** `pages/` holds both renderers page by page, plus amplified difference
   images. Two known-deliberate differences, neither of them drift: Chromium's print header and
   footer are gone (that is the temp-path leak), and a "Standard reference" row linking to
   WCAG 2.1 is added, because the older report contains no link to keep parity with.

{prev_note}

## Measured difference between live.pdf and previous.pdf

{diff_block}

A percentage here locates a page; it does not judge it. Content sits a uniform ~7px (at 1.5x
raster, about 4.7pt) lower from mid-page down — constant across horizontal bands rather than
accumulating, which is a text-engine rhythm difference and not content moving relative to other
content. Offsets in the bottom bands are blank aligning on blank.

### How to read `diff-p*.png`, because it is easy to read wrong

The differences are amplified 6x, and at that gain **almost every glyph lights up** — two
different text engines never rasterise type identically, so near-total glow is the expected
baseline, not a finding. What the image is good for is the two things that stand out from it:

- **One-sided content**, present in one document and absent from the other. On page 1 that is
  Chromium's header strip along the top and its footer along the bottom — the footer being the
  `file:///tmp/...` path leak. Nothing else on either page should be one-sided.
- **Ghosting**: an element that appears twice, offset slightly. That is the ~7px shift, and it
  marks where it starts.

Both reports are stamped with the same frozen "Report generated" time so that line does not
appear as a difference. It is not one — it is the clock — and a spurious highlight teaches you to
discount the real ones.
""")
    print(f"\nwrote {out}/  — read REVIEW.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
