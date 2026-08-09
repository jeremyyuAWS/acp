#!/usr/bin/env python3
"""Assessment scorecard for the labelled .docx corpus — recall, precision, and the two rates
that decide whether an AI-assessed lane is defensible.

READS THE CERTIFIED VERDICT, NOT THE RUBRIC RESULT, AND THE DIFFERENCE IS NOT COSMETIC.
`analyse_and_assess` returns a `per_criterion` list whose `result` is the RUBRIC's answer, before
policy. On a document with no images it reports `1.1.1: pass` — and 1.1.1 on .docx is a
review-lane pair that policy forbids from ever certifying (ADR 0016). A scorer that read that
field would credit ACP with 32 passes it does not claim, and would report a false-PASS rate of
zero by construction. So this recomputes the outcome the way `store` does: split the findings
into blocking and advisory (assessment_policy._split_sc_counts), then run the one gate,
`_rule_outcome`. Same function, same order, no second expression of the rule.

THE FOUR-WAY VOCABULARY COLLAPSES TO THREE THINGS WORTH SCORING:

    FAIL                     asserted a violation
    PASS                     certified conformance
    REVIEW / NOT_EVALUATED   asserted neither — an abstention

Treating REVIEW as a miss would score correct behaviour as failure: on eight of the fifteen
.docx pairs REVIEW is the BEST available answer, because the lane cannot certify. Treating it as
a pass would be worse. It is counted as its own outcome throughout.

WHY THERE IS NO SINGLE MACRO-F1 HERE. A confusion matrix needs a true-negative class, and only
1.3.1, 1.4.3, 2.4.2 and 3.1.1 have one on .docx. Reporting one macro-F1 over all fifteen would
average four real cells with eleven undefined ones and produce a number that moves when the
corpus mix changes rather than when the product does. The two lanes are reported separately, and
the per-SC table says which is which.

FALSE PASS IS THE HEADLINE, and it is deliberately not folded into F1. A missed violation that
resolves to REVIEW costs a human five minutes. A missed violation that resolves to PASS is a
conformance claim on an inaccessible document — it feeds a VPAT, and it is the specific outcome
ADR 0016 exists to prevent. An F1 score averages those two together; this does not.

ATTRIBUTION IS SCORED SEPARATELY FROM DETECTION. A fixture that seeds a heading-level skip and
gets a finding under 2.4.6 instead of 1.3.1 was DETECTED and MISLABELLED, which is a different
defect with a different fix than not noticing at all.

Run:
    python scripts/score_assessment.py --corpus ~/Downloads/acp-docx-eval/sc-corpus
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import assessment_policy as pol  # noqa: E402
import corpus_expectations as ce  # noqa: E402

FMT = "docx"
PASS, FAIL, REVIEW, NOT_EVAL = ce.PASS, ce.FAIL, ce.REVIEW, ce.NOT_EVALUATED
ABSTAIN = (REVIEW, NOT_EVAL)


def scan(path: Path) -> tuple[list[dict], float]:
    """Findings from the shipped scan path, plus wall-clock seconds."""
    import scanner
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(path, tmp / path.name)
    t0 = time.time()
    try:
        res, _ = scanner.analyse_and_assess(tmp, path.name)
    except Exception as e:                                            # noqa: BLE001
        print(f"    scan failed: {e.__class__.__name__}: {e}", file=sys.stderr)
        return [], 0.0
    return list((res or {}).get("issues") or []), time.time() - t0


def verdicts(issues: list[dict], scs: list[str]) -> dict[str, str]:
    """The CERTIFIED outcome per criterion — `store`'s computation, not the rubric's."""
    fail_counts, review_counts = pol._split_sc_counts(issues)
    return {sc: pol._rule_outcome(sc, FMT, fail_counts.get(sc, 0), review_counts.get(sc, 0),
                                  "AA", None)
            for sc in scs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path,
                    default=Path.home() / "Downloads" / "acp-docx-eval" / "sc-corpus")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    man = json.loads((args.corpus / "manifest.json").read_text())
    scs = sorted(man["lanes"])
    can_pass = {sc for sc in scs if man["lanes"][sc]["can_pass"]}

    # per-SC tallies. `abstain_on_fail` is kept apart from `fn` because they are different
    # products: one handed the case to a human, the other said nothing.
    tally = {sc: dict(tp=0, fp=0, fn_pass=0, abstain_on_fail=0, tn=0, pass_missed=0, n=0)
             for sc in scs}
    attribution: list[tuple[str, str, list[str]]] = []
    latencies: list[float] = []
    rows = []

    for fx in man["fixtures"]:
        path = args.corpus / fx["file"]
        issues, secs = scan(path)
        latencies.append(secs)
        got = verdicts(issues, scs)
        expect = fx["expect"]

        # Anything the fixture does not speak to is expected to behave as a clean document
        # would on that pair — which is how a false positive on an untouched criterion is
        # caught. `clean_verdict` supplies that per pair rather than assuming "PASS".
        full = {sc: expect.get(sc, ce.clean_verdict(sc, FMT)) for sc in scs}

        wrong = []
        for sc in scs:
            e, g = full[sc], got[sc]
            t = tally[sc]
            t["n"] += 1
            if e == FAIL:
                if g == FAIL:
                    t["tp"] += 1
                elif g == PASS:
                    t["fn_pass"] += 1            # the dangerous one
                    wrong.append(f"{sc}: FAIL->PASS")
                else:
                    t["abstain_on_fail"] += 1
                    wrong.append(f"{sc}: FAIL->{g}")
            elif e == PASS:
                if g == PASS:
                    t["tn"] += 1
                elif g == FAIL:
                    t["fp"] += 1
                    wrong.append(f"{sc}: PASS->FAIL")
                else:
                    t["pass_missed"] += 1
                    wrong.append(f"{sc}: PASS->{g}")
            else:                                 # expected REVIEW / NOT_EVALUATED
                if g == FAIL:
                    t["fp"] += 1
                    wrong.append(f"{sc}: {e}->FAIL")

        # Attribution: the fixture seeded these criteria; which did the engine actually blame?
        seeded = {sc for sc, v in expect.items() if v == FAIL}
        if seeded:
            blamed = sorted({pol._extract_sc(i.get("wcag", "")) for i in issues} - {None, ""})
            if seeded - set(blamed) and set(blamed) - seeded:
                attribution.append((fx["name"], ",".join(sorted(seeded)), blamed))

        # COUNT-LEVEL CHECK, where the fixture recorded how many defects it seeded.
        #
        # A per-criterion verdict is close to meaningless on a long document: a 25-page file with
        # eleven undescribed images and a file with one both resolve to "1.1.1: FAIL", and a
        # detector that finds one of eleven scores identically to one that finds all eleven. The
        # generator counted them at the moment it wrote them — the only moment the count is
        # reliably known — so the comparison is available and is the real measurement here.
        counts = {}
        if fx.get("truth"):
            # DISTINCT LOCATIONS, not findings. Some rules emit one located finding per defect
            # (DOCX-LINK-001, three of them, each naming its paragraph and URL) and others emit a
            # single ROLLUP with location=None summarising the same defects ("3 hyperlink(s) with
            # unclear text"). Counting rows conflates the two: the 25-page handbook seeds three
            # bad links, the engine reports them correctly, and a row count says four. That reads
            # as a false positive against the product and is an artefact of this scorer.
            buckets: dict[str, set] = {"undescribed_images": set(), "bad_links": set(),
                                       "headerless_tables": set()}
            for i in issues:
                rid = str(i.get("ruleId") or "").upper()
                # BOTH keys. The vendored .NET rules write `location`
                # ("docx:hyperlink:paragraph:115:url:…"); the Python detectors write `locator`
                # ("word/header1.xml#Picture 1"). Reading one of them silently drops every
                # finding from the other engine — which showed up here as the header-image
                # fixture scoring 0 of 1 on a defect the scan had in fact reported.
                loc = i.get("location") or i.get("locator")
                if not loc:
                    continue                  # a rollup — already counted via its members
                key = ("undescribed_images" if ("ALT" in rid or "IMAGE_NO_ALT" in rid) else
                       "bad_links" if "LINK" in rid else
                       "headerless_tables" if "TABLE" in rid else None)
                if key:
                    buckets[key].add(loc)
            seen = {k: len(v) for k, v in buckets.items()}
            for k, expected in fx["truth"].items():
                if k in seen:
                    counts[k] = (seen[k], expected)
                    if seen[k] != expected:
                        wrong.append(f"{k}: found {seen[k]} of {expected}")

        rows.append({"name": fx["name"], "kind": fx["kind"], "seconds": round(secs, 2),
                     "wrong": wrong, "issues": len(issues), "counts": counts})
        mark = "ok " if not wrong else "MISS"
        detail = "; ".join(wrong)
        if counts and not wrong:
            detail = "  ".join(f"{k.split('_')[0]} {g}/{e}" for k, (g, e) in counts.items())
        print(f"  {mark} {fx['kind']:11} {fx['name']:24} {len(issues):3} finding(s)"
              + (f"   {detail}" if detail else ""))

    # ── per-SC table ────────────────────────────────────────────────────────
    print(f"\n{'SC':8}{'lane':10}{'TP':>4}{'FP':>4}{'FN!':>5}{'abst':>6}{'TN':>4}"
          f"{'recall':>9}{'prec':>8}{'F1':>7}")
    f1s_det, f1s_rev = [], []
    for sc in scs:
        t = tally[sc]
        pos = t["tp"] + t["fn_pass"] + t["abstain_on_fail"]
        if not pos and not t["fp"] and not t["tn"]:
            continue
        recall = t["tp"] / pos if pos else float("nan")
        prec = t["tp"] / (t["tp"] + t["fp"]) if (t["tp"] + t["fp"]) else float("nan")
        f1 = (2 * recall * prec / (recall + prec)
              if pos and (t["tp"] + t["fp"]) and (recall + prec) else float("nan"))
        lane = "determ." if sc in can_pass else "review"
        (f1s_det if sc in can_pass else f1s_rev).append(f1)
        print(f"{sc:8}{lane:10}{t['tp']:>4}{t['fp']:>4}{t['fn_pass']:>5}"
              f"{t['abstain_on_fail']:>6}{t['tn']:>4}{recall:>9.2f}{prec:>8.2f}{f1:>7.2f}")

    def _macro(xs):
        xs = [x for x in xs if x == x]      # drop NaN
        return statistics.mean(xs) if xs else float("nan")

    tot_tp = sum(t["tp"] for t in tally.values())
    tot_fp = sum(t["fp"] for t in tally.values())
    tot_fnp = sum(t["fn_pass"] for t in tally.values())
    tot_abs = sum(t["abstain_on_fail"] for t in tally.values())
    tot_pos = tot_tp + tot_fnp + tot_abs
    tot_tn = sum(t["tn"] for t in tally.values())

    print(f"\n{'':8}macro-F1 deterministic lane (PASS-capable): {_macro(f1s_det):.2f}"
          f"   over {len(f1s_det)} SC")
    print(f"{'':8}macro-F1 review lane (no true-negative class): {_macro(f1s_rev):.2f}"
          f"   over {len(f1s_rev)} SC")
    micro_r = tot_tp / tot_pos if tot_pos else float("nan")
    micro_p = tot_tp / (tot_tp + tot_fp) if (tot_tp + tot_fp) else float("nan")
    print(f"{'':8}micro recall {micro_r:.2f}   micro precision {micro_p:.2f}"
          f"   ({tot_pos} seeded violations)")

    # ── the headline rates ──────────────────────────────────────────────────
    print("\n=== THE RATES THAT DECIDE THE POLICY QUESTION ===")
    print(f"  FALSE PASS       {tot_fnp:>3} / {tot_pos}  "
          f"({tot_fnp / tot_pos * 100 if tot_pos else 0:.1f}%)  "
          "— a real violation CERTIFIED as conformant. This is what ADR 0016 prevents.")
    print(f"  missed-to-review {tot_abs:>3} / {tot_pos}  "
          f"({tot_abs / tot_pos * 100 if tot_pos else 0:.1f}%)  "
          "— violation not asserted, but not certified either; costs a human, not a claim.")
    print(f"  false positive   {tot_fp:>3}       "
          "— flagged something compliant. Cheap, but it is what erodes trust in the tool.")
    print(f"  certified clean  {tot_tn:>3}       "
          "— PASS where PASS was correct, only reachable on the 4 deterministic SCs.")

    # The statistical ceiling on any claim this corpus can support. Rule of three: with n
    # observations and zero failures, the 95% upper bound on the true rate is about 3/n. Stating
    # it here stops "0 false PASSes" from being read as "0% false PASS rate" — with a corpus this
    # size those are very different claims, and only the second one clears a 99% gate.
    if tot_pos:
        bound = 3.0 / tot_pos * 100
        print(f"\n  CEILING ON THE CLAIM: {tot_pos} seeded violations. Even at zero observed "
              f"false passes,\n  the 95% upper bound on the true rate is ~{bound:.1f}% "
              f"(rule of three). Defending <=1% needs ~300\n  observations per criterion, not "
              f"per corpus — see docs on the AI-assessed lane proposal.")

    if attribution:
        print("\n=== ATTRIBUTION ERRORS (detected, blamed the wrong SC) ===")
        for name, seeded, blamed in attribution:
            print(f"  {name:24} seeded {seeded:8} -> reported {','.join(blamed) or '(none)'}")

    if latencies:
        ls = sorted(latencies)
        p95 = ls[min(len(ls) - 1, int(0.95 * len(ls)))]
        print(f"\nlatency  p50 {statistics.median(ls):.2f}s   p95 {p95:.2f}s   "
              f"n={len(ls)}   ({len(ls) / sum(ls) * 3600:.0f} docs/hour single-threaded)")

    if args.out:
        args.out.write_text(json.dumps(
            {"per_sc": tally, "fixtures": rows, "attribution": attribution,
             "false_pass": tot_fnp, "seeded": tot_pos}, indent=2) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
