#!/usr/bin/env python3
"""Run the same .docx remediation drafts through several local models and print them side by side.

WHY THIS EXISTS. ACP's AI lane is a local Ollama instance (api/ai.py), and the models it defaults
to were chosen under a constraint that no longer applies everywhere: deploy/ollama/Dockerfile
records that llava:7b + llama3.1:8b came to ~9.2GB and OOM-killed the container against an 8Gi
Azure Consumption ceiling, so the vision model became moondream — "a compact captioner, not a 7B
VLM; revisit if alt-text quality regresses". On a workstation with real memory that trade is not
forced, and nothing in the repo made it easy to find out what a bigger model would do.

WHAT IT DOES NOT DO. It does not score. There is no ground truth for "good alt text" and inventing
a number would be worse than no number — a 7.4 that nobody can defend gets quoted in a deck. It
prints the drafts, the latency and the model, and a person reads them. The comparison is the
deliverable; the judgement stays human, which is the same posture ai.py itself takes (draft →
approve → apply, never auto-write).

WHAT IT COVERS. The .docx surfaces that actually call the model:

    1.1.1  alt text            VISION  — the weakest today, and the reason to run this
    1.3.3  sensory rewrite     text
    2.4.4  link purpose        text
    3.1.2  language of parts   text
    4.1.2  form field name     text

Usage:
    python scripts/bench_models.py --models llama3.1:8b qwen3:14b
    python scripts/bench_models.py --models qwen2.5vl:7b --vision-only --image path/to.png
    python scripts/bench_models.py --list           # what the server already has

    python scripts/bench_models.py --ladder vision --pull --image path/to.png
    python scripts/bench_models.py --ladder all --pull

--ladder runs a fixed set of rungs smallest-first, each including the model that ships today, so
every run carries its own baseline. It answers the question one model cannot: not "is this good"
but "where does quality stop improving" — which is what decides whether a bigger GPU elsewhere
would buy anything. --pull is the explicit opt-in to downloading missing rungs; it prints the
sizes first, because the top rungs are tens of gigabytes.

A model that is not pulled is REPORTED AND SKIPPED, not pulled silently: a benchmark that
downloads 20GB because of a typo in a model name is not a benchmark anybody runs twice.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

# One representative finding per criterion, phrased the way the real detector reports it, so the
# prompt a model sees here is the prompt it would see in a scan. Not fixtures on disk: these are
# the DETAIL strings ai.suggest_fix receives, and hand-writing them keeps the harness runnable
# without a scan, a database or a corpus build.
CASES = [
    ("1.3.3", "Sensory Characteristics", "A",
     "instruction relies on shape/position alone: “click the round button on the right to continue”"),
    ("2.4.4", "Link Purpose (In Context)", "A",
     "link text is “click here”; the surrounding sentence is "
     "“For the full accessibility policy, click here.”"),
    ("3.1.2", "Language of Parts", "AA",
     "an unmarked French passage: “Veuillez consulter la politique d’accessibilité.”"),
    ("4.1.2", "Name, Role, Value", "A",
     "a content control with no Title (w:alias); nearby label text reads “Date of birth”"),
]


# Rungs, smallest first. The point of a ladder rather than a favourite is that it answers a
# question a single model cannot: not "is this one good" but "where does quality STOP improving".
# That shape is what tells you whether a bigger Azure container would buy anything — a curve that
# is still climbing at the top rung says the ceiling is model size; one that flattens at 7B says
# more GPU buys a flat line, and the honest move is to spend the effort on prompts instead.
#
# Rung 0 of each is what ships TODAY, so every run includes its own baseline. A comparison that
# omits the incumbent measures the candidates against nothing.
#
# Sizes are approximate 4-bit quantised footprints, listed because the top rungs are the reason
# this machine exists and the reason they were not options before: deploy/ollama/Dockerfile
# records llava:7b + llama3.1:8b OOM-killing an 8Gi container.
LADDER = {
    "vision": [
        ("moondream", "~1.7GB", "ships today — a compact captioner, not a VLM"),
        ("llava:7b", "~4.7GB", "the model the 8Gi ceiling rejected"),
        ("qwen2.5vl:7b", "~6GB", "a current-generation 7B VLM"),
        ("qwen2.5vl:32b", "~21GB", "only reachable with real memory"),
    ],
    "text": [
        ("llama3.1:8b", "~4.9GB", "ships today"),
        ("qwen3:14b", "~9GB", ""),
        ("qwen3:32b", "~20GB", ""),
    ],
}


def _norm(model: str) -> str:
    """`moondream` and `moondream:latest` are the same model. Ollama's /api/tags always answers
    with the explicit tag, so comparing raw strings makes an installed bare-named model report as
    missing — and the "report and skip" path then drops it from the run.

    That failed silently in the worst possible place: moondream is rung 0 of the vision ladder,
    the model that SHIPS, so the baseline vanished from the comparison and every candidate was
    left being measured against nothing. Observed with moondream:latest present on the server.
    """
    return model if ":" in model else f"{model}:latest"


def _pull_hint(model: str) -> str:
    """Tell the user how to pull FOR THE SERVER THEY ARE ACTUALLY TALKING TO.

    The old text said `docker compose exec ollama ollama pull` unconditionally. That command
    fails outright once Ollama runs natively — which is the recommended setup on macOS, where a
    containerised Ollama gets no GPU — and it fails as "no such service", which sends people to
    debug compose rather than to pull a model.
    """
    if "host.docker.internal" in BASE or "localhost" in BASE or "127.0.0.1" in BASE:
        return f"ollama pull {model}"
    return f"docker compose exec ollama ollama pull {model}"


def _get(path: str, timeout: int = 10):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def installed() -> list[str]:
    try:
        return sorted(m.get("name", "") for m in (_get("/api/tags").get("models") or []))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SystemExit(
            f"Cannot reach Ollama at {BASE} ({e.__class__.__name__}).\n"
            "  native (macOS — the only way to get the GPU):  brew services start ollama\n"
            "  in the stack (Linux):  cd deploy/compose && docker compose up -d ollama\n"
            "…or set OLLAMA_BASE_URL if it runs elsewhere.")


def run_case(model: str, rule_id: str, rule_name: str, level: str, detail: str) -> dict:
    """One suggest_fix draft, through api/ai.py rather than a hand-rolled prompt.

    Going through ai.py is the point: a bespoke prompt here would benchmark a prompt this
    product does not use, and read as evidence about ACP. The env override is how ai.py already
    selects its model, so nothing is monkeypatched.
    """
    sys.path.insert(0, str(ROOT / "api"))
    os.environ["OLLAMA_MODEL"] = model
    import importlib

    import ai
    importlib.reload(ai)          # re-read OLLAMA_MODEL and drop the /api/tags probe cache

    t0 = time.time()
    try:
        out = ai.suggest_fix(rule_id, rule_name, level, "benchmark.docx", detail=detail)
    except Exception as e:        # noqa: BLE001 — a model that errors is a RESULT, not a crash
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}", "secs": time.time() - t0}
    return {"ok": bool(out), "value": (out or {}).get("value") or (out or {}).get("alt"),
            "raw": out, "secs": round(time.time() - t0, 1)}


def run_vision(model: str, image: Path) -> dict:
    sys.path.insert(0, str(ROOT / "api"))
    os.environ["OLLAMA_VISION_MODEL"] = model
    import importlib

    import ai
    importlib.reload(ai)

    t0 = time.time()
    try:
        out = ai.describe_image(image.read_bytes(), filename=image.name)
    except Exception as e:        # noqa: BLE001
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}", "secs": time.time() - t0}
    return {"ok": bool(out), "value": (out or {}).get("alt"), "secs": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="*", default=[], help="model tags to compare")
    ap.add_argument("--ladder", choices=[*LADDER, "all"],
                    help="compare a predefined ladder instead of naming models (see LADDER)")
    ap.add_argument("--pull", action="store_true",
                    help="pull the rungs that are missing, after printing what that will cost")
    ap.add_argument("--image", type=Path, help="an image for the 1.1.1 vision comparison")
    ap.add_argument("--vision-only", action="store_true")
    ap.add_argument("--list", action="store_true", help="show the models the server has")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.ladder:
        rungs = [r for k, v in LADDER.items() if args.ladder in (k, "all") for r in v]
        # Ladder rungs go FIRST and duplicates are dropped, so the printed comparison reads
        # smallest-to-largest — the order the curve has to be read in to mean anything.
        args.models = list(dict.fromkeys([m for m, _, _ in rungs] + args.models))

    have = installed()

    if args.ladder and args.pull:
        wanted = [(m, size, note) for m, size, note in
                  [r for k, v in LADDER.items() if args.ladder in (k, "all") for r in v]
                  if _norm(m) not in have]
        if wanted:
            # Print the bill before spending it. The module's rule is that a benchmark must never
            # download 20GB because of a typo; --pull is the explicit opt-out of that, so it stays
            # explicit — the cost is stated, and a bad tag fails here by name rather than being
            # quietly skipped later.
            print(f"Pulling {len(wanted)} missing rung(s) to {BASE}:", file=sys.stderr)
            for m, size, note in wanted:
                print(f"  {m:18} {size:>8}  {note}", file=sys.stderr)
            for m, _, _ in wanted:
                print(f"pulling {m}…", file=sys.stderr, flush=True)
                try:
                    req = urllib.request.Request(
                        f"{BASE}/api/pull",
                        data=json.dumps({"model": m, "stream": False}).encode(),
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=3600) as r:
                        body = json.loads(r.read() or b"{}")
                    if body.get("error"):
                        print(f"  FAILED {m}: {body['error']}", file=sys.stderr)
                except (urllib.error.URLError, OSError, ValueError) as e:
                    print(f"  FAILED {m}: {e.__class__.__name__}: {e}", file=sys.stderr)
            have = installed()

    if args.list or not args.models:
        print(f"Ollama at {BASE} has {len(have)} model(s):")
        for m in have:
            print(f"  {m}")
        if not args.models:
            print("\nPass --models to compare, e.g.:\n"
                  "  python scripts/bench_models.py --models llama3.1:8b qwen3:14b")
        return 0

    # Report and skip, never pull. See the module docstring.
    missing = [m for m in args.models if _norm(m) not in have]
    for m in missing:
        print(f"skip {m} — not pulled. `{_pull_hint(m)}`", file=sys.stderr)
    models = [m for m in args.models if _norm(m) in have]
    if not models:
        return 1

    results: dict = {}
    for model in models:
        results[model] = {}
        if not args.vision_only:
            for rule_id, name, level, detail in CASES:
                results[model][rule_id] = run_case(model, rule_id, name, level, detail)
        if args.image:
            results[model]["1.1.1"] = run_vision(model, args.image)

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    for rule_id in ["1.1.1"] + [c[0] for c in CASES]:
        if not any(rule_id in r for r in results.values()):
            continue
        label = next((f"{c[0]} {c[1]}" for c in CASES if c[0] == rule_id), "1.1.1 Non-text Content")
        print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
        for model, per_rule in results.items():
            r = per_rule.get(rule_id)
            if not r:
                continue
            if not r["ok"]:
                print(f"  {model:24} — no draft ({r.get('error', 'model returned nothing')})")
                continue
            print(f"  {model:24} {r['secs']:>5}s  {r['value']}")
    print("\nNo scores, by design — there is no ground truth for these, and a number nobody can\n"
          "defend is worse than none. Read the drafts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
