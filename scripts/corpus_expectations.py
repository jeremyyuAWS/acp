#!/usr/bin/env python3
"""What a test-corpus manifest is ALLOWED to expect, derived from the engine.

`test-corpus/generate.py` already emits a ground-truth manifest and calls itself an oracle. The
piece it has no way to get right by hand is the VOCABULARY: ACP answers four things, not three,
and which of the four are reachable is a property of the (criterion, format) pair.

    PASS           the validator ran and certified conformance
    FAIL           a blocking finding fired
    REVIEW         assessed-for-review — evidence for a human, never a certification
    NOT_EVALUATED  nobody looked (out of target, out of scope, or no lane)

The trap this module exists to close: a REVIEW_FORMATS pair "resolves to REVIEW when its detector
fires and to NOT_EVALUATED when it does not — it NEVER resolves to PASS" (assessment_policy).
2.1.2 on docx/pptx/xlsx is exactly that. A manifest that marks a clean 2.1.2 fixture `pass` is
not describing a bug in ACP; it is describing a bug in the manifest, and it will report a false
failure on every run forever. The same applies to any pair whose lane cannot certify
(NO_CERTIFY_ASSESS_FORMATS) and to registry pairs with partial coverage.

So rather than let a corpus author guess, this answers two questions per pair:

    clean_verdict(sc, fmt)   what the engine says about a file with NOTHING wrong
    possible_verdicts(sc, fmt)  the full set any fixture could legitimately expect

Both mirror `_rule_outcome`'s branches in its order. They are deliberately a SECOND expression of
that logic rather than a call into it: `_rule_outcome` needs finding counts, a scan target and a
resolved scope, and a corpus author has none of those at the point they are writing an
expectation. Where two expressions of one rule exist, tests/test_corpus_expectations.py drives
the real `_rule_outcome` with synthetic counts and asserts the two agree — so the copy cannot
drift silently, which is the only reason a copy is acceptable here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import assessment_policy as pol      # noqa: E402

PASS, FAIL, REVIEW, NOT_EVALUATED = "PASS", "FAIL", pol.REVIEW, pol.NOT_EVALUATED
VERDICTS = frozenset({PASS, FAIL, REVIEW, NOT_EVALUATED})

# Manifest words → engine words. The corpus speaks in lowercase outcomes; the engine speaks in
# these. Kept explicit so a manifest can never smuggle in a fifth concept: "not_applicable" is
# NOT accepted, deliberately — assessment_policy renamed it away because it "asserts the
# criterion is out of scope; the truth is only that we didn't look".
MANIFEST_STATUS = {
    "pass": PASS,
    "fail": FAIL,
    "review": REVIEW,
    "not_evaluated": NOT_EVALUATED,
}


def _registry(sc: str, fmt: str):
    """The capability registration for a pair, or None. Lazy, like assessment_policy's own."""
    return pol._registry_for(sc, fmt)      # noqa: SLF001 — the one accessor that exists


def clean_verdict(sc: str, fmt: str, scope=None, target: str = "AA") -> str:
    """What ACP reports for this pair on a file with NO findings at all.

    This is the number an "accessible" fixture must be written against, and the one most likely
    to be assumed. A clean review-lane pair is NOT_EVALUATED, not PASS. A clean pair whose lane
    cannot certify is REVIEW, not PASS.

    Mirrors _rule_outcome with fail_count=0, review_count=0, in its branch order.
    """
    if not pol.in_target(sc, target):
        return NOT_EVALUATED
    if not pol.in_scope(sc, fmt, scope):
        return NOT_EVALUATED
    if fmt is not None and fmt in pol.REVIEW_FORMATS.get(sc, frozenset()):
        return NOT_EVALUATED                       # no signal fired; never PASS
    reg = _registry(sc, fmt)
    if reg is not None:
        if reg.coverage in pol._CAN_CERTIFY_PASS:  # noqa: SLF001
            return pol._certify(sc, fmt)           # noqa: SLF001 — may still downgrade to REVIEW
        if reg.coverage in pol._NEEDS_REVIEW_ON_CLEAN:  # noqa: SLF001
            return REVIEW
        return NOT_EVALUATED
    if fmt is None or fmt not in pol.RULE_FORMATS.get(sc, pol._ALL_FORMATS):  # noqa: SLF001
        return NOT_EVALUATED
    return pol._certify(sc, fmt)                   # noqa: SLF001


