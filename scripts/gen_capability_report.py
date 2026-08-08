#!/usr/bin/env python3
"""What ACP can actually prove about the 17 tracked criteria — as a document you can hand over.

WHY THIS EXISTS. The facts in this report are all derivable today, from four modules, and none
of them are readable in one place. `assessment_policy` knows which (criterion, format) pairs are
in the Core 17 and what a clean file resolves to; `remediation_capability` knows which lane each
pair sits in; `corpus_expectations` knows which verdicts a pair is even ALLOWED to reach. A
reviewer asking "what does a green scan actually certify" currently has to hold three tables in
their head and join them by hand, which is how the answer gets stated as a percentage nobody can
defend.

THE NUMBER THIS EXISTS TO SURFACE. Most Core-17 pairs cannot certify a PASS — not because they
are unimplemented, but by design: a REVIEW_FORMATS pair resolves to REVIEW when its detector
fires and NOT_EVALUATED when it does not, and never to PASS. A clean scan on those pairs means
"nothing was found by a check that was never able to conclude", which is a very different claim
from conformance. That distinction is the single most misreadable thing about the product, and
it is the first thing in the output.

WHAT IT DOES NOT DO. It does not scan. Every column here is a property of the ENGINE, not of any
document, so the report is reproducible from a checkout with no corpus, no database and no
network. Observed per-file behaviour is a separate question and belongs to the corpus run — see
--corpus, which annotates the same table with what the manifest expects rather than replacing
any of it.

Usage:
    python scripts/gen_capability_report.py                 # markdown to stdout
    python scripts/gen_capability_report.py -o report.md
    python scripts/gen_capability_report.py --corpus test-corpus/manifest.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))

import assessment_policy as pol            # noqa: E402
import corpus_expectations as ce           # noqa: E402
import remediation_capability as cap       # noqa: E402

PRESET = "acp-core-17"

# Formats in a fixed order so two runs of this script diff cleanly. Sorting by name would put
# pdf between docx and pptx, which reads oddly next to the Office trio it does not belong to.
FORMAT_ORDER = ("docx", "pptx", "xlsx", "pdf")

LANE_LABEL = {"auto": "AUTO", "assisted": "ASSISTED", "human": "HUMAN"}

# A pair the Core 17 claims but REMEDIATION has no row for. `lane()` answers None there while
# `mode_for()` — the accessor the /capability route and the frontend actually use — answers
# "human". So the product behaves consistently; what is missing is a STATEMENT of intent, and
# rendering it as "None" would misreport a default as a hole. 14 of the 61 pairs are in this
# state (1.4.1, 1.4.11, 2.1.2, 2.4.3, 4.1.2), which is enough to be worth naming rather than
# flattening into the HUMAN count.
IMPLICIT = "HUMAN (implicit)"


def _rem_label(lane: str | None) -> str:
    return IMPLICIT if lane is None else LANE_LABEL.get(lane, lane)


def _sc_sort(sc: str) -> tuple[int, ...]:
    """1.4.11 sorts AFTER 1.4.5, which string ordering gets wrong — and gets wrong quietly, in a
    table whose whole job is to be read in order."""
    return tuple(int(p) for p in sc.split("."))


def _git_sha() -> str:
    """Stamp the commit, not the clock. A timestamp makes every regeneration a diff even when
    nothing changed; a SHA says exactly which engine produced these claims, which is the thing a
    reader actually needs in order to trust or re-derive them."""
    try:
        out = subprocess.run(["git", "-C", str(ACP), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def rows() -> list[dict]:
    """One row per (criterion, format) pair in the Core 17 preset."""
    preset = pol.SCOPE_PRESETS[PRESET]
    out: list[dict] = []
    for sc in sorted(preset, key=_sc_sort):
        for fmt in FORMAT_ORDER:
            if fmt not in preset[sc]:
                continue
            out.append({
                "sc": sc,
                "fmt": fmt,
                "assessment": cap.assessment_lane(fmt, sc),
                # NOTE the argument orders differ between these two modules and it is easy to
                # transpose: cap.lane(fmt, sc), ce.* (sc, fmt). Both take two strings, so a
                # transposition does not raise — it silently reports another pair's lane.
                "remediation": cap.lane(fmt, sc),
                "clean": ce.clean_verdict(sc, fmt),
                "can_pass": ce.can_ever_pass(sc, fmt),
                "possible": sorted(ce.possible_verdicts(sc, fmt)),
            })
    return out


def _corpus_index(path: Path) -> dict[tuple[str, str], list[str]]:
    """Manifest expectations keyed by (sc, fmt), for the optional observed column.

    Shape-tolerant on purpose: this reads a hand-authored corpus manifest, and the report is
    worth more degraded than absent. An entry it cannot parse is skipped rather than fatal.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        print(f"warning: could not read {path}: {e}", file=sys.stderr)
        return {}
    entries = data if isinstance(data, list) else (data.get("files") or data.get("entries") or [])
    idx: dict[tuple[str, str], list[str]] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("file") or entry.get("name") or "")
        fmt = (entry.get("format") or name.rsplit(".", 1)[-1] or "").lower()
        # Two shapes, because the repo has two manifests and only one is ground truth.
        # test-corpus/generate.py records `expected_rule_ids` per file — that is the oracle. The
        # checked-in test-corpus/manifest.json is a DIFFERENT, descriptive file (file/size_kb/
        # desc, 12 entries) with no criterion-level expectations at all, so pointing this at it
        # yields an honest but useless zero. Read both rather than assuming which one was passed.
        for sc in (entry.get("expected_rule_ids") or []):
            idx.setdefault((str(sc), fmt), []).append(str(entry.get("expected_outcome") or "fail"))
        for sc, status in (entry.get("expect") or entry.get("expected") or {}).items():
            idx.setdefault((str(sc), fmt), []).append(str(status))
    return idx


