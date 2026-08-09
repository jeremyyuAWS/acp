#!/usr/bin/env python3
"""Alt-text fact coverage per vision model, repeated, with variance.

WHY REPEATS. Vision models sample. `moondream` described one bar chart as "Urn of purple bars on
a white background" on one run and "The image presents a bar graph with six vertical bars" on
another — same image, same prompt. A single run cannot distinguish a worse model from a noisier
one, and a mean without a range invites a reader to treat 3/6 as precise.

WHY FACT COVERAGE. There is no ground truth for "good alt text", which is why bench_models.py
refuses to score. But when the image is an image OF TEXT, ground truth is its own OCR, and "how
many of the document's facts does the alt carry?" is countable and arguable. That is the only
defensible accuracy metric available here, and it does NOT generalise to photographs.

A fact counts only when fully conveyed: "2026" alone is not the title, "March 1" alone is not the
window. Conjunctions are lookaheads inside one alternative so alternatives stay alternatives — an
earlier version required ALL patterns and made the window unscoreable, silently costing every
model one fact.

Run:
    python scripts/measure_alt_fact_coverage.py --runs 3
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODELS = ["moondream", "llava:7b", "qwen2.5vl:7b", "qwen2.5vl:32b"]
IMAGE = ROOT / "frontend" / "public" / "samples" / "enrollment-notice.png"

# The six facts in that notice. Ground truth is the image's OCR, not a hand-written summary.
FACTS = {
    "title": [r"(?=.*open enrollment)(?=.*2026)"],
    "window": [r"march\s*1\b.*march\s*31", r"march\s*1\s*[-–]\s*31"],
    "coverage": [r"medical.*dental.*vision"],
    "portal": [r"ut\s*southwestern"],
    "consequence": [r"(?=.*default)(?=.*prior year)"],
    "contact": [r"214[-\s]?648[-\s]?9999"],
}


def facts_in(text: str) -> list[str]:
    t = (text or "").lower()
    return [k for k, pats in FACTS.items() if any(re.search(p, t, re.S) for p in pats)]


def one_run(model: str, img: bytes):
    os.environ["OLLAMA_VISION_MODEL"] = model
    sys.path.insert(0, str(ROOT / "api"))
    import ai
    importlib.reload(ai)
    t0 = time.time()
    try:
        out = ai.describe_image(img, filename="enrollment-notice.png")
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "err": f"{e.__class__.__name__}: {e}",
                "secs": round(time.time() - t0, 1), "facts": [], "alt": ""}
    secs = round(time.time() - t0, 1)
    alt = (out or {}).get("alt") or ""
    return {"ok": bool(alt), "secs": secs, "alt": alt, "facts": facts_in(alt),
            "words": len(alt.split())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--image", type=Path, default=IMAGE)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    img = args.image.read_bytes()
    results = {}
    for model in MODELS:
        runs = []
        for i in range(args.runs):
            r = one_run(model, img)
            runs.append(r)
            print(f"  {model:16} run{i + 1}  {r['secs']:5.1f}s  "
                  f"{len(r['facts'])}/{len(FACTS)}  {r['alt'][:64]}", flush=True)
        results[model] = runs

    print(f"\n{'model':16}{'facts mean':>12}{'range':>10}{'sd':>7}"
          f"{'secs mean':>11}{'produced':>10}")
    for model, runs in results.items():
        f = [len(r["facts"]) for r in runs]
        s = [r["secs"] for r in runs]
        ok = sum(1 for r in runs if r["ok"])
        sd = statistics.stdev(f) if len(f) > 1 else 0.0
        print(f"{model:16}{statistics.mean(f):>9.1f}/{len(FACTS)}"
              f"{f'{min(f)}-{max(f)}':>10}{sd:>7.2f}"
              f"{statistics.mean(s):>11.1f}{f'{ok}/{len(runs)}':>10}")

    # Which facts each model conveyed AT LEAST ONCE vs EVERY time — the gap is the instability,
    # and it is more useful than the mean when deciding whether a model is dependable.
    print("\nfact stability (conveyed in every run / at least one run):")
    for model, runs in results.items():
        sets = [set(r["facts"]) for r in runs]
        always = set.intersection(*sets) if sets else set()
        ever = set.union(*sets) if sets else set()
        print(f"  {model:16} always={sorted(always) or '[]'}  "
              f"only-sometimes={sorted(ever - always) or '[]'}")

    if args.out:
        args.out.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
