#!/usr/bin/env python3
"""Collect every local model's drafts into one file for the judge, with calibration items.

TWO KINDS OF ITEM, and the mix is the point:

  CALIBRATION  alt text for an image OF TEXT. Ground truth exists — the image's own OCR — so
               `truth_facts` carries the objective fact count. The judge scores these blind and
               judge_drafts.py correlates its accuracy scores against that number. A judge that
               tracks the known answers has earned an opinion on the unknown ones.

  UNMEASURABLE link rewrites, sensory rewrites, alt for textless images. No answer key exists,
               which is exactly why bench_models.py refuses to score them and why a judge is
               worth having at all.

Both go in one file, shuffled by the judge, so the judge cannot tell which of its scores are
being checked. Separating them would let a model — or a judge — behave differently on the graded
subset, which is the oldest failure in evaluation design.

Everything runs through api/ai.py, the shipped path, so these are drafts ACP would really offer.

Run:
    python scripts/collect_drafts_for_judging.py --out ~/Downloads/acp-docx-eval/results/drafts.json
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = Path.home() / "Downloads" / "acp-docx-eval"

VISION_MODELS = ["moondream", "granite3.2-vision", "qwen2.5vl:3b", "llava:7b",
                 "minicpm-v", "qwen2.5vl:7b", "qwen2.5vl:32b"]
TEXT_MODELS = ["llama3.1:8b", "qwen3:14b", "qwen3:32b"]

CALIBRATION_DIR = EVAL_ROOT / "calibration"      # gen_calibration_images.py writes here
PHOTO = ROOT / "frontend" / "public" / "samples" / "sample-image.png"

# Facts come from calibration/manifest.json, one set per image, each verified OCR-legible at
# generation time. Hard-coding one image's facts here is what limited the first calibration run
# to seven points — the answer key has to scale with the corpus or the correlation never does.
def load_calibration() -> list[dict]:
    mf = CALIBRATION_DIR / "manifest.json"
    if not mf.exists():
        print("no calibration corpus — run scripts/gen_calibration_images.py first",
              file=sys.stderr)
        return []
    return json.loads(mf.read_text())


TEXT_CASES = [
    ("2.4.4", "Link Purpose (In Context)",
     'link text is "click here"; the sentence reads "For the full accessibility policy, click here."'),
    ("1.3.3", "Sensory Characteristics",
     'instruction relies on shape/position alone: "Click the round green button on the right to continue."'),
    ("3.1.2", "Language of Parts",
     "an unmarked French passage: “Veuillez consulter la politique d’accessibilité avant le 31 mars.”"),
]


def _ai(model_env: str, model: str):
    os.environ[model_env] = model
    sys.path.insert(0, str(ROOT / "api"))
    import ai
    importlib.reload(ai)
    return ai


def fact_count(text: str, facts: dict[str, str]) -> int:
    """How many of THIS image's verified facts the draft conveys."""
    t = (text or "").lower()
    return sum(1 for pat in facts.values() if re.search(pat, t, re.S))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=EVAL_ROOT / "results" / "drafts.json")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    calib = load_calibration()
    if not calib:
        return 1
    print(f"calibration corpus: {len(calib)} images, "
          f"{sum(len(c['facts']) for c in calib)} verified facts")

    items: list[dict] = []
    photo = PHOTO.read_bytes() if PHOTO.exists() else None

    for m in VISION_MODELS:
        ai = _ai("OLLAMA_VISION_MODEL", m)
        n0 = len(items)
        # CALIBRATION — every image, so the judge is checked over a real sample rather than a
        # single document. `truth_facts` is the objective score judge_drafts.py correlates against.
        for c in calib:
            img = (CALIBRATION_DIR / c["file"]).read_bytes()
            out = ai.describe_image(img, filename=c["file"])
            alt = (out or {}).get("alt") or ""
            if alt:
                items.append({"model": m, "criterion": "1.1.1", "draft": alt,
                              "source": c["ocr"] or c["source_text"], "image": c["file"],
                              "truth_facts": fact_count(alt, c["facts"])})
        # UNMEASURABLE — a textless image; no answer key by construction, which is the case the
        # judge exists to cover.
        if photo:
            out = ai.describe_image(photo, filename=PHOTO.name)
            alt = (out or {}).get("alt") or ""
            if alt:
                items.append({"model": m, "criterion": "1.1.1", "draft": alt,
                              "source": "A chart image containing no readable text. There is no "
                                        "transcript; judge whether the description is plausible, "
                                        "specific and appropriately brief for an alt attribute."})
        print(f"  vision {m:18} -> {len(items) - n0} item(s)", flush=True)

    for m in TEXT_MODELS:
        ai = _ai("OLLAMA_MODEL", m)
        for sc, name, detail in TEXT_CASES:
            out = ai.suggest_fix(sc, name, "A", "benefits-notice.docx", detail=detail)
            draft = (out or {}).get("suggestion")
            if draft:
                items.append({"model": m, "criterion": sc, "draft": draft, "source": detail})
        print(f"  text   {m:18} -> {sum(1 for i in items if i['model'] == m)} item(s)", flush=True)

    args.out.write_text(json.dumps(items, indent=2) + "\n")
    cal = sum(1 for i in items if i.get("truth_facts") is not None)
    print(f"\n{len(items)} drafts ({cal} calibration, {len(items) - cal} unmeasurable)")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
