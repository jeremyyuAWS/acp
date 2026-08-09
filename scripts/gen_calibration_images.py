#!/usr/bin/env python3
"""Images of text with known facts — the answer key the LLM judges are calibrated against.

WHY MORE THAN ONE. The first calibration set was a single notice described by seven models: six
or seven usable points, enough to catch a judge that is badly wrong and not enough to certify one
that looks right. Correlation over seven points is a hint, not a measurement.

WHY THESE ARE MEASURABLE AT ALL. An image OF TEXT has an objective answer: the words in it. So
"how many of this document's facts does the alt text convey" is countable, and a judge's opinion
can be checked against it. That property does not hold for photographs, which is exactly why the
judge is needed there and cannot be validated there.

GROUND TRUTH IS AUTHORED, THEN VERIFIED. Each image's facts are declared here — I wrote the text,
so I know what it says — and then tesseract reads the rendered image back to confirm every fact
is actually legible. A fact that OCR cannot recover is dropped from the answer key rather than
counted against a model that could not have read it either. Without that check the answer key
would quietly include text no vision model could see, and every model would look worse than it is.

CONTENT IS SYNTHETIC. Healthcare-shaped wording, invented values, no real names, records or
identifiers. These are sent to third-party judges; nothing here may be real.

Run:
    python scripts/gen_calibration_images.py --out ~/Downloads/acp-docx-eval/calibration
"""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

# Each entry: the lines rendered into the image, and the facts a good alt text should convey.
# A fact is (name, regex) — the regex is what "conveyed" means, kept generous on wording and
# strict on the fact itself, matching measure_alt_fact_coverage.py's convention.
DOCS = [
    ("enrollment-notice", [
        "2026 Open Enrollment Notice",
        "Enrollment runs March 1 through March 31",
        "Review medical, dental and vision options",
        "Elect coverage in the Benefits Portal",
    ], [
        ("title", r"(?=.*open enrollment)(?=.*2026)"),
        ("window", r"march\s*1\b.*march\s*31"),
        ("coverage", r"medical.*dental.*vision"),
        ("portal", r"benefits portal"),
    ]),
    ("lab-summary", [
        "Laboratory Results Summary",
        "Glucose 127 mg per dL is above range",
        "Cholesterol 185 mg per dL is normal",
        "Repeat testing in three months",
    ], [
        ("title", r"lab(oratory)?\s*result"),
        ("glucose", r"glucose.*127"),
        ("cholesterol", r"cholesterol.*185"),
        ("followup", r"(three months|3 months|repeat)"),
    ]),
    ("medication-label", [
        "Take one tablet twice daily",
        "Swallow whole with a full glass of water",
        "Do not take with grapefruit juice",
        "Refills remaining: two",
    ], [
        ("dose", r"(one|1)\s*tablet.*(twice|two times)"),
        ("water", r"(glass of )?water"),
        ("interaction", r"grapefruit"),
        ("refills", r"refill"),
    ]),
    ("appointment-reminder", [
        "Appointment Reminder for April 14",
        "Arrive fifteen minutes before your visit",
        "Bring your insurance card and photo ID",
        "Call 214 648 9999 to reschedule",
    ], [
        ("title", r"appointment"),
        ("date", r"april\s*14"),
        ("bring", r"insurance card|photo id"),
        ("phone", r"214[-\s]?648[-\s]?9999"),
    ]),
    ("consent-header", [
        "Authorization to Disclose Health Information",
        "This authorization is valid for ninety days",
        "You may revoke it in writing at any time",
        "A copy will be provided on request",
    ], [
        ("title", r"authoriz\w+ to disclose"),
        ("validity", r"(ninety|90)\s*days"),
        ("revoke", r"revoke"),
        ("copy", r"copy"),
    ]),
]


def render(lines: list[str]) -> bytes:
    """Same approach as gen_demo_fixtures._png_of_text: draw small, then upscale, because the
    default bitmap font is too small for tesseract at its native size."""
    im = Image.new("RGB", (900, 60 + 70 * len(lines)), "white")
    d = ImageDraw.Draw(im)
    y = 20
    for ln in lines:
        d.text((20, y), ln, fill="black")
        y += 70
    im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "Downloads" / "acp-docx-eval" / "calibration")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    try:
        import pytesseract
    except ImportError:
        raise SystemExit("pytesseract is required to verify the answer key")

    manifest, dropped_total = [], 0
    for name, lines, facts in DOCS:
        png = render(lines)
        path = args.out / f"{name}.png"
        path.write_bytes(png)

        # VERIFY: only facts tesseract can actually recover stay in the answer key. A fact the
        # OCR cannot see is one no vision model could have read either, and counting it would
        # penalise every model for a rendering problem.
        ocr = pytesseract.image_to_string(Image.open(io.BytesIO(png))) or ""
        kept, dropped = [], []
        for fname, pat in facts:
            (kept if re.search(pat, ocr.lower(), re.S) else dropped).append(fname)
        dropped_total += len(dropped)
        manifest.append({
            "file": path.name,
            "source_text": " ".join(lines),
            "ocr": " ".join(ocr.split()),
            "facts": {f: p for f, p in facts if f in kept},
        })
        flag = f"  DROPPED (not legible to OCR): {dropped}" if dropped else ""
        print(f"  {path.name:24} {len(kept)}/{len(facts)} facts verified{flag}")

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(len(m["facts"]) for m in manifest)
    print(f"\n{len(manifest)} images · {total} verified facts · {dropped_total} dropped")
    print(f"wrote {args.out}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
