#!/usr/bin/env python3
"""Fail closed when an analysis engine is missing, so a partial suite cannot report as a pass.

WHY THIS IS A SCRIPT AND NOT A SHELL LADDER IN YAML. `scripts/install_tesseract.sh` was pulled
out of ci.yml for exactly this reason: azure-pipelines.yml needs the same treatment, and a
condition buried in YAML cannot be tested. Two pipelines running one suite need the same gates,
or the suite means different things in each — which has already happened twice in this repo (see
below), both times in the direction where the less-watched pipeline carried the weaker gate.

WHAT "FAIL CLOSED" BUYS. Every engine here gates real criteria, and every one of them degrades
SILENTLY when absent: the tests that need it self-skip, the suite goes green, and the green tick
sits over coverage that never ran. That is the failure this exists to stop — not a broken engine,
which is loud, but a missing one, which is not.

  office   the .NET AcpScan.Cli — the partner analysers behind most OOXML detection
  pdf      engine/pdf-analyser — `analysers` backs assessment, `remediation` backs the fixers
  ocr      tesseract — gates 1.4.5 and 1.4.9, and grounds inline 1.1.1 alt text

THE AVAILABILITY CHECK IS NOT REIMPLEMENTED HERE. `office` and `pdf` are read straight from
`tests/engines.py`, the same module whose OFFICE_OK / PDF_OK decide whether those tests skip. A
guard that recomputed the condition could pass while the tests it is guarding still skipped —
which is the precise shape of a check that cannot fail. `ocr` asks `api/ocr.is_available()`, the
same function the runtime asks, rather than whether an apt step exited 0: those are different
questions, and the one worth gating on is "can we actually OCR".

TWO STALE-GUARD BUGS THIS FILE IS THE ANSWER TO, both of which read as settled fact until checked:

  * ci.yml's header still described the PDF engine as "NOT vendored ... loaded at runtime from
    ACP_PDF_ENGINE. The suites needing it skip with an honest reason." ADR 0029 vendored it.
    `engine/pdf-analyser` is in the tree and PDF_OK resolves True. The comment told a reader that
    skipping was expected, so nobody looked — and there was no guard to notice either way.
    `tests/engines.py` documents having been bitten by the same stale claim once already, when
    PDF_OK defaulted to a path outside the repo and ten tests skipped saying the engine "is not
    vendored in this repo" — true when written, false since ADR 0029.

  * azure-pipelines.yml installs tesseract but has never carried ci.yml's "Fail if OCR coverage
    was lost" step. ci.yml's own header calls step-for-step parity "a live invariant, not a
    description" and records that it "has already drifted once". This is the second drift, and
    the same asymmetry: the pipeline least likely to be watched had the weaker gate.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent

ENGINES = ("office", "pdf", "ocr")


def _office() -> tuple[bool, str]:
    sys.path.insert(0, str(ACP / "tests"))
    import engines
    return engines.OFFICE_OK, engines.NO_OFFICE


def _pdf() -> tuple[bool, str]:
    sys.path.insert(0, str(ACP / "tests"))
    import engines
    return engines.PDF_OK, engines.NO_PDF


def _ocr() -> tuple[bool, str]:
    sys.path.insert(0, str(ACP / "api"))
    import ocr
    return ocr.is_available(), (
        "tesseract (OCR) is unavailable, so 1.4.5 and 1.4.9 were NOT exercised and inline 1.1.1 "
        "alt text could not be grounded. Run scripts/install_tesseract.sh.")


CHECKS = {"office": _office, "pdf": _pdf, "ocr": _ocr}

# What a missing engine costs, in criteria rather than in module names — so the CI log says what
# went unchecked, not merely what failed to load.
COVERAGE = {
    "office": "most OOXML detection (docx/xlsx/pptx) runs through the partner analysers",
    "pdf": "PDF assessment AND every PDF fixer — anything importing `remediation` hard-errors",
    "ocr": "1.4.5 and 1.4.9, plus grounding for inline 1.1.1 alt text",
}


def check(names: list[str]) -> list[tuple[str, str]]:
    """Returns [(engine, why)] for each REQUIRED engine that is unavailable. An engine whose
    probe itself raises counts as unavailable: an import that blows up is not evidence of a
    working engine, and treating the exception as "unknown, carry on" is how a hard dependency
    failure turns back into a silent skip."""
    missing: list[tuple[str, str]] = []
    for name in names:
        try:
            ok, why = CHECKS[name]()
        except Exception as e:                                  # noqa: BLE001 - see docstring
            ok, why = False, f"the {name} availability probe itself failed: {e!r}"
        if not ok:
            missing.append((name, why))
    return missing


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--require", default="office,pdf,ocr",
                   help="comma-separated engines that MUST be available (default: all three)")
    p.add_argument("--report", action="store_true",
                   help="print availability for every engine and exit 0 regardless")
    args = p.parse_args(argv)

    if args.report:
        for name in ENGINES:
            try:
                ok, _ = CHECKS[name]()
            except Exception as e:                              # noqa: BLE001
                print(f"{name:8} ERROR  {e!r}")
                continue
            print(f"{name:8} {'ok' if ok else 'MISSING'}")
        return 0

    names = [n.strip() for n in args.require.split(",") if n.strip()]
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        print(f"check_engines: unknown engine(s) {unknown}; known: {list(CHECKS)}", file=sys.stderr)
        return 2

    missing = check(names)
    if not missing:
        print(f"check_engines: all required engines present ({', '.join(names)})")
        return 0

    for name, why in missing:
        # ::error:: is GitHub Actions' annotation form; Azure Pipelines ignores it harmlessly and
        # the plain text below carries the same information there.
        print(f"::error::{name} engine unavailable. NOT exercised: {COVERAGE[name]}.")
        print(f"  {why}")
    print("\nThe suite above ran WITHOUT the coverage named here — read its result as partial.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
