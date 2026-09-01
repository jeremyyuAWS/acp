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
    candidate.pdf          the WeasyPrint report — the file to open in PAC and the reader
    shipped.pdf            today's Chromium report, for side-by-side (skipped if no Chromium)
    pages/                 both rendered page by page, plus amplified difference images
    verapdf-candidate.txt  machine-readable ua1 result (skipped if veraPDF is absent)
    REVIEW.md              what was checked here, and what the reviewer must still do

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

# The sample run is imported from the structural suite rather than restated here. Two copies of
# the fixture is how the numbers in a review packet start disagreeing with the numbers the tests
# assert, and this document exists to be trusted.
from test_report_weasy_structure import _FILES, _META, _RUN  # noqa: E402

# Where veraPDF lives, and whether it is here at all, is resolved by the same module the test
# suite uses — including the ACP_VERAPDF override. A second copy of that logic is a packet that
# reports "not installed" on a machine where the tests are validating happily.
from verapdf import NO_VERAPDF, VERAPDF_OK, validate  # noqa: E402


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
        lines.append(f"PAGE COUNT DIFFERS: shipped {len(a_imgs)}, candidate {len(b_imgs)}. "
                     f"Pagination changed; review every page.")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=ACP / "review-packet")
    args = ap.parse_args()
    out: Path = args.out
    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)

    import report_weasy
    candidate = out / "candidate.pdf"
    with frozen_clock():
        candidate.write_bytes(report_weasy.build_weasy_report(_RUN, _FILES, _META))
    cand_imgs = _render_pages(candidate, pages, "candidate")
    print(f"candidate.pdf  {candidate.stat().st_size} bytes, {len(cand_imgs)} page(s)")

    # The baseline needs Chromium, which is not everywhere. Say so rather than silently
    # producing a packet with nothing to compare against.
    shipped_note = ""
    diff_lines: list[str] = []
    try:
        import report_tagged
        shipped = out / "shipped.pdf"
        with frozen_clock():
            shipped.write_bytes(report_tagged.build_tagged_report(_RUN, _FILES, _META))
        ship_imgs = _render_pages(shipped, pages, "shipped")
        diff_lines = _diff_pages(ship_imgs, cand_imgs, pages)
        print(f"shipped.pdf    {shipped.stat().st_size} bytes, {len(ship_imgs)} page(s)")
    except Exception as exc:  # noqa: BLE001 — any failure here is a stated skip, not a crash
        shipped_note = (f"**The baseline is missing from this packet.** Building today's "
                        f"Chromium report failed: `{type(exc).__name__}: {exc}`. Without it the "
                        f"visual comparison below could not be made, and the reviewer is "
                        f"looking at the candidate alone.")
        print(f"shipped.pdf    SKIPPED — {type(exc).__name__}: {exc}")

    if VERAPDF_OK:
        res = validate(candidate)
        (out / "verapdf-candidate.txt").write_text(res.summary())
        verdict = "PASS" if res.compliant else f"FAIL — {len(res.failures)} rule(s)"
        vera_note = (f"flavour ua1: **{verdict}**, {res.passed_checks} checks passed, "
                     f"{res.failed_checks} failed (verapdf-candidate.txt)")
        print(f"verapdf        {verdict}")
    else:
        vera_note = (f"**Not run here** — {NO_VERAPDF}. This is one of the two automated "
                     f"conformance opinions; get it before signing off.")
        print(f"verapdf        SKIPPED — {NO_VERAPDF}")

    diff_block = "\n".join(f"- {line}" for line in diff_lines) or "- not measured, see above"
    (out / "REVIEW.md").write_text(f"""# Conformance report — review packet

The WeasyPrint PDF/UA-1 renderer proposed to replace the Chromium one. **Nothing has been
switched over.** `api/report_tagged.py`, `api/report.py` and `api/routes/scans.py` are untouched;
this packet is the evidence for deciding whether to.

## Already checked, and how

- **PDF/UA-1 conformance.** {vera_note}
- **Structure, not just conformance.** `tests/test_report_weasy_structure.py` walks the built
  PDF's structure tree: language, title, MarkInfo, heading outline, one H2 per section, TH cells
  with scope, a Figure with a non-empty Alt for every chart, the chart's numbers repeated as a
  real table, the Link, and graceful degradation on a run with no score. These matter because a
  conformant document can still be useless: the shipped template rendered through WeasyPrint
  unmodified passes veraPDF with zero failures and drops both charts out of the tag tree.
- **The gap being closed.** `tests/test_report_pdfua_gap.py` pins what today's renderer does:
  fails PDF/UA-1 on clause 7.1 tests 3 and 8 — 8 failed checks — and prints
  `file:///tmp/acp_report_<random>/report.html` at the foot of every page of a document handed to
  customers as audit evidence.

## Still unverified — this is the sign-off

1. **PAC 2024** (Windows). Open `candidate.pdf`. veraPDF and PAC disagree in both directions, so
   one passing is not the other passing.
2. **NVDA (Windows) or VoiceOver (macOS).** Read `candidate.pdf` front to back. The question is
   reading order and whether the chart alternatives say anything useful — a validator cannot ask
   either. Specifically worth hearing: the two chart Figures, whose Alt text is a sentence
   generated from the run's own numbers, and whether the File Inventory table's row headers are
   announced with each cell.
3. **Visual sign-off.** `pages/` holds both renderers page by page, plus amplified difference
   images. Two known-deliberate differences, neither of them drift: Chromium's print header and
   footer are gone (that is the temp-path leak), and page 2 gains a "Standard reference" row
   linking to WCAG 2.1, because the shipped report contains no link to keep parity with.

{shipped_note}

## Measured difference against the shipped report

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
