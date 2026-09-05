#!/usr/bin/env python3
"""Generate the derivable half of docs/TODO.md from the code that decides it.

TODO.md calls itself "the single backlog", and it is — for *intent*. But it also carried
coverage counts, per-format gap statements, and a "last genuinely-open item" paragraph, all of
which are facts about the code rather than decisions about the work. Those went 387 commits
stale, and the stalest part was the headline: it described a per-format-applicability gap that
the capability registry had since closed.

The split this script draws:

  DERIVED (here)   which criteria have a detector, on which formats, at what coverage, and
                   which conformance levels are in scope. Recomputable, so it cannot drift.
  AUTHORED (there) whether we are going to build a thing, when, who owns it, and why it was
                   deferred. Not derivable from anything, and no generator should pretend.

Usage:
    python scripts/gen_todo_status.py            # splice into docs/TODO.md
    python scripts/gen_todo_status.py --stdout   # print the block, write nothing
    python scripts/gen_todo_status.py --check    # CI: fail if the file is out of date

`--check` is the point. Nothing forced this content to stay current, so it didn't — a backlog
whose facts are 387 commits old is worse than one with no facts, because it reads as current.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "api"
TODO = ROOT / "docs" / "TODO.md"

BEGIN = "<!-- BEGIN GENERATED: coverage-status"
END = "<!-- END GENERATED: coverage-status -->"

FORMATS = ("html", "docx", "xlsx", "pptx", "pdf")
# The four Required (A/AA) criteria TODO.md's headline paragraph called out as auto-detected for
# HTML but UNCHECKED for PDF/Office. Kept here so the doc's own open question gets answered with
# current data every run, instead of by a sentence nobody re-checked.
HEADLINE_GAPS = ("1.4.1", "1.3.5", "2.5.3", "4.1.2")

# The disposition table TODO.md carried by hand. It is a fact about a file, so it belongs here.
#
# WHY IT MOVED. The authored version said 36 shipped / 45 HITL / 6 partner and told the reader to
# "treat them as 2026-07-09 figures until someone re-counts against the catalog", because
# `frontend/src/wcagCatalog.js` was not in the checkout when that paragraph was written. The
# catalog arrived on 2026-08-28 (#907) and nothing re-counted: the real split is 37 / 44 / 6.
# One criterion had moved from HITL to shipped and the doc could not say so — which is the exact
# failure this script's own docstring describes, recurring in the half it had not reached.
CATALOG = ROOT / "frontend" / "src" / "wcagCatalog.js"

# What each `source:` value means, in the doc's own words. Ordered by size so the table reads the
# way the old one did.
CATALOG_BUCKETS = {
    "Shipped (demo)": "Real automated validator, verified backing",
    "MDK HITL": "Human-judgment criteria — routed to the HITL queue",
    "Partner baseline": "Covered by the .NET partner engine (`spike/dotnet/AcpScan.Cli`)",
}


def catalog_counts() -> dict[str, int]:
    """{source: count} over the criteria in wcagCatalog.js.

    A REGEX RATHER THAN A JS PARSER, and the risk that carries is a pattern that silently matches
    nothing — which would render every bucket as zero and read as "no coverage at all". The
    caller checks the total against the catalog's own count of `sc:` keys for exactly that reason.
    """
    import collections
    import re
    text = CATALOG.read_text(encoding="utf-8")
    rows = re.findall(r'\{sc:"[\d.]+".*?source:"([^"]+)"', text)
    return dict(collections.Counter(rows))


def _load():
    sys.path.insert(0, str(API))
    import store
    try:
        import rule_registry
        rule_registry.load()
    except Exception as exc:                       # bare CI container, no parsers
        print(f"note: registry unavailable ({exc.__class__.__name__}: {exc})", file=sys.stderr)
        rule_registry = None
    return store, rule_registry


def _remediation_gaps() -> list[tuple[str, str]]:
    """(criterion, format) pairs ACP assesses but declares no remediation lane for.

    Derived by asking `gen_matrix_coverage.py` rather than re-deriving it here: that script
    already owns the definition (and the awkward parts of it — the write-back applier surface
    is read out of handlers.py's AST), and a second copy of the rule in this file is precisely
    the kind of quietly-diverging fact the whole script exists to stop writing.

    Degrades to an empty list rather than failing the doc build: this runs in a bare CI
    container, and a TODO block is not worth breaking a pipeline over. The generator's own
    `--check` is where a moved source is supposed to fail loudly.
    """
    try:
        import importlib.util
        path = ROOT / "scripts" / "gen_matrix_coverage.py"
        spec = importlib.util.spec_from_file_location("acp_gen_matrix_coverage_todo", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        data = mod.build()
    except Exception as exc:
        print(f"note: matrix coverage unavailable ({exc.__class__.__name__}: {exc})",
              file=sys.stderr)
        return []
    return [(sc, fmt) for sc, fmts in data["cells"].items()
            for fmt, cell in fmts.items() if cell["remediation_gap"]]


def signals_for(store, registry, sc: str, fmt: str) -> str:
    """How this (criterion, format) is covered today, in one word.

    Reads every table that can put a criterion in scope, in decreasing authority: the capability
    registry (explicit coverage), the pass/fail lane, the review-only lane. Anything else is a
    genuine blank — no signal of any kind.
    """
    if registry is not None:
        reg = registry.get(sc, fmt)
        if reg is not None:
            return reg.coverage.value
    if fmt in store.RULE_FORMATS.get(sc, frozenset()):
        return "pass/fail"
    if fmt in store.REVIEW_FORMATS.get(sc, frozenset()):
        return "review"
    return "—"


def build(store, registry) -> str:
    lines: list[str] = []
    add = lines.append

    add("### Coverage status — generated, do not edit by hand")
    add("")
    add("Regenerate with `python scripts/gen_todo_status.py`; CI fails if this block is stale "
        "(`--check`). Everything below is read from `api/rule_registry.py`, `api/store.py` "
        "(`RULE_FORMATS` / `REVIEW_FORMATS`) and `config/rule-catalog.json` — the code that "
        "actually decides it. Intent, priority and ownership are authored above and below; this "
        "block never speaks to those.")
    add("")

    # ── conformance target ────────────────────────────────────────────────────────────
    target = store.config_target()
    aaa = sorted(r["id"] for r in store.RULE_CATALOG if (r.get("level") or "A") == "AAA")
    add(f"**Conformance target: {target}.** Criteria above the target are not assessed at all "
        f"(`store.in_target`). Selectable targets are {', '.join(store.TARGET_LEVELS)}, so the "
        f"{len(aaa)} AAA criteria are never assessed: {', '.join(f'`{s}`' for s in aaa)}.")
    add("")
    add("This is a behaviour change, not bookkeeping: several detectors compute the AA and AAA "
        "thresholds in one pass, so AAA findings were previously scored against AA-target files.")
    add("")

    # ── the disposition of all 87 criteria ────────────────────────────────────────────
    counts = catalog_counts()
    declared = len(re.findall(r'\{sc:"[\d.]+"', CATALOG.read_text(encoding="utf-8")))
    total = sum(counts.values())
    if total != declared:
        raise SystemExit(
            f"gen_todo_status: the catalog parse found {total} sources for {declared} criteria in "
            f"{CATALOG.relative_to(ROOT)} — the regex has drifted from the file's shape, and "
            f"emitting the counts anyway would understate coverage")

    add(f"**Criterion disposition — {declared} success criteria**, counted from "
        f"`frontend/src/wcagCatalog.js` (its `source:` field). Every criterion has a closed "
        f"disposition; the buckets are the catalog's own.")
    add("")
    add("| Bucket | Count | Meaning |")
    add("|---|---:|---|")
    for bucket, meaning in CATALOG_BUCKETS.items():
        add(f"| {bucket} | {counts.get(bucket, 0)} | {meaning} |")
    unknown = sorted(set(counts) - set(CATALOG_BUCKETS))
    for bucket in unknown:
        add(f"| {bucket} | {counts[bucket]} | **not described here — a new bucket appeared in "
            f"the catalog** |")
    add("")

    # ── capability registry ───────────────────────────────────────────────────────────
    regs = registry.all_registrations() if registry is not None else []
    add(f"**Capability registry — {len(regs)} (criterion, format) pair(s) migrated.** "
        f"Coverage is declared beside the detector; only `full` may certify a pass.")
    add("")
    if regs:
        add("| Criterion | Format | Coverage | Confidence | Not covered |")
        add("|---|---|---|---|---|")
        for r in regs:
            why = (r.reason or "").split(";")[-1].strip() or "—"
            add(f"| `{r.rule}` | {r.fmt} | **{r.coverage.value}** | {r.confidence.value} "
                f"| {why[:110]} |")
    else:
        add("_Registry unavailable in this environment._")
    add("")

    # ── the doc's own headline question ───────────────────────────────────────────────
    add("**The four Required format gaps** this file's header has tracked since the first "
        "snapshot — auto-detected for HTML, historically UNCHECKED for PDF/Office:")
    add("")
    add("| Criterion | " + " | ".join(f.upper() for f in FORMATS) + " |")
    add("|---|" + "---|" * len(FORMATS))
    for sc in HEADLINE_GAPS:
        cells = " | ".join(signals_for(store, registry, sc, f) for f in FORMATS)
        add(f"| `{sc}` | {cells} |")
    add("")
    add("`partial` / `heuristic` / `full` come from the registry and mean a real detector runs. "
        "`review` means a review-lane detector surfaces evidence but never certifies. `—` means "
        "no signal of any kind — the genuine remaining gap.")
    add("")

    # ── undeclared coverage ───────────────────────────────────────────────────────────
    # A detector that emits for a pair no scope table admits: findings surface as FAIL, yet the
    # pair can never PASS. Three of these existed; the registry closed them.
    add("**Undeclared coverage** — detectors emitting for a (criterion, format) that no scope "
        "table admits. `scripts/gen_matrix_coverage.py` reports these; all known instances "
        "(`1.4.11` xlsx, `2.4.3` pdf, `4.1.2` pdf) are now declared in the registry.")
    add("")
    # ── undeclared REMEDIATION, which is a different gap on a different axis ───────────
    # Registering a pair answers "what does the detector examine?" and nothing else. Whether a
    # fixer writes is `api/remediation_capability.REMEDIATION`, and a pair can be fully declared
    # on the assessment axis while the remediation axis says nothing at all. It used to be
    # invisible: the matrix generator turned a missing lane into a confident "No Remediation",
    # which read as a settled fact rather than the gap it is (pdf 4.1.2 shipped a working fixer
    # under that label until the lane was added). The generator now emits a null ceiling and a
    # NO REMEDIATION LANE note per cell, so the remaining ones are worth naming here too.
    gaps = _remediation_gaps()
    listed = (", ".join(f"`{sc}` {fmt}" for sc, fmt in gaps) if gaps
              else "none — every assessed pair has a declared lane")
    add(f"**Undeclared remediation ({len(gaps)})** — a pair ACP assesses (a detector emits it, "
        f"a review lane admits it, or the registry declares it) with no entry in "
        f"`api/remediation_capability.REMEDIATION`. Registration says what the DETECTOR "
        f"examines and nothing about whether a FIXER writes, so the two go stale separately. "
        f"`scripts/gen_matrix_coverage.py` reports each as an explicit gap with an unknown "
        f"(null) remediation ceiling rather than inferring \"no remediation\" from the "
        f"assessment axis — the inference that hid a working PDF form-field fixer behind "
        f"\"No Remediation\" until `4.1.2` pdf got its lane. Open: {listed}.")
    add("")
    return "\n".join(lines)


def splice(block: str) -> tuple[str, bool]:
    text = TODO.read_text()
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0:
        raise SystemExit(
            f"{TODO.name}: markers not found. Add\n  {BEGIN} ... -->\n  {END}\n"
            f"around the generated section first.")
    head = text[i:text.index("-->", i) + 4]
    new = f"{head}\n{block}\n"
    return text[:i] + new + text[j:], text[i:j] != new


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stdout", action="store_true", help="print the block, write nothing")
    ap.add_argument("--check", action="store_true", help="fail if docs/TODO.md is out of date")
    args = ap.parse_args()

    store, registry = _load()
    block = build(store, registry)

    if args.stdout:
        print(block)
        return 0

    text, changed = splice(block)
    if args.check:
        if changed:
            print("docs/TODO.md coverage block is STALE — run "
                  "`python scripts/gen_todo_status.py` and commit the result.", file=sys.stderr)
            return 1
        print("docs/TODO.md coverage block is current")
        return 0
    if not changed:
        print("coverage block unchanged")
        return 0
    TODO.write_text(text)
    print(f"regenerated the coverage block in {TODO.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
