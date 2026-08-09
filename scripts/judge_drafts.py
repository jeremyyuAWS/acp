#!/usr/bin/env python3
"""LLM-as-judge for the local models' drafts — calibrated before it is believed.

WHAT THIS IS FOR. Two of the three things we want to score have no ground truth: link-text
rewrites and sensory-instruction rewrites ("is this good link text?"), and alt text for
photographs. scripts/bench_models.py refuses to score them for that reason. A judge is the right
instrument there — but only once it has been shown to agree with a known answer.

CALIBRATION FIRST, and this is the whole design. Alt text for an image OF TEXT has an objective
answer key: the image's own OCR, scored as fact coverage (see measure_alt_fact_coverage.py). The
judge scores those SAME items, and its scores are compared with the objective ones. A judge that
tracks ground truth where ground truth exists has earned an opinion where it does not. One that
does not has told us so before anything was published.

TWO JUDGES, and not for redundancy. Anthropic and OpenAI are independent; their agreement on the
unmeasurable items is a second axis. A single judge gives a number, two give a number with an
error bar. Either alone still runs — the calibration axis works with one.

THE RUBRIC EXISTS BECAUSE A NAIVE JUDGE WOULD INVERT OUR RECOMMENDATION. Asked to "rate this alt
text 1-10", both judges reliably prefer the longer, more thorough description — a documented
verbosity bias. But WCAG 1.1.1 asks for a CONCISE equivalent: a 33-word alt naming a portal and a
fallback rule is an excellent long description and a poor `alt`. So conciseness is scored as its
own dimension, and over-length is penalised rather than rewarded. Left implicit, the judge would
confidently recommend the 21GB model we measured as the worse choice.

BLIND AND SHUFFLED. Model names are stripped and candidate order is randomised per item. Judges
show position bias, and a judge that can see "moondream" versus "qwen2.5vl:32b" is scoring a
reputation, not a draft.

NO PRODUCT DEPENDENCY. Uses httpx, not the vendor SDKs: ADR 0019/0022 rest on ACP having "no
third-party AI SDK/key", and adding one to api/requirements.txt for a benchmark would falsify
that claim in the artefact that documents it.

PHI BOUNDARY, ENFORCED NOT INTENDED. This sends document text to a third party. That is
acceptable for the SYNTHETIC eval corpus and unacceptable for a customer estate, so the input
path is checked against the eval directory and refused otherwise. A comment would not survive
this script being reused on a real scan six months from now.

Keys come from the environment and are never logged:
    export ANTHROPIC_API_KEY=...
    export OPENAI_API_KEY=...

Run:
    python scripts/judge_drafts.py --input ~/Downloads/acp-docx-eval/results/drafts.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from pathlib import Path

EVAL_ROOT = (Path.home() / "Downloads" / "acp-docx-eval").resolve()

RUBRIC = """You are grading a single draft produced by an accessibility remediation tool.

Score each dimension 0-5. Reply with ONLY a JSON object, no prose:
{"accuracy": n, "conciseness": n, "usefulness": n, "note": "one short sentence"}

accuracy     Does it state only what is supported by the source? A confident wrong fact
             (a wrong date, an invented label) scores 0. Omission is not inaccuracy.
conciseness  Is the length RIGHT FOR ITS PURPOSE, not merely short?
             - For alt text (WCAG 1.1.1): a concise equivalent. Roughly 5-20 words. A
               longer, more thorough description is WORSE as alt text, not better — it
               belongs in a long description. Penalise over-length.
             - For link text (2.4.4): names the destination, a few words.
             - For a rewritten instruction (1.3.3): about as long as what it replaces.
usefulness   Could a reviewer accept this as-is? A placeholder like "[button label]" is
             honest but not usable: score it low here and high on accuracy.

