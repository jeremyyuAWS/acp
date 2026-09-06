#!/usr/bin/env python3
"""Run a mutation campaign against ACP's detector modules, and report only the findings.

P5.4. ON DEMAND ONLY — this is never run in CI, and the reason is the same one that kept the
LibreOffice round-trip out (P5.3): a campaign takes tens of minutes, and spending that on every PR
is a budget decision rather than something to slip in with a script. Run it when you have changed
a detector, or periodically to see whether the suite has drifted.

    python scripts/mutation_test.py            # run a campaign, then summarise
    python scripts/mutation_test.py --report   # summarise the last campaign, no re-run

WHAT MUTATION TESTING ANSWERS THAT COVERAGE DOES NOT. Coverage says a line was executed. It says
nothing about whether any assertion would have noticed the line being WRONG. mutmut changes the
code in small ways — a comparison flipped, a constant altered, a return replaced — and re-runs the
tests. A mutant the suite still passes is a change to the detector that no test objects to.

    F1 1.00 bounds only the fixtures we thought to write.   — docs/BACKLOG.md, P5.4

THE THREE OUTCOMES ARE NOT THREE GRADES, and conflating them is how a campaign gets misread:

  * KILLED     — a test failed. The suite noticed. Good.
  * SURVIVED   — tests ran and all passed. THIS IS THE FINDING: the detector can be changed here
                 without any test objecting.
  * NO TESTS   — no test in the selection exercises this line at all. NOT a weak assertion; a
                 gap in what was selected to run, or code the selection legitimately does not
                 cover. Reported separately and never mixed into the score, because counting it
                 as a survivor makes an unrelated module's code look like a hole in this one's
                 tests.

That distinction is why this script exists rather than `mutmut results` alone: the raw list mixes
them, and on a module spanning docx, pptx and xlsx the no-tests entries drown the real findings.

READ THE SCORE AS A FLOOR, NOT A GRADE. Some survivors are equivalent mutants — changes that
cannot alter observable behaviour, so no test could kill them. There is no way to detect those
automatically, so a campaign never legitimately reaches 100%, and chasing it wastes effort on
mutants that are not defects. The useful output is the LIST, read one entry at a time.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent

MISSING = """mutmut is not installed.

    pip install mutmut

