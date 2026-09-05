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

WHY THE NUMBER IS WHAT IT IS. Every format now has a per-criterion generator, and only .docx is
complete: xlsx declares 10 of 15, pptx 9 of 17, pdf 10 of 15. The shortfalls are not neglect — a
pair is declared only where a detector was actually driven against the fixture and confirmed to
fire, so criteria needing OCR, or tag-tree semantics nothing reads yet, stay uncounted until
something can check them. Reporting 71% honestly is worth more than a percentage assembled from
whatever happened to be countable; that was true at 24%, when .docx was the only corpus, and it
is the reason the number moved by fixtures rather than by redefinition.

"Confirmed to fire" is deliberately not "first-party": pdf 2.4.2 and 3.1.1 live in the vendored
analyser (ADR 0029) rather than in api/, and are as reachable as anything in api/formats/.
Phrasing the rule by directory instead of by availability cost that corpus two pairs for one
commit, and they were two of the ten pairs that can CERTIFY.

WHERE the confirmation happens is a real distinction, and the report keeps it. Most pairs are
confirmed wherever the suite runs. A few — xlsx 2.4.2 and 3.1.1 today — have no first-party
detector on any Office format and are proven by the .NET analyser, so their label holds in CI
and not on a bare checkout. `engine_only` names them per format and the header counts them,
because folding them in would make one column mean two things; leaving them out entirely would
mean a certifying pair stayed verified by nothing, which is strictly worse.

Not counted here, deliberately: `gen_complex_corpus.py` is also .docx, and `complex_corpus.py`'s
expectations are a floor ("at least these SCs"), not a per-pair verdict.

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
# 17 criteria, 62 pairs — and it is the model the PRD's own capability counts reproduce.
#
# WHICH DENOMINATOR TO REPORT WAS AN OPEN PRODUCT QUESTION AND IS NOW SETTLED: the preset, 62
# pairs, including for figures quoted outside the team (owner's decision, 2026-08-30). The wider
# rules registry carries 22 criteria and 71 pairs — the extra nine being 1.3.5 docx/pdf, 1.4.4
# pptx, 1.4.10 docx/pptx, 1.4.12 docx/pdf/pptx and 2.5.3 pdf — and the same body of work scores
# noticeably lower against it. Both are defensible; the point of writing the choice down is that
# only one of them should ever reach a customer, and a number that silently switches denominator
# between two documents is worse than either.
#
# So this is now a recorded decision rather than a deferral, and changing it is an edit somebody
# makes on purpose. If the preset itself gains or loses criteria the number moves with it, which
# is the intended behaviour — tests/test_fixture_coverage.py asserts the pair count so that a
# change to the scope cannot quietly restate coverage.
PRESET = "acp-core-17"

# Coverage floor, by format. Update ONLY upward, and only alongside the fixtures that earned it.
# Written down rather than computed so a drop is a diff someone has to justify in review.
BASELINE = {"docx": 15, "xlsx": 13, "pptx": 14, "pdf": 14}


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


def _xlsx_declared() -> set[str]:
    """Criteria the .xlsx corpus declares an expectation for.

    Cheaper than the .docx path: `gen_xlsx_corpus` keeps its declared set in a constant, because
    its fixtures were built after the .docx ones and could be written to expose it. The constant
    is held honest against the fixtures themselves by tests/test_xlsx_corpus.py, so reading it
    here is not taking a claim on trust.
    """
    import gen_xlsx_corpus
    return set(gen_xlsx_corpus.DECLARED)


def _engine_declared(fmt: str) -> set[str]:
    """Criteria a corpus declares that are confirmed ONLY where the .NET Office analyser is
    built — CI, not a bare container.

    Held apart from `_*_declared` on purpose. The corpora's rule is "a detector was driven
    against this fixture and confirmed to fire"; for these the confirmation happens in CI
    instead of everywhere, which is a weaker guarantee and would silently make one column mean
    two things if the two sets were merged. They are counted in the total — a pair verified in
    CI is enormously better than a certifying pair verified nowhere, which is what these were —
    and the report names the split so nobody has to infer it.
    """
    gen = GENERATORS.get(fmt)
    if gen is None:
        return set()
    mod = {"xlsx": "gen_xlsx_corpus", "pptx": "gen_pptx_corpus",
           "pdf": "gen_pdf_corpus", "docx": "gen_sc_corpus"}[fmt]
    import importlib
    return set(getattr(importlib.import_module(mod), "DECLARED_ENGINE", ()))


def _pptx_declared() -> set[str]:
    """Criteria the .pptx corpus declares. Same constant-plus-test shape as xlsx: the set is held
    honest against the fixtures themselves by tests/test_pptx_corpus.py."""
    import gen_pptx_corpus
    return set(gen_pptx_corpus.DECLARED)


def _pdf_declared() -> set[str]:
    """Criteria the .pdf corpus declares. Same constant-plus-test shape as xlsx and pptx, held
    honest against the fixtures by tests/test_pdf_corpus.py — which, unlike the Office ones, can
    drive real detection anywhere the suite runs, because the PDF analyser is vendored in-tree
    (ADR 0029) rather than needing the .NET engine."""
    import gen_pdf_corpus
    return set(gen_pdf_corpus.DECLARED)


# One entry per format. A format with no generator was absent here rather than mapped to a stub
# returning an empty set: "nobody has written one" and "the generator found nothing" are
# different states, and the report distinguished them. Every format now has one — the
# distinction is kept because it is what `has_generator` reports, and a format could lose its
# corpus the same way it gained one.
GENERATORS = {"docx": _docx_declared, "xlsx": _xlsx_declared, "pptx": _pptx_declared,
              "pdf": _pdf_declared}


def coverage() -> dict:
    pairs = applicable_pairs()
    out = {}
    for fmt in FORMATS:
        applicable = pairs[fmt]
        gen = GENERATORS.get(fmt)
        base = gen() if gen else None
        engine_only = _engine_declared(fmt) if gen else set()
        declared = (base | engine_only) if base is not None else None
        covered = sorted(sc for sc in applicable if declared and sc in declared) if declared else []
        out[fmt] = {
            "applicable": applicable,
            "covered": covered,
            "missing": sorted(set(applicable) - set(covered)),
            "has_generator": gen is not None,
            # Of `covered`, the pairs whose label is confirmed only where the .NET Office
            # analyser is built. Reported rather than merged so the headline number keeps
            # meaning "confirmed wherever the suite runs" for everything outside this list.
            "engine_only": sorted(sc for sc in covered if sc in engine_only),
            # A criterion the corpus declares that the preset does not consider applicable to
            # this format. Not an error — a fixture may legitimately exercise more — but worth
            # surfacing, because it usually means the preset and the corpus disagree about scope.
            "declared_outside_preset": (sorted(set(declared) - set(applicable)) if declared else []),
        }
    return out


def _report(cov: dict) -> None:
    total_app = sum(len(v["applicable"]) for v in cov.values())
    total_cov = sum(len(v["covered"]) for v in cov.values())
    total_eng = sum(len(v["engine_only"]) for v in cov.values())
    print(f"Ground-truth fixture coverage — scope preset {PRESET!r}")
    print(f"{total_cov} of {total_app} applicable (criterion, format) pairs "
          f"have a labelled fixture ({100 * total_cov / total_app:.0f}%)")
    if total_eng:
        print(f"  of those, {total_eng} are confirmed only where the .NET Office analyser is "
              f"built (CI), not on a bare checkout")
    print()
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
        if v["engine_only"]:
            print(f"  {fmt} — confirmed only with the .NET analyser built: "
                  f"{', '.join(v['engine_only'])}")
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
