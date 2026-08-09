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

THE RUBRIC JUDGES LENGTH AGAINST THE IMAGE, NOT AGAINST A WORD COUNT — and the first version of
it did not. It scored `conciseness` and penalised over-length outright, on the reasoning that
WCAG 1.1.1 asks for a concise equivalent and a naive judge has a documented verbosity bias. Two
things were wrong with that. First, WCAG's own rule for an image OF TEXT is that the alt IS the
text, which the same product enforces elsewhere — so on a medication label or an enrolment
notice, length is the requirement, and a missing dose or deadline is a safety failure rather than
a style one. Second, it did not discriminate: every vision model landed between 2.45 and 3.18, a
flat penalty on all of them, so the dimension cost information and bought none.

It is now `completeness`, judged against what the source contains: transcripts should carry their
facts, textless images should not be padded with invented ones, and BOTH truncation and filler
are penalised. The verbosity bias the old wording guarded against is still real, so the rubric
says explicitly not to reward the longest draft — it just no longer treats brevity as the goal.
If this changes the model ranking, that is a finding about the first rubric and should be
reported as one.

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
The reader is a hospital: these documents carry clinical and benefits information, and a
patient using a screen reader hears ONLY this text in place of the image.

Score each dimension 0-5. Reply with ONLY a JSON object, no prose:
{"accuracy": n, "completeness": n, "usefulness": n, "note": "one short sentence"}

accuracy      Does it state only what the source supports? A confident wrong fact — a wrong
              date, an invented dosage, a made-up label — scores 0. Omission is judged under
              completeness, not here.

completeness  Does it carry the information a reader needs, at a length suited to WHAT THE
              IMAGE CONTAINS? Judge against the source, not against a word count.
              - If the SOURCE is a transcript of text in the image (a notice, a label, a
                form, a lab result), the alt text SHOULD carry that information. WCAG's rule
                for an image of text is that the alt IS the text. Missing a dose, a deadline,
                a phone number or a warning is a REAL FAILURE — on a medication label an
                incomplete alt is a safety problem, not a style problem. Length that serves
                completeness is CORRECT, not verbose.
              - If the SOURCE says the image has no readable text (a photo, a chart), there
                is less to convey: a brief description that names the subject is right, and
                padding it with invented specifics is wrong.
              - For link text (2.4.4) and rewritten instructions (1.3.3), the draft replaces
                a phrase in running prose; it should say what the original failed to say
                without becoming a paragraph.
              Score 5 for "carries what a reader needs and no filler". Penalise BOTH
              truncation and padding. Do not penalise length by itself.

usefulness    Could a reviewer accept this as-is, unchanged? A placeholder such as
              "[button label]" is honest but unusable — score it low here even when accuracy
              is high.

Judge the DRAFT against the SOURCE only. Do not reward whichever is longest, and do not
reward brevity for its own sake."""


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
        return {k: float(d.get(k, 0)) for k in ("accuracy", "completeness", "usefulness")} | {
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
            for dim in ("accuracy", "completeness", "usefulness"):
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
    print(f"{'model':18}{'accuracy':>10}{'complete':>10}{'useful':>9}{'n':>5}")
    for m, ss in sorted(by.items()):
        print(f"{m:18}{statistics.mean(s['accuracy'] for s in ss):>10.2f}"
              f"{statistics.mean(s['completeness'] for s in ss):>10.2f}"
              f"{statistics.mean(s['usefulness'] for s in ss):>9.2f}{len(ss):>5}")

    if args.out:
        _guard(args.out.parent).joinpath(args.out.name).write_text(
            json.dumps(items, indent=2) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
