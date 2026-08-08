#!/usr/bin/env python3
"""Run each local model over the DOCX eval corpus and score what it actually fixed.

ONE AXIS AT A TIME. A grid of every vision model against every text model would be 12 runs whose
differences cannot be attributed to either. The vision sweep holds the text model fixed and the
text sweep holds the vision model fixed, so a change in the result is a change in the one model
that moved.

WHAT IS SCORED. Per fixture, the criteria the remediation actually applied, against the criteria
the manifest says the fixture breaks. Three outcomes per expected criterion:

    fixed     the criterion appears in the applied-fix list
    missed    the fixture breaks it and nothing was applied
    extra     a fix for a criterion the fixture was not built to break

`extra` is reported rather than ignored: a model that "fixes" a criterion the document does not
violate is not scoring a point, it is editing a document for no reason — which on a hospital's
file is worse than doing nothing.

THE CONTROLS MATTER. 1.3.1, 1.4.3, 2.4.2, 2.4.6 and 3.1.1 are deterministic rule code on .docx.
They MUST come out identical for every model. If they do not, this harness is measuring something
other than the model and the comparison is void — so they are checked explicitly, not assumed.

Run:
    python scripts/eval_models_docx.py --sweep vision
    python scripts/eval_models_docx.py --sweep text --out /tmp/text_eval.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "test-corpus" / "model-eval"

# Vision sweep holds the TEXT model at the shipped default; text sweep holds VISION at the model
# today's measurement picked as the sweet spot. Neither is a claim about the best pairing — they
# are constants so the moving axis is the only explanation for a difference.
SWEEPS = {
    "vision": ("OLLAMA_VISION_MODEL",
               ["moondream", "llava:7b", "qwen2.5vl:7b", "qwen2.5vl:32b"],
               {"OLLAMA_MODEL": "llama3.1:8b"}),
    "text": ("OLLAMA_MODEL",
             ["llama3.1:8b", "qwen3:14b", "qwen3:32b"],
             {"OLLAMA_VISION_MODEL": "qwen2.5vl:7b"}),
}

DETERMINISTIC = {"1.3.1", "1.4.3", "2.4.2", "2.4.6", "3.1.1"}
_SC = re.compile(r"\b(\d+\.\d+\.\d+)\b")


def criteria_from(summaries, applied, diffs):
    """Criteria touched by one remediation run, from all THREE channels.

    They carry different things and no one of them is complete:

      summaries    end in "· 1.3.1" for most deterministic fixes
      applied_fixes carry rule_id ("SC_1_1_1") for the AI-drafted ones
      diffs        carry rule_id for fixes whose SUMMARY has no suffix

    That third channel is not defensive padding. `_ensure` (remediate_office.py:1313) formats
    its label without the criterion — "Set document language to 'en-US'" — while passing the
    SC to _rec(diffs, ...). Reading only the first two scored 2.4.2 and 3.1.1 as MISSED on a
    document where both were fixed, and they are DETERMINISTIC controls: the harness would
    have reported the control group failing and invalidated its own comparison.
    """
    out = set()
    for s in summaries or []:
        out.update(_SC.findall(str(s)))
    for coll in (applied or [], diffs or []):
        for f in coll:
            rid = (f or {}).get("rule_id") if isinstance(f, dict) else getattr(f, "rule_id", "")
            out.update(_SC.findall(str(rid or "").replace("_", ".")))
    return out


def run_one(path: Path, tmp: Path):
    """Remediate ONE file, returning (criteria, seconds, n_applied, n_proposals, error).

    Proposals are counted separately and deliberately. On .docx the ASSISTED criteria do not
    auto-apply — an ungrounded draft goes to `proposals` for a human to approve, by design — so
    a model can do excellent work and move `applied` not at all. Counting only applied fixes
    would score every text model identically at zero and call that "no difference between
    models"."""
    import importlib
    import shutil
    sys.path.insert(0, str(ROOT / "api"))
    import ai
    import remediate_office
    importlib.reload(ai)                 # pick up the env for this sweep step
    importlib.reload(remediate_office)

    work = tmp / path.name
    shutil.copy(path, work)
    applied: list = []
    diffs: list = []
    proposals: list = []
    t0 = time.time()
    try:
        res = remediate_office.remediate_office(work, ai_enabled=True, applied_fixes=applied,
                                                diffs=diffs, proposals=proposals)
    except Exception as e:                                        # noqa: BLE001
        return set(), round(time.time() - t0, 1), 0, 0, f"{e.__class__.__name__}: {e}"
    summaries = res[1] if isinstance(res, tuple) and len(res) > 1 else []
    return (criteria_from(summaries, applied, diffs), round(time.time() - t0, 1),
            len(applied), len(proposals), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", choices=sorted(SWEEPS), required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    args = ap.parse_args()

    manifest = json.loads((args.corpus / "manifest.json").read_text())
    var, models, fixed = SWEEPS[args.sweep]
    for k, v in fixed.items():
        os.environ[k] = v

    import tempfile
    results = {}
    for model in models:
        os.environ[var] = model
        print(f"\n=== {var}={model} ===", flush=True)
        per_file = {}
        for entry in manifest:
            path = args.corpus / entry["file"]
            with tempfile.TemporaryDirectory() as td:
                got, secs, n_ai, n_prop, err = run_one(path, Path(td))
            exp = set(entry["expect_criteria"])
            per_file[entry["file"]] = {
                "expected": sorted(exp), "fixed": sorted(got & exp),
                "missed": sorted(exp - got), "extra": sorted(got - exp),
                "secs": secs, "ai_fixes": n_ai, "proposals": n_prop, "error": err,
            }
            mark = "·" if not exp else ("OK " if not (exp - got) else "MISS")
            print(f"  {mark:4} {entry['file']:22} {secs:6.1f}s  prop={n_prop}  "
                  f"fixed={sorted(got & exp)} missed={sorted(exp - got)}", flush=True)
        results[model] = per_file

    print("\n=== control check (deterministic criteria) ===")
    drift = []
    for entry in manifest:
        for sc in set(entry["expect_criteria"]) & DETERMINISTIC:
            got = {m: sc in results[m][entry["file"]]["fixed"] for m in models}
            if len(set(got.values())) > 1:
                drift.append((entry["file"], sc, got))
    if drift:
        for f, sc, got in drift:
            print(f"  DRIFT {f} {sc}: {got}")
        print("  ^ a deterministic criterion moved with the model - this comparison is VOID")
    else:
        print(f"  stable across all {len(models)} models - the moving axis is the model")

    if args.out:
        args.out.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