It is deliberately absent from api/requirements.txt and tests/requirements.txt: nothing ACP ships
imports it, and nothing in CI runs it (see this script's docstring). Installing it is a local,
on-demand step."""

#: `mutmut results` lines look like `    api.office_structure.x_fn__mutmut_3: survived`.
RESULT = re.compile(r"^\s*(?P<mutant>[\w.]+):\s*(?P<status>.+?)\s*$")

#: The statuses that are findings. `mutmut results` only ever emits these two — see below.
FINDING = {"survived"}

#: WHERE THE COUNTS COME FROM, and why not from `mutmut results`.
#:
#: `results` lists ONLY survivors and no-tests, by design: it is the "what needs attention" view,
#: and killed mutants are omitted because there is nothing to do about them. An earlier version of
#: this script counted statuses from that output and duly reported `killed 0` for a campaign that
#: had killed 513 — a made-up number, produced with total confidence, from a command that was
#: never claiming to report it.
#:
#: `mutmut export-cicd-stats` writes the real tallies as JSON. That file is the source for every
#: count printed here; `results` is used only for the survivor NAMES.
STATS_JSON = Path("mutants/mutmut-cicd-stats.json")


def _require_mutmut() -> None:
    if shutil.which("mutmut") is None:
        sys.exit(MISSING)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run a mutmut subcommand from the repository root, streaming nothing, capturing all.

    cwd is pinned to ACP rather than inherited: mutmut reads `setup.cfg` from the working
    directory and writes `mutants/` beside it, so running this script from elsewhere would
    silently mutate nothing and report a clean campaign.
    """
    return subprocess.run(["mutmut", *args], cwd=ACP, capture_output=True, text=True)


def parse_results(text: str) -> dict[str, list[str]]:
    """`mutmut results` output → {status: [mutant, ...]}.

    Tolerant of section headers and blank lines, and deliberately NOT tolerant of an unknown
    status: those land under their own key and are printed, because the alternative is a finding
    silently reclassified as a pass.
    """
    by_status: dict[str, list[str]] = defaultdict(list)
    for line in text.splitlines():
        match = RESULT.match(line)
        if not match:
            continue
        status = match.group("status").strip().lower()
        # A results line always names a dotted mutant; a header like "survived:" does not.
        mutant = match.group("mutant")
        if "." not in mutant:
            continue
        by_status[status].append(mutant)
    return dict(by_status)


def function_of(mutant: str) -> str:
    """`api.office_structure.x_docx_checks__mutmut_12` → `docx_checks`.

    Grouping by function is what makes a 400-entry list readable: forty survivors in one function
    is one conversation about one detector, not forty separate ones.
    """
    tail = mutant.rsplit(".", 1)[-1]
    tail = re.sub(r"__mutmut_\d+$", "", tail)
    return tail[2:] if tail.startswith("x_") else tail


def load_stats() -> dict:
    """The authoritative tallies, refreshed from mutmut rather than inferred from `results`."""
    _run(["export-cicd-stats"])
    path = ACP / STATS_JSON
    if not path.exists():
        sys.exit(f"{STATS_JSON} was not written — run a campaign first "
                 f"(python scripts/mutation_test.py).")
    import json
    return json.loads(path.read_text())


def report(by_status: dict[str, list[str]], stats: dict) -> int:
    survived_names = sorted({m for s in FINDING for m in by_status.get(s, [])})
    killed = int(stats.get("killed", 0))
    survived = int(stats.get("survived", 0))
    no_tests = int(stats.get("no_tests", 0))
    total = int(stats.get("total", 0))
    other = {k: int(v) for k, v in stats.items()
             if k not in {"killed", "survived", "no_tests", "total"} and int(v or 0)}

    tested = killed + survived
    print("Mutation campaign")
    print(f"  killed    {killed:>5}   a test failed — the suite noticed")
    print(f"  SURVIVED  {survived:>5}   tests ran and passed — these are the findings")
    print(f"  no tests  {no_tests:>5}   nothing in the selection exercises this line")
    for status, count in sorted(other.items()):
        print(f"  {status:<9} {count:>5}   (read these yourself — not counted in the score)")
    print(f"  total     {total:>5}")

    # The names come from `results`, the counts from the stats JSON. If they disagree the report
    # is describing two different campaigns, so say so rather than printing a confident mixture.
    if survived and len(survived_names) != survived:
        print(f"\n  WARNING: `mutmut results` listed {len(survived_names)} survivors but the stats "
              f"say {survived}.\n  The two came from different runs; re-run the campaign.")

    if tested:
        # Scored over mutants the tests ACTUALLY RAN against. Including no-tests in the
        # denominator would let an unrelated part of the module drag the number down and make a
        # strong docx suite look weak.
        print(f"\n  score {killed / tested:.1%} of {tested} mutants the selected tests reached")
        print("  (a floor, not a grade — some survivors are equivalent mutants no test can kill)")
    else:
        print("\n  No mutant was reached by any selected test. The score is not 0% — it is "
              "undefined,\n  and the test selection in setup.cfg is what to look at.")

    if survived_names:
        print(f"\nSurvivors by function — each is a change no test objects to:\n")
        grouped: dict[str, list[str]] = defaultdict(list)
        for mutant in survived_names:
            grouped[function_of(mutant)].append(mutant)
        for func, mutants in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            print(f"  {len(mutants):>4}  {func}")
        print("\n  Inspect one with:  mutmut show <mutant-name>")
        print(f"  e.g.               mutmut show {survived_names[0]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true",
                        help="summarise the last campaign without re-running it")
    args = parser.parse_args()

    _require_mutmut()

    if not args.report:
        print("Running the campaign. This takes tens of minutes; --report re-reads it later.\n",
              file=sys.stderr)
        run = _run(["run"])
        # mutmut exits non-zero when mutants survive, which is its normal reporting outcome and
        # NOT an error. A real failure shows up as an empty/unparseable results list below, so the
        # exit code is deliberately not treated as the signal.
        if run.returncode not in (0, 1, 2):
            sys.stderr.write(run.stdout[-4000:] + run.stderr[-4000:])
            return run.returncode

    results = _run(["results"])
    by_status = parse_results(results.stdout)
    stats = load_stats()
    if not by_status and not stats.get("total"):
        sys.stderr.write(results.stdout[-2000:] + results.stderr[-2000:])
        sys.exit("mutmut reported no results at all. Run a campaign first, and check that the "
                 "module alias is loading — see mutmut_module_alias.py.")
    return report(by_status, stats)


if __name__ == "__main__":
    raise SystemExit(main())
