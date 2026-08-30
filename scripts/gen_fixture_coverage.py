#!/usr/bin/env python3
"""Which (criterion, format) pairs have a labelled ground-truth fixture, and which do not.

WHAT THIS ANSWERS. The Phase-1 acceptance criterion is "all applicable pairs have explicit
fixture coverage or a documented human-only rationale". Nothing computed that, so the size of the
remaining fixture job was unknown — and an unknown denominator is how "we have a corpus" turns
into a claim nobody can check. This prints the number and names the gaps.

A PAIR IS COVERED WHEN A FIXTURE DECLARES AN EXPECTATION FOR IT, not when a fixture merely
exists in that format. `gen_sc_corpus.py` writes single-criterion .docx fixtures whose `expect`
dict names the criterion and the verdict; a fixture that happens to be a .docx says nothing about
1.4.3 unless it declares something about 1.4.3. Counting files rather than declarations is the
easy way to report coverage that is not there.

WHY THE NUMBER IS LOW AND THAT IS THE POINT. Only .docx has a per-criterion generator today. The
other three formats have no labelled corpus at all — `gen_complex_corpus.py` is also .docx, and
`complex_corpus.py`'s expectations are a floor ("at least these SCs"), not a per-pair verdict.
Reporting 24% honestly is worth more than a percentage assembled from whatever happened to be
countable.

THE GUARD IS A RATCHET, NOT A THRESHOLD. `--check` fails when coverage DROPS below the recorded
baseline, not when it falls short of 100%. A guard demanding full coverage today would be red on
every commit, and a red that is always red stops being read — this repo has the receipts on that
(docs/TODO.md's generated block went 387 commits stale because nothing checked it, and read as
current the whole time). A ratchet is the version that can actually be merged and still refuses
to let a fixture quietly disappear.

Run:
    python scripts/gen_fixture_coverage.py            # the table
    python scripts/gen_fixture_coverage.py --json     # machine-readable
    python scripts/gen_fixture_coverage.py --check    # CI: fail if coverage regressed
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import corpus_expectations as ce  # noqa: E402

FORMATS = ("docx", "xlsx", "pptx", "pdf")

# The applicability model. `acp-core-17` is a SHIPPED scope preset, not a filter invented here —
# 17 criteria, 62 pairs — and it is the model the PRD's own capability counts reproduce. The
# wider registry carries more (currently 22 criteria), so which denominator is right is a
# product decision, not this script's; it reports the preset and says so.
PRESET = "acp-core-17"

# Coverage floor, by format. Update ONLY upward, and only alongside the fixtures that earned it.
# Written down rather than computed so a drop is a diff someone has to justify in review.
BASELINE = {"docx": 15, "xlsx": 0, "pptx": 0, "pdf": 0}


def applicable_pairs() -> dict[str, list[str]]:
    """{format: [criteria]} for the preset — the denominator."""
    preset = ce.pol.SCOPE_PRESETS[PRESET]
    out: dict[str, list[str]] = {f: [] for f in FORMATS}
    for sc, fmts in preset.items():
        for f in fmts:
            if f in out:
                out[f].append(sc)
    return {f: sorted(scs) for f, scs in out.items()}


def _docx_declared() -> set[str]:
    """Criteria the .docx corpus actually declares an expectation for.

    Builds the fixtures into a temp dir, exactly as tests/test_docx_corpus_regression_gate.py
    does, because the expectations are RETURNED by each fixture's build function rather than
    sitting in a table that could be read statically. Generated, not committed — a generated
    corpus cannot drift from the generator that documents what each fixture is for.
    """
    import gen_sc_corpus
    declared: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="acp-fixcov-") as d:
        docs = Path(d) / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        for name, build, post, _kind in gen_sc_corpus.FIXTURES:
            doc = gen_sc_corpus._doc()
            expectations, _note = build(doc)
            path = docs / f"{name}.docx"
            doc.save(path)
            if post:
                post(path)
            declared.update(expectations or {})
    return declared


# One entry per format. A format with no generator is absent here rather than mapped to a stub
# that returns an empty set: "nobody has written one" and "the generator found nothing" are
# different states, and the report distinguishes them.
GENERATORS = {"docx": _docx_declared}


def coverage() -> dict:
    pairs = applicable_pairs()
    out = {}
    for fmt in FORMATS:
        applicable = pairs[fmt]
        gen = GENERATORS.get(fmt)
        declared = gen() if gen else None
        covered = sorted(sc for sc in applicable if declared and sc in declared) if declared else []
        out[fmt] = {
            "applicable": applicable,
            "covered": covered,
            "missing": sorted(set(applicable) - set(covered)),
            "has_generator": gen is not None,
            # A criterion the corpus declares that the preset does not consider applicable to
            # this format. Not an error — a fixture may legitimately exercise more — but worth
            # surfacing, because it usually means the preset and the corpus disagree about scope.
            "declared_outside_preset": (sorted(set(declared) - set(applicable)) if declared else []),
        }
    return out


def _report(cov: dict) -> None:
    total_app = sum(len(v["applicable"]) for v in cov.values())
    total_cov = sum(len(v["covered"]) for v in cov.values())
    print(f"Ground-truth fixture coverage — scope preset {PRESET!r}")
    print(f"{total_cov} of {total_app} applicable (criterion, format) pairs "
          f"have a labelled fixture ({100 * total_cov / total_app:.0f}%)\n")
    print(f"  {'format':8}{'covered':>9}{'applicable':>12}   status")
    for fmt in FORMATS:
        v = cov[fmt]
        status = ("no labelled corpus exists for this format" if not v["has_generator"]
                  else "complete" if not v["missing"] else f"missing {len(v['missing'])}")
        print(f"  {fmt:8}{len(v['covered']):>9}{len(v['applicable']):>12}   {status}")

    for fmt in FORMATS:
        v = cov[fmt]
        if v["missing"]:
            print(f"\n  {fmt} — no fixture declares an expectation for:")
            print(f"    {', '.join(v['missing'])}")
        if v["declared_outside_preset"]:
            print(f"  {fmt} — corpus declares criteria the preset excludes: "
                  f"{', '.join(v['declared_outside_preset'])}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="emit the coverage map as JSON")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if coverage dropped below the recorded baseline")
    args = ap.parse_args(argv)

    cov = coverage()
    if args.json:
        print(json.dumps(cov, indent=2, sort_keys=True))
        return 0

    if args.check:
        regressed = []
        for fmt in FORMATS:
            got, floor = len(cov[fmt]["covered"]), BASELINE.get(fmt, 0)
            if got < floor:
                regressed.append(
                    f"{fmt}: {got} covered, baseline is {floor} — "
                    f"lost {', '.join(sorted(set(cov[fmt]['applicable']) - set(cov[fmt]['covered'])))}")
        if regressed:
            print("fixture coverage regressed:", file=sys.stderr)
            for r in regressed:
                print(f"  {r}", file=sys.stderr)
            print("\nA pair that had a labelled fixture no longer does. Either restore it, or "
                  "lower\nthe BASELINE in this file deliberately, in the same commit, with a "
                  "reason.", file=sys.stderr)
            return 1
        total = sum(len(v["covered"]) for v in cov.values())
        print(f"gen_fixture_coverage: {total} pairs covered, no regression against the baseline")
        return 0

    _report(cov)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
