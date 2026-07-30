#!/usr/bin/env python3
"""Vision alt-text quality eval + model bake-off (ADR 0019 acceptance policy, task #93).

Runs the APP's real structured vision path (`ai.describe_image_structured`, OCR-grounded, the
hardened no-fabricated-values prompt) over a labelled corpus and scores each description on four
honest, checkable axes — type named, subject captured, grounding flag correct, and NO fabricated
figures on data charts (the ADR 0016 gate llava tends to violate). Repeat across models to compare
quality vs latency and inform the production vision-model choice.

Usage (point at any Ollama, local or a GPU pod):
  OLLAMA_BASE_URL=https://<pod>-11434.proxy.runpod.net \
  .venv-drive/bin/python scripts/vision_eval.py --models llava:13b llava:7b llama3.2-vision:11b

Not a unit test (needs a model + the corpus); a runnable, re-runnable quality harness.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402

# A stated figure on a data chart is the confabulation signal — llava can't map bar→value reliably,
# so any specific value is presumed wrong (ADR 0016). Catches: a currency ("$150"), a percentage
# ("45%"), a magnitude ("705 million"), AND a category↔value pairing ("legal at 87", "sales with
# 25%", "score of 60") — the last is llava's actual failure mode and must not slip through, or the
# eval would give the same false confidence it exists to catch.
_FIGURE = re.compile(
    r"\$\s?\d"                                                        # $150
    r"|\b\d+(?:\.\d+)?\s?%"                                           # 45%
    r"|\b\d+(?:\.\d+)?\s?(?:million|thousand|billion|percent)\b"      # 705 million
    r"|\b(?:at|with|of|is|reached|reaching|total(?:ing|led)?|score[sd]?)\s+\$?\d{1,3}(?!\d)",  # "at 87" (not years like 2026)
    re.I,
)


def _load_labels(path: Path) -> dict:
    return json.loads(path.read_text())


def _image_bytes(corpus: Path, file: str, member: str) -> bytes | None:
    p = corpus / file
    if not p.exists():
        return None
    with zipfile.ZipFile(p) as z:
        return z.read(member) if member in z.namelist() else None


def _score(alt: str, grounded, label: dict) -> dict:
    a = (alt or "").lower()
    type_ok = any(t in a for t in label["type_any"])
    subj_hits = sum(1 for s in label["subject_any"] if s in a)
    subject_ok = subj_hits >= label.get("min_subject", 1)
    grounded_ok = (bool(grounded) == bool(label["expect_grounded"]))
    fabricated = bool(label.get("forbid_values")) and bool(_FIGURE.search(alt or ""))
    ok = type_ok and subject_ok and grounded_ok and not fabricated
    return {"type_ok": type_ok, "subject_ok": subject_ok, "grounded_ok": grounded_ok,
            "no_fabrication": not fabricated, "pass": ok}


def run_model(model: str, labels: dict, corpus: Path) -> dict:
    # Pin the model for the whole run. Assigning the global is not enough on its own: every
    # describe_image_structured call goes through ai._maybe_refresh_endpoint(), which reassigns
    # OLLAMA_VISION_MODEL from the store override / env default on a 30s TTL — so the first image
    # silently reverted the bake-off to whatever the environment says and every later `--models`
    # entry scored the SAME model. That is invisible in the output (it prints the name you asked
    # for) and it inverted a real comparison on 2026-07-30: moondream, warm, was reported as
    # qwen2.5vl:7b at 0.14 pass / 520ms, against qwen's actual 0.71 / 9920ms.
    #
    # The harness is the thing choosing the model here, so the runtime override has no business
    # overruling it — stub the refresh out rather than trying to out-race its TTL.
    ai._maybe_refresh_endpoint = lambda: None
    ai.OLLAMA_VISION_MODEL = model          # module global read at call time by _vision_generate
    ai.reset_probe_cache()                  # the availability probe must re-check for THIS model
    rows, latencies, missing = [], [], 0
    for label in labels["images"]:
        data = _image_bytes(corpus, label["file"], label["member"])
        if not data:
            missing += 1
            continue
        t0 = time.monotonic()
        res = ai.describe_image_structured(data, filename=label["file"])
        dt = (time.monotonic() - t0) * 1000
        latencies.append(dt)
        alt = (res or {}).get("alt", "")
        grounded = (res or {}).get("grounded")
        sc = _score(alt, grounded, label)
        rows.append({"member": label["member"], "alt": alt, "latency_ms": round(dt), **sc})
    n = len(rows) or 1
    agg = {k: sum(1 for r in rows if r[k]) for k in ("type_ok", "subject_ok", "grounded_ok", "no_fabrication", "pass")}
    return {"model": model, "n": len(rows), "missing": missing,
            "avg_latency_ms": round(sum(latencies) / (len(latencies) or 1)),
            "pass_rate": round(agg["pass"] / n, 2), "agg": agg, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=[ai.OLLAMA_VISION_MODEL])
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--labels", default=str(Path(__file__).with_name("vision_eval_labels.json")))
    ap.add_argument("--repeat", type=int, default=1, help="runs per model — averages out llava's stochastic output")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    labels = _load_labels(Path(args.labels))
    corpus = Path(args.corpus or labels.get("corpus_default", ".")).expanduser()
    print(f"corpus: {corpus}  |  images: {len(labels['images'])}  |  repeat: {args.repeat}  |  zone: {ai.provenance()['zone']}\n")

    summary = []
    for m in args.models:
        runs = [run_model(m, labels, corpus) for _ in range(args.repeat)]
        n = runs[0]["n"] or 1
        # Average the per-axis pass COUNTS across runs, so a stochastic fabrication shows as a fraction.
        avg = {k: sum(r["agg"][k] for r in runs) / len(runs) for k in runs[0]["agg"]}
        summary.append({"model": m, "n": n,
                        "pass_rate": round(sum(r["pass_rate"] for r in runs) / len(runs), 2),
                        "avg": avg, "lat": round(sum(r["avg_latency_ms"] for r in runs) / len(runs)),
                        "runs": runs})
    hdr = f"{'model':22} {'pass':>6} {'type':>7} {'subj':>7} {'gnd':>7} {'no-fab':>7} {'lat(ms)':>8}"
    print(hdr); print("-" * len(hdr))
    for s in summary:
        a = s["avg"]; n = s["n"]
        print(f"{s['model']:22} {s['pass_rate']:>6} {a['type_ok']:>4.1f}/{n} {a['subject_ok']:>4.1f}/{n} "
              f"{a['grounded_ok']:>4.1f}/{n} {a['no_fabrication']:>4.1f}/{n} {s['lat']:>8}")
    if args.verbose:
        for s in summary:
            print(f"\n=== {s['model']} (last run) ===")
            for row in s["runs"][-1]["rows"]:
                print(f"  [{'PASS' if row['pass'] else 'FAIL'}] {row['member']} ({row['latency_ms']}ms): {row['alt']}")
    return summary


if __name__ == "__main__":
    main()
