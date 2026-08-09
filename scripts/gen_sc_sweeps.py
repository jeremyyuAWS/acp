#!/usr/bin/env python3
"""Dense sampling around each decision boundary — the corpus's statistical power, honestly.

THE PROBLEM THIS SOLVES, AND THE ONE IT DOES NOT. `gen_sc_corpus.py` presents 21 seeded
violations. By the rule of three, n trials with zero observed failures bound the true failure
rate at about 3/n at 95% confidence — so 21 licenses a claim of ~14%, an order of magnitude
weaker than the ">=99% PASS precision" gate the local-model programme proposes. More
observations are the fix.

BUT MORE FIXTURES ARE NOT AUTOMATICALLY MORE OBSERVATIONS, and getting this wrong would produce
a confident number backed by nothing. The rule of three assumes INDEPENDENT trials. Three hundred
copies of "a table whose header row is not marked" is one observation repeated three hundred
times: the detector either handles that shape or it does not, and re-asking cannot change the
answer. Reporting n=300 there would be arithmetic dressed as evidence.

So density is generated only where the INPUT SPACE IS GENUINELY RICH — where each sample is a
different question:

    1.4.3   contrast ratio is continuous. Every step across 4.5:1 is a distinct input, and the
            boundary is exactly where a detector's arithmetic can be wrong.
    1.4.11  same, at 3:1, against a fill that also varies.
    3.1.2   segment length crosses textchecks._MIN_SEG_WORDS (12), and the language pair varies.
            Two axes, both real.
    1.4.5   OCR word count crosses ocr._MIN_WORDS (10). Each count is a different input.
    1.1.1   junk-descr classification has a real vocabulary — filenames, auto-names, extensions,
            whitespace — and each is a distinct string the predicate must judge.
    2.4.4   vague link text likewise: a phrase list, not a repetition.

Criteria whose input space is two or three discrete states (2.4.2 title present/absent/blank,
3.1.1 language present/absent) are DELIBERATELY NOT swept. Their fixtures in the base corpus
already cover the space; adding copies would inflate the denominator and weaken nothing but the
honesty of the number.

WHAT THE NUMBERS MEAN AFTERWARDS. Even a swept criterion's samples are not fully independent —
consecutive contrast steps share almost everything — so the bound this supports is a bound on
"the detector mishandles some input in this region", not on "ACP is wrong about an arbitrary
document". `score_assessment.py` reports the count per criterion so the claim is scoped to the
criterion it was measured on, which is the smallest unit that means anything.

Run:
    python scripts/gen_sc_sweeps.py --out ~/Downloads/acp-docx-eval/sc-sweeps --density 40
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

import corpus_expectations as ce  # noqa: E402
from gen_sc_corpus import _add_hyperlink, _add_image, _content_png, _doc, _run, _text_png  # noqa: E402

FMT = "docx"


def _contrast_ratio(fg: tuple[int, int, int], bg=(255, 255, 255)) -> float:
    def lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    def lum(rgb):
        r, g, b = (lin(x) for x in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ── 1.4.3 · body-text contrast across the 4.5:1 boundary ──────────────────────

def sweep_contrast(n: int) -> list[tuple[str, object, dict, str]]:
    """Greys either side of 4.5:1, densest where the answer flips.

    Every sample is a genuinely different input — a different luminance, a different arithmetic
    result — which is what makes counting them defensible. The band is narrow on purpose: a
    detector that is wrong at 12:1 is wrong in a way one fixture already catches, and a detector
    that is wrong at 4.51 is wrong in a way only this finds.
    """
    out = []
    lo, hi = 0x66, 0x8E                       # ~5.9:1 down to ~3.2:1 on white
    # DISTINCT VALUES ONLY — see sweep_language for what asking for more samples than the range
    # holds actually produces. 41 greys exist here; a --density above that adds rows, not inputs.
    for v in sorted({lo + round(i * (hi - lo) / max(1, n - 1)) for i in range(n)}):
        ratio = _contrast_ratio((v, v, v))
        expect = {} if ratio >= 4.5 else {"1.4.3": ce.FAIL}

        def build(d, v=v):
            d.add_heading("Notice", level=1)
            _run(d.add_paragraph(),
                 "Your coverage begins on the first of March and continues to the year end.",
                 color=(v, v, v))
            return d
        out.append((f"contrast-{v:02x}-{ratio:.2f}".replace(".", "p"), build, expect,
                    f"body text #{v:02x}{v:02x}{v:02x} on white = {ratio:.2f}:1 "
                    f"({'passes' if ratio >= 4.5 else 'fails'} the 4.5 AA floor)"))
    return out


# ── 3.1.2 · foreign passage length across the 12-word floor ───────────────────

_FR = ("Veuillez consulter la politique d'accessibilite de notre etablissement avant le trente "
       "et un mars prochain sans faute pour eviter toute interruption de couverture medicale")
_EN = ("Please review the accessibility policy for the coming plan year before the enrollment "
       "deadline at the end of March to avoid any interruption in your medical coverage")


def sweep_language(n: int) -> list[tuple[str, object, dict, str]]:
    """French passages from below the floor to well above it.

    textchecks needs TWO confident segments in different languages, each at least
    _MIN_SEG_WORDS (12) words — a fact that produced three false "product defects" in one day
    before it was understood. The English side is held comfortably above the floor so the only
    variable is the foreign passage's length, which is what makes each sample one question.

    DISTINCT k ONLY. The first version asked for `n` samples across a 21-value range, so 40
    requests produced 21 files and 40 manifest rows — three fixtures named lang-12w, one file,
    three "independent" observations. That is exactly the inflated denominator this module's
    docstring warns about, generated by the module that warns about it. Density is bounded by how
    many distinct questions the axis can pose, and asking for more does not create more.
    """
    words = _FR.split()
    lo, hi = 6, min(len(words), 26)
    out = []
    for k in sorted({lo + round(i * (hi - lo) / max(1, n - 1)) for i in range(n)}):
        # BOTH SIDES TERMINATED. Truncating the French mid-clause and leaving no full stop made
        # pii.extract_text return one unsegmentable blob — the paragraphs arrive space-joined, so
        # without sentence punctuation the two languages ran together and there was no boundary
        # to find. Every k>=12 sample "missed", and the detector was right each time: it was
        # being handed a single segment and asked to notice two. Verified directly — the base
        # corpus's lang-parts-long fires on the same construction because its sentences end.
        passage = " ".join(words[:k]).rstrip(",") + "."
        expect = {"3.1.2": ce.FAIL} if k >= 12 else {}

        def build(d, passage=passage):
            d.add_heading("Notice", level=1)
            d.add_paragraph(_EN + ".")
            d.add_paragraph(passage)
            return d
        out.append((f"lang-{k:02d}w", build, expect,
                    f"{k}-word French passage beside a {len(_EN.split())}-word English one — "
                    f"{'over' if k >= 12 else 'under'} the 12-word floor"))
    return out


# ── 1.1.1 · the junk-descr vocabulary ─────────────────────────────────────────

_JUNK = ["image1.png", "img_02.jpg", "picture 3", "photo", "graphic", "IMG_4821.JPEG",
         "media\\image7.png", "icons/user.svg", "  ", "1", "image", "Grafik", "bild.png"]
_REAL = ["Bar chart comparing Bronze and Silver premiums.",
         "Photograph of the main hospital entrance.",
         "Diagram of the referral process, described in the paragraph below."]


def sweep_alt(n: int) -> list[tuple[str, object, dict, str]]:
    """Each descr is a different string the junk predicate must judge — a real vocabulary, not a
    repetition. The compliant ones are included in the same sweep so the sample measures both
    directions; a predicate that called everything junk would score perfectly on the first half.
    """
    out = []
    cases = [(v, True) for v in _JUNK] + [(v, False) for v in _REAL]
    for i, (descr, is_junk) in enumerate(cases[:max(n, len(cases))]):
        expect = {"1.1.1": ce.FAIL} if is_junk else {}

        def build(d, descr=descr):
            d.add_heading("Coverage", level=1)
            _add_image(d, _content_png(7), alt=descr)
            return d
        out.append((f"alt-{i:02d}", build, expect,
                    f"descr={descr!r} — {'junk' if is_junk else 'a real description'}"))
    return out


SWEEPS = {"1.4.3": sweep_contrast, "3.1.2": sweep_language, "1.1.1": sweep_alt}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "Downloads" / "acp-docx-eval" / "sc-sweeps")
    ap.add_argument("--density", type=int, default=40,
                    help="samples per swept criterion (contrast/language); the alt sweep is "
                         "bounded by its vocabulary, which is a real list rather than a range")
    args = ap.parse_args()
    docs = args.out / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    manifest, problems, per_sc = [], [], {}
    for sc, fn in sorted(SWEEPS.items()):
        for name, build, expect, note in fn(args.density):
            d = build(_doc())
            d.save(docs / f"{name}.docx")
            for k, v in expect.items():
                if v not in ce.possible_verdicts(k, FMT):
                    problems.append(f"{name}: {k}={v} unreachable for ({k}, {FMT})")
            manifest.append({"file": f"docs/{name}.docx", "name": name, "kind": "sweep",
                             "format": FMT, "expect": expect, "note": note, "sweep_sc": sc})
            per_sc[sc] = per_sc.get(sc, 0) + (1 if expect else 0)
        print(f"  {sc:8} {sum(1 for m in manifest if m['sweep_sc'] == sc):>4} fixtures, "
              f"{per_sc.get(sc, 0):>4} seeded violations")

    if problems:
        print("\nIMPOSSIBLE EXPECTATIONS:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    scs = sorted(sc for sc, f in ce.pol.SCOPE_PRESETS["acp-core-17"].items() if FMT in f)
    (args.out / "manifest.json").write_text(json.dumps(
        {"format": FMT, "fixtures": manifest,
         "lanes": {sc: {"clean_verdict": ce.clean_verdict(sc, FMT),
                        "possible": sorted(ce.possible_verdicts(sc, FMT)),
                        "can_pass": ce.can_ever_pass(sc, FMT)} for sc in scs}}, indent=2) + "\n")
    print(f"\n{len(manifest)} fixtures -> {args.out / 'manifest.json'}")
    print("NOTE: consecutive samples share almost everything, so these are not fully independent "
          "trials.\nThe bound they support is 'the detector mishandles some input in this region',"
          "\nnot 'ACP is wrong about an arbitrary document'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