def possible_verdicts(sc: str, fmt: str, scope=None, target: str = "AA") -> frozenset[str]:
    """Every verdict a fixture for this pair could legitimately expect.

    Used to reject a manifest entry before a scan ever runs — an expectation outside this set
    can never be met, so it is a mistake in the corpus, not a finding about ACP.
    """
    if not pol.in_target(sc, target) or not pol.in_scope(sc, fmt, scope):
        return frozenset({NOT_EVALUATED})
    clean = clean_verdict(sc, fmt, scope, target)
    # A blocking finding is a FACT and outranks the format bookkeeping — _rule_outcome hoists it
    # above the registry and RULE_FORMATS branches precisely so a detected failure can never be
    # reclassified as "not checked". So FAIL is reachable for any in-scope, in-target pair.
    out = {clean, FAIL}
    if fmt is not None and fmt in pol.REVIEW_FORMATS.get(sc, frozenset()):
        out.add(REVIEW)                            # its detector firing
    elif _registry(sc, fmt) is not None or fmt in pol.RULE_FORMATS.get(sc, frozenset()):
        out.add(REVIEW)                            # an advisory finding on a pass/fail lane
    return frozenset(out)


def can_ever_pass(sc: str, fmt: str) -> bool:
    """Is PASS reachable at all? False for every review-lane pair and every non-certifying lane.

    The single most useful fact for a corpus author: if this is False, an "accessible" fixture
    for the pair must expect REVIEW or NOT_EVALUATED, and marking it `pass` guarantees a
    permanent false failure.
    """
    return PASS in possible_verdicts(sc, fmt)


def validate(entries: list[dict], scope=None, target: str = "AA") -> list[str]:
    """Problems with a manifest, as human-readable lines. Empty list means it is expressible.

    Checks the expectation is a verdict ACP has, and that it is one this pair can produce.
    Says which, and why, because "invalid expectation" without the reachable set just moves the
    guessing.
    """
    problems: list[str] = []
    for e in entries:
        sc, fmt = e.get("sc"), e.get("format")
        raw = str(e.get("expected", "")).lower()
        where = f"{e.get('file', '?')} {sc} x {fmt}"
        if raw not in MANIFEST_STATUS:
            problems.append(
                f"{where}: expected={raw!r} is not one of {sorted(MANIFEST_STATUS)} "
                "('not_applicable' is deliberately absent — ACP says NOT_EVALUATED, which claims "
                "only that nothing ran)")
            continue
        want = MANIFEST_STATUS[raw]
        allowed = possible_verdicts(sc, fmt, scope, target)
        if want not in allowed:
            extra = ""
            if want == PASS and not can_ever_pass(sc, fmt):
                extra = (" — this pair can never PASS: "
                         + ("it is a review lane (REVIEW_FORMATS), which resolves to REVIEW or "
                            "NOT_EVALUATED and never certifies"
                            if fmt in pol.REVIEW_FORMATS.get(sc, frozenset())
                            else "its assessment lane cannot certify (NO_CERTIFY_ASSESS_FORMATS)"))
            problems.append(
                f"{where}: expects {want}, but the engine can only answer "
                f"{sorted(allowed)}{extra}")
    return problems


def _table(scope=None) -> list[dict]:
    """Every scopeable pair with its clean verdict — the sheet a corpus author works from."""
    rows = []
    for sc, fmts in sorted(pol.SCOPE_PRESETS["acp-core-17"].items(),
                           key=lambda kv: [int(n) for n in kv[0].split(".")]):
        for fmt in sorted(fmts):
            rows.append({"sc": sc, "format": fmt,
                         "clean": clean_verdict(sc, fmt, scope),
                         "possible": sorted(possible_verdicts(sc, fmt, scope)),
                         "can_pass": can_ever_pass(sc, fmt)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit the table as JSON")
    ap.add_argument("--validate", metavar="MANIFEST",
                    help="check a manifest's expectations are reachable; exit 1 if not")
    args = ap.parse_args()

    if args.validate:
        entries = json.loads(Path(args.validate).read_text())
        problems = validate(entries if isinstance(entries, list) else entries.get("documents", []))
        for p in problems:
            print(p, file=sys.stderr)
        print(f"{len(problems)} unreachable expectation(s)", file=sys.stderr)
        return 1 if problems else 0

    rows = _table()
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0

    print(f"{'SC':<8} {'fmt':<6} {'clean scan':<14} can pass?  possible")
    for r in rows:
        print(f"{r['sc']:<8} {r['format']:<6} {r['clean']:<14} "
              f"{'yes' if r['can_pass'] else 'NO ':<10} {','.join(r['possible'])}")
    cannot = [r for r in rows if not r["can_pass"]]
    print(f"\n{len(rows)} pairs · {len(cannot)} can never PASS "
          "(an 'accessible' fixture for those must expect REVIEW or NOT_EVALUATED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