Judge the DRAFT against the SOURCE only. You are not being asked which is longest or
most impressive."""


def _guard(path: Path) -> Path:
    """Refuse anything outside the synthetic eval corpus.

    This script ships document text to a third-party API. On generated fixtures that is fine;
    on a customer's estate it is a PHI disclosure. The check is here rather than in the
    docstring because the risk is not someone misreading the intent today — it is this script
    being pointed at a real scan later by someone who never read it.
    """
    p = path.resolve()
    if not str(p).startswith(str(EVAL_ROOT)):
        raise SystemExit(
            f"REFUSED: {p}\nThis sends text to a third-party API and is restricted to the "
            f"synthetic eval corpus under {EVAL_ROOT}.\nIf you need to judge other content, "
            "move it there deliberately — do not widen this check.")
    return p


def _post(url: str, headers: dict, payload: dict) -> str:
    import httpx
    r = httpx.post(url, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.text


def ask_anthropic(prompt: str, model: str = "claude-sonnet-5") -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = json.loads(_post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"model": model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}))
    return "".join(b.get("text", "") for b in body.get("content", []))


def ask_openai(prompt: str, model: str = "gpt-4o") -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    body = json.loads(_post(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "content-type": "application/json"},
        {"model": model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}))
    return body["choices"][0]["message"]["content"]


JUDGES = {"anthropic": ask_anthropic, "openai": ask_openai}


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        s = raw[raw.index("{"):raw.rindex("}") + 1]
        d = json.loads(s)
        return {k: float(d.get(k, 0)) for k in ("accuracy", "conciseness", "usefulness")} | {
            "note": str(d.get("note", ""))[:200]}
    except (ValueError, KeyError, TypeError):
        return None


def judge_item(item: dict, judges: list[str]) -> dict:
    """One item, every judge. Blind: the model name never reaches the prompt."""
    prompt = (f"{RUBRIC}\n\n--- CRITERION ---\n{item['criterion']}\n"
              f"--- SOURCE (what the document actually contains) ---\n{item['source']}\n"
              f"--- DRAFT ---\n{item['draft']}\n")
    out = {}
    for name in judges:
        try:
            out[name] = _parse(JUDGES[name](prompt))
        except Exception as e:                                     # noqa: BLE001
            out[name] = None
            print(f"    {name} failed: {e.__class__.__name__}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, required=True,
                    help="JSON list of {model, criterion, source, draft, truth_facts?}")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seed", type=int, default=7, help="shuffle seed, recorded for repeatability")
    args = ap.parse_args()

    src = _guard(args.input)
    items = json.loads(src.read_text())
    judges = [n for n in JUDGES if os.environ.get(
        "ANTHROPIC_API_KEY" if n == "anthropic" else "OPENAI_API_KEY")]
    if not judges:
        raise SystemExit("No judge available — set ANTHROPIC_API_KEY and/or OPENAI_API_KEY.")
    print(f"judges: {', '.join(judges)}   items: {len(items)}")

    random.Random(args.seed).shuffle(items)      # order bias is real; the seed makes it repeatable
    for i, it in enumerate(items, 1):
        it["scores"] = judge_item(it, judges)
        got = {j: (s or {}).get("usefulness") for j, s in it["scores"].items()}
        print(f"  [{i}/{len(items)}] {it['criterion']:6} {it.get('model', '?'):16} {got}",
              flush=True)

    # ---- calibration: does the judge track the objective measure where one exists? ----
    cal = [it for it in items if it.get("truth_facts") is not None]
    if cal:
        print("\n=== CALIBRATION — judged accuracy vs OCR fact coverage ===")
        for j in judges:
            pairs = [(it["truth_facts"], (it["scores"][j] or {}).get("accuracy"))
                     for it in cal if it["scores"].get(j)]
            pairs = [(a, b) for a, b in pairs if b is not None]
            if len(pairs) < 3:
                print(f"  {j:10} too few scored items to calibrate ({len(pairs)})")
                continue
            xs, ys = zip(*pairs)
            try:
                r = statistics.correlation(xs, ys)
                verdict = ("tracks ground truth" if r >= 0.6 else
                           "WEAK — treat its unmeasurable scores with suspicion")
                print(f"  {j:10} r={r:+.2f} over {len(pairs)} items — {verdict}")
            except statistics.StatisticsError:
                print(f"  {j:10} no variance to correlate")

    # ---- inter-judge agreement on everything ----
    if len(judges) > 1:
        both = [it for it in items if all(it["scores"].get(j) for j in judges)]
        if both:
            print("\n=== INTER-JUDGE AGREEMENT ===")
            for dim in ("accuracy", "conciseness", "usefulness"):
                a = [it["scores"][judges[0]][dim] for it in both]
                b = [it["scores"][judges[1]][dim] for it in both]
                diff = statistics.mean(abs(x - y) for x, y in zip(a, b))
                print(f"  {dim:12} mean |difference| = {diff:.2f} / 5")

    # ---- per-model summary ----
    print("\n=== BY MODEL (mean across judges) ===")
    by: dict[str, list] = {}
    for it in items:
        for s in it["scores"].values():
            if s:
                by.setdefault(it.get("model", "?"), []).append(s)
    print(f"{'model':18}{'accuracy':>10}{'concise':>10}{'useful':>9}{'n':>5}")
    for m, ss in sorted(by.items()):
        print(f"{m:18}{statistics.mean(s['accuracy'] for s in ss):>10.2f}"
              f"{statistics.mean(s['conciseness'] for s in ss):>10.2f}"
              f"{statistics.mean(s['usefulness'] for s in ss):>9.2f}{len(ss):>5}")

    if args.out:
        _guard(args.out.parent).joinpath(args.out.name).write_text(
            json.dumps(items, indent=2) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
