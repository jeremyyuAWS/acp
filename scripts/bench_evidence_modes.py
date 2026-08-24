#!/usr/bin/env python3
"""P4.3 — Compare evidence modes A–D for the LLM judge.

Runs judge_drafts under each text evidence mode against the same item set and prints a
comparison table showing calibration (Pearson r vs. ground-truth fact-coverage where
available), mean usefulness, and inter-judge agreement per mode.

The comparison answers the minimum-viable-evidence question: how much of the deterministic
package ACP already has — OCR text, surrounding context, OOXML attributes — actually
changes the judge's accuracy? Mode B is the current default; D is the maximum text evidence.

Mode E (image crop) requires image_b64 fields and a vision-capable judge model; it is not
included here and must be run separately with judge_drafts.py --evidence-mode E.

Run:
    python scripts/bench_evidence_modes.py \\
        --input ~/Downloads/acp-docx-eval/results/drafts.json \\
        [--modes A,B,C,D] \\
        [--out ~/Downloads/acp-docx-eval/results/evidence_modes.json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from judge_drafts import EVIDENCE_MODES, JUDGES, _build_prompt, _guard, _parse  # noqa: E402

DEFAULT_MODES = ("A", "B", "C", "D")


def _run_mode(items: list[dict], mode: str, judges: list[str]) -> list[dict]:
    """Run every judge on every item under a single evidence mode."""
    results = []
    for item in items:
        prompt = _build_prompt(item, mode)
        scores: dict = {}
        for name in judges:
            try:
                scores[name] = _parse(JUDGES[name](prompt))
            except Exception as e:                                  # noqa: BLE001
                scores[name] = None
                print(f"    {mode}/{name} failed: {e.__class__.__name__}", file=sys.stderr)
        results.append({**item, "mode": mode, "scores": scores})
    return results


def _calibration_r(results: list[dict], judge: str) -> float | None:
    """Pearson r between truth_facts and judge accuracy score."""
    pairs = [
        (it["truth_facts"], (it["scores"].get(judge) or {}).get("accuracy"))
        for it in results
        if it.get("truth_facts") is not None and it["scores"].get(judge)
    ]
    pairs = [(a, b) for a, b in pairs if b is not None]
    if len(pairs) < 3:
        return None
    try:
        return statistics.correlation([x for x, y in pairs], [y for x, y in pairs])
    except statistics.StatisticsError:
        return None


def _mean_dim(results: list[dict], judge: str, dim: str) -> float | None:
    scores = [(it["scores"].get(judge) or {}).get(dim) for it in results]
    scores = [s for s in scores if s is not None]
    return statistics.mean(scores) if scores else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, required=True,
                    help="JSON list of items (same format as judge_drafts.py --input)")
    ap.add_argument("--modes", default=",".join(DEFAULT_MODES),
                    help="comma-separated evidence modes to compare (default: A,B,C,D)")
    ap.add_argument("--seed", type=int, default=7,
                    help="shuffle seed — keep consistent across mode runs for fair comparison")
    ap.add_argument("--out", type=Path,
                    help="write per-mode results as JSON for later analysis")
    args = ap.parse_args()

    src = _guard(args.input)
    all_items = json.loads(src.read_text())

    judges = [n for n in JUDGES
              if os.environ.get("ANTHROPIC_API_KEY" if n == "anthropic" else "OPENAI_API_KEY")]
    if not judges:
        raise SystemExit("No judge available — set ANTHROPIC_API_KEY and/or OPENAI_API_KEY.")

    modes = [m.strip().upper() for m in args.modes.split(",")]
    unknown = [m for m in modes if m not in EVIDENCE_MODES]
    if unknown:
        raise SystemExit(f"Unknown mode(s): {', '.join(unknown)}. "
                         f"Valid: {', '.join(EVIDENCE_MODES)}")

    print(f"judges: {', '.join(judges)}   items: {len(all_items)}   "
          f"modes: {', '.join(modes)}   seed: {args.seed}")

    import random
    shuffled = list(all_items)
    random.Random(args.seed).shuffle(shuffled)  # same order for every mode

    all_results: dict[str, list[dict]] = {}
    for mode in modes:
        print(f"\n--- Mode {mode}: {EVIDENCE_MODES[mode]} ---", flush=True)
        all_results[mode] = _run_mode(shuffled, mode, judges)
        for j in judges:
            r = _calibration_r(all_results[mode], j)
            u = _mean_dim(all_results[mode], j, "usefulness")
            n = sum(1 for it in all_results[mode] if (it["scores"].get(j) or {}).get("accuracy"))
            r_str = f"{r:+.2f}" if r is not None else "  N/A"
            u_str = f"{u:.2f}" if u is not None else "  N/A"
            print(f"  {j:10} cal_r={r_str}  useful={u_str}  n={n}")

    # ── comparison table ──────────────────────────────────────────────────────
    print("\n=== EVIDENCE MODE COMPARISON (P4.3) ===")
    col = 16
    header = f"{'mode':<5} {'evidence description':<55}"
    for j in judges:
        header += f"  {j[:col]:>{col}}"
    print(header)
    print("-" * (60 + col * len(judges) + 2 * len(judges)))

    for mode in modes:
        desc = EVIDENCE_MODES[mode][:53]
        row = f"{mode:<5} {desc:<55}"
        for j in judges:
            r = _calibration_r(all_results[mode], j)
            u = _mean_dim(all_results[mode], j, "usefulness")
            cell = (f"r={r:+.2f}" if r is not None else "r=  N/A")
            cell += f" U={u:.2f}" if u is not None else " U=  N/A"
            row += f"  {cell:>{col}}"
        print(row)

    # ── inter-judge agreement per mode ────────────────────────────────────────
    if len(judges) > 1:
        print("\n=== INTER-JUDGE AGREEMENT PER MODE ===")
        for mode in modes:
            both = [it for it in all_results[mode]
                    if all((it["scores"].get(j) or {}).get("usefulness") for j in judges)]
            if not both:
                continue
            diffs = [abs((both[i]["scores"][judges[0]] or {}).get("usefulness", 0) -
                         (both[i]["scores"][judges[1]] or {}).get("usefulness", 0))
                     for i in range(len(both))]
            print(f"  mode {mode}: mean |Δusefulness| = {statistics.mean(diffs):.2f} / 5"
                  f"  (n={len(both)})")

    # ── interpretation note ───────────────────────────────────────────────────
    best = max(modes, key=lambda m: max(
        (_calibration_r(all_results[m], j) or -1) for j in judges), default=None)
    if best:
        print(f"\nBest calibration: Mode {best} — {EVIDENCE_MODES[best]}")
        print("If B and D calibrate similarly, the added OOXML evidence is not helping the")
        print("judge. If D >> B, the deterministic evidence is load-bearing.")

    if args.out:
        out_doc = {
            "metadata": {
                "seed": args.seed,
                "judges": judges,
                "modes_run": modes,
                "run_at": datetime.datetime.utcnow().isoformat() + "Z",
            },
            "results_by_mode": all_results,
        }
        _guard(args.out.parent).joinpath(args.out.name).write_text(
            json.dumps(out_doc, indent=2) + "\n")
        print(f"\nwrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