def render(data: list[dict], corpus: dict | None = None) -> str:
    total = len(data)
    can = sum(1 for r in data if r["can_pass"])
    cannot = total - can
    scs = sorted({r["sc"] for r in data}, key=_sc_sort)

    L: list[str] = []
    L.append("# ACP — what a scan can prove about the Core 17")
    L.append("")
    L.append(f"Generated by `scripts/gen_capability_report.py` from engine commit `{_git_sha()}`. "
             "Every column is a property of the engine, not of any document — this is "
             "reproducible from a checkout with no corpus and no network.")
    L.append("")
    L.append("## The headline")
    L.append("")
    L.append(f"- **{len(scs)} criteria**, **{total} (criterion, format) pairs** in `{PRESET}`.")
    L.append(f"- **{can} of {total} pairs can certify a PASS.**")
    L.append(f"- **{cannot} of {total} cannot** — a clean scan on those is *not* a conformance "
             "claim.")
    L.append("")
    L.append("That second number is the one to read carefully, and it is not a backlog. A pair "
             "in `REVIEW_FORMATS` resolves to `REVIEW` when its detector fires and "
             "`NOT_EVALUATED` when it does not; it never resolves to `PASS`. So on those pairs a "
             "clean result means *nothing was found by a check that could not conclude either "
             "way* — which is a weaker statement than \"this document conforms\", and is the "
             "single most misreadable thing in the product.")
    L.append("")
    L.append("`NOT_EVALUATED` is deliberately not called *not applicable*: the honest claim is "
             "that nobody looked, not that the criterion does not apply.")
    L.append("")

    L.append("## Lanes")
    L.append("")
    L.append("- **Assessment** — can the engine reach a verdict deterministically (🟢), only "
             "gather evidence for a human (🟡), or not at all (🔴)?")
    L.append("- **Remediation** — `AUTO` writes the fix back; `ASSISTED` drafts one for approval; "
             "`HUMAN` means a person does the work.")
    L.append("")
    for axis, key in (("Assessment", "assessment"), ("Remediation", "remediation")):
        counts: dict[str, int] = {}
        for r in data:
            # "HUMAN (implicit)" is a statement about the REMEDIATION axis specifically —
            # mode_for() defaults an unlisted pair to human. The assessment axis has no such
            # default (CAPABILITY is derived from REMEDIATION, so an unlisted pair is simply
            # absent from both), and borrowing the remediation word here would assert a fallback
            # that does not exist.
            label = _rem_label(r[key]) if key == "remediation" else str(r[key] or "unlisted")
            counts[label] = counts.get(label, 0) + 1
        parts = ", ".join(f"`{k}` {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        L.append(f"- **{axis}**: {parts}")
    L.append("")

    implicit = [r for r in data if r["remediation"] is None]
    if implicit:
        L.append(f"**{len(implicit)} of {total} pairs have no explicit remediation entry.** "
                 "`REMEDIATION` has no row for them, so `mode_for()` — the accessor the "
                 "`/capability` route and the frontend read — answers `human` by default. The "
                 "behaviour is therefore consistent; what is absent is a recorded decision. "
                 "Worth confirming each was intended as HUMAN rather than missed:")
        L.append("")
        by_sc: dict[str, list[str]] = {}
        for r in implicit:
            by_sc.setdefault(r["sc"], []).append(r["fmt"])
        for sc in sorted(by_sc, key=_sc_sort):
            L.append(f"- **{sc}** — {', '.join(f'`{f}`' for f in by_sc[sc])}")
        L.append("")

    L.append("## Per-criterion detail")
    L.append("")
    hdr = "| Criterion | Format | Assessment | Remediation | Clean file resolves to | Can PASS? |"
    L.append(hdr)
    L.append("|---|---|---|---|---|---|")
    for r in data:
        L.append(
            f"| {r['sc']} | `{r['fmt']}` | `{r['assessment'] or '—'}` | "
            f"`{_rem_label(r['remediation'])}` | "
            f"`{r['clean']}` | {'yes' if r['can_pass'] else '**no**'} |")
    L.append("")

    L.append("## Criteria that can never certify, on any format")
    L.append("")
    never = [sc for sc in scs
             if not any(r["can_pass"] for r in data if r["sc"] == sc)]
    if never:
        L.append("These are the ones where a green result carries the least information, so they "
                 "are where a reviewer's attention is worth the most:")
        L.append("")
        for sc in never:
            fmts = ", ".join(f"`{r['fmt']}`" for r in data if r["sc"] == sc)
            L.append(f"- **{sc}** — {fmts}")
    else:
        L.append("None: every criterion can certify on at least one format.")
    L.append("")

    if corpus is not None:
        L.append("## Corpus coverage")
        L.append("")
        covered = sum(1 for r in data if (r["sc"], r["fmt"]) in corpus)
        L.append(f"The manifest carries expectations for **{covered} of {total}** pairs.")
        L.append("")
        if not covered:
            L.append("**Zero is a real answer here, not a parsing failure — and it is the "
                     "finding.** The checked-in `test-corpus/manifest.json` is a descriptive "
                     "index (`file`, `size_kb`, `desc`); it carries no criterion-level "
                     "expectations. The ground-truth manifest is the one "
                     "`test-corpus/generate.py` emits, with `expected_rule_ids` per file, and it "
                     "has to be regenerated to exist.")
            L.append("")
            L.append("The consequence is worth stating plainly: `scripts/corpus_expectations.py` "
                     "was built to stop a manifest from expecting a verdict the engine cannot "
                     "produce — but with no expectations recorded, there is nothing for it to "
                     "check, and no measurement of whether any detector is CORRECT. Every lane "
                     "in the table above is a claim the engine makes about itself.")
            L.append("")
        gaps = [r for r in data if (r["sc"], r["fmt"]) not in corpus]
        if gaps:
            L.append("Pairs with **no fixture expecting anything** — untested, and silently so, "
                     "since a pair nothing exercises cannot fail:")
            L.append("")
            for r in gaps:
                L.append(f"- {r['sc']} / `{r['fmt']}`")
        L.append("")

    L.append("## What this report does not tell you")
    L.append("")
    L.append("- **Whether the detectors are correct.** Every column here is what the engine "
             "*claims*; none of it is measured against a document. A pair can sit in `AUTO` and "
             "still be wrong.")
    L.append("- **Anything about PDF, measured locally.** The PDF analyser is loaded at runtime "
             "from `ACP_PDF_ENGINE` and is not vendored into this repo, so PDF pairs are "
             "unrunnable on a fresh checkout — including in CI, where the PDF-dependent suites "
             "skip. The lanes below are still accurate; only observation is missing.")
    L.append("- **Whether the AI lane produces usable output.** `ASSISTED` says a draft is "
             "offered, not that it is good. That is a question for "
             "`scripts/bench_models.py --ladder`, which compares models on the criteria that "
             "actually call one.")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, help="write here instead of stdout")
    ap.add_argument("--corpus", type=Path, help="a corpus manifest, for the coverage section")
    args = ap.parse_args()

    corpus = _corpus_index(args.corpus) if args.corpus else None
    text = render(rows(), corpus)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
