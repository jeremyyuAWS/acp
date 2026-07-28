#!/usr/bin/env python3
"""Emit the code-derived capability ceiling for every WCAG-matrix grid cell.

The matrix at https://wcag-matrix.mova-io.app/ scores 20 SCs x 4 document formats on two
axes — assessment (`ROWS.a`) and remediation (`ROWS.r`). Those 80 cells have always been
hand-verified against this repo, which is exactly why CLAUDE.md ground rule 4 carries a
growing list of "catalog != code" drift, some of it in the risky direction (a cell claiming
more automation than the code actually performs).

This script derives, from shipped code, the STRONGEST tier each cell could honestly claim.
It does not decide the tier. The matrix may always claim LESS — ground rule 3's honest-partial
rule makes a deliberate downgrade a valid editorial act — so the consumer
(wcag-matrix/scripts/check_grid_drift.py) only flags cells that claim MORE than the code
supports. That asymmetry is the whole design: over-claiming is a correctness bug, under-
claiming is a judgment call, and only the first can be caught mechanically.

Sources, in order of authority
------------------------------
1. api/remediation_capability.py — the primary signal. A dense (format x SC) -> lane table
   whose every entry is proven by tests/test_remediation_capability.py against the real
   remediators: each "auto" is triggered on a fixture, remediated, re-scanned, and asserted
   to no longer fire. It also derives the assessment axis (ADR 0023). Nothing else in the
   repo makes a capability claim that has been round-trip proven, so nothing else outranks it.
2. api/handlers.py — APPLIER PRESENCE. An "assisted" lane means a human approves a proposal;
   it does NOT mean the approval reaches the file. Where no write-back applier is wired, the
   approval is a no-op (the exact defect ground rule 4 flags), so the honest remediation
   ceiling is "guided manual", not "AI proposal". This is the check that catches risky-
   direction drift, and it is why applier presence is read from code rather than assumed.
3. api/proposals.py — AI IN THE DECISION PATH. Ground rule 2 caps any cell with an LLM in a
   decision path at Guided / AI-Proposal. Read from code so a newly model-backed proposer
   lowers its own ceiling without anyone remembering to.
4. config/rule-catalog.json + the first-party Python checks (via gen_rules_index.py) —
   DETECTOR PRESENCE, corroborating only. These are catalog/code inventories, not proofs,
   so they never raise a ceiling; they are carried into the output as per-cell evidence so a
   drift PR can show its work, and to surface catalog-vs-lane disagreement as a note.

Usage:
    python scripts/gen_matrix_coverage.py                 # full coverage JSON -> stdout
    python scripts/gen_matrix_coverage.py --explain       # human-readable table
    python scripts/gen_matrix_coverage.py --check         # fail if a source's shape moved
    python scripts/gen_matrix_coverage.py --sources       # the repo paths a ceiling depends on

This emits a CEILING, never a tier. Writing tiers into the matrix is the matrix's own job,
behind a pull request a human approves — see wcag-matrix/.github/workflows/grid-drift.yml.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "api"
CATALOG = ROOT / "config" / "rule-catalog.json"

# The matrix's own axes. Formats are its four document columns — `html` is a real ACP engine
# but the matrix has no column for it, so it is read and discarded here rather than silently
# widening the grid.
FORMATS = ("docx", "xlsx", "pptx", "pdf")

# The 20 SCs the matrix has rows for. Kept in sync with gen_progress_log.TRACKED_SCS by
# _check(); a criterion ACP starts covering does not appear here until the matrix grows a row.
TRACKED_SCS = (
    "1.1.1", "1.3.1", "1.3.2", "1.3.3", "1.4.1", "1.4.3", "1.4.4", "1.4.5",
    "1.4.10", "1.4.11", "1.4.12", "2.1.1", "2.1.2", "2.4.2", "2.4.3", "2.4.4",
    "2.4.6", "3.1.1", "3.1.2", "4.1.2",
)

# Matrix vocabulary (index.html's AL/RL maps). Ordered weakest -> strongest claim; the
# consumer compares ranks, so this ordering IS the contract.
A_TIERS = ("NA", "H", "Q", "C")          # Not applicable < Human < Guided < Certified
R_TIERS = ("NA", "N", "M", "AI", "AP", "AC", "A")

# Every repo path a ceiling is computed from. Declared here, beside the loaders that read them,
# so the notify workflow can ask "did this push touch anything that could move a ceiling?"
# without keeping a second copy of the list in YAML that would drift from this one.
SOURCES = (
    "api/remediation_capability.py",   # the proven lane table (primary)
    "api/store.py",                    # REVIEW_FORMATS — the second, review-only scope table
    "api/handlers.py",                 # write-back applier surface
    "api/proposals.py",                # model-backed proposers
    "config/rule-catalog.json",        # detector inventory + claimed fix_mode
    "api/office_structure.py",         # first-party checks, via gen_rules_index
    "api/textchecks.py",
    "api/ocr.py",
    "scripts/gen_matrix_coverage.py",  # a change to the derivation itself moves ceilings too
    "scripts/gen_rules_index.py",
)

# lane -> the strongest matrix tier that lane can honestly support.
# A missing lane (ACP does not evaluate this pair) is NOT "not applicable": the criterion may
# still apply to the format in WCAG terms, ACP simply automates nothing for it. So the ceiling
# is "a human does it", which lets the matrix say H/NA on the assessment axis and M/N/NA on the
# remediation axis, but never C/Q or any flavour of automatic.
A_CEILING = {"auto": "C", "review": "Q", "human": "H", None: "H"}
R_CEILING = {"auto": "A", "assisted": "AI", "human": "M", None: "N"}


def _load(name: str, path: Path):
    """Import a module by path without requiring the package to be importable."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"gen_matrix_coverage: cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. the proven lane table ──────────────────────────────────────────────────────────
def load_capability() -> dict[str, dict[str, dict[str, str]]]:
    """CAPABILITY[fmt][sc] = {"assessment": lane, "remediation": lane}, straight from the
    round-trip-proven module. Imported rather than parsed: it is a dependency-free data
    module, and importing means this script cannot misread a table its own tests guarantee."""
    return _load("acp_remediation_capability", API / "remediation_capability.py").CAPABILITY


# ── 1b. the review-only scope table ───────────────────────────────────────────────────
def load_review_formats() -> dict[str, set[str]]:
    """{sc: {formats}} from store.REVIEW_FORMATS — the SECOND scope table (ADR 0023).

    A pair listed here runs a REVIEW detector: it surfaces evidence of a likely issue for a
    human to adjudicate, resolving to REVIEW when the detector fires and NOT_EVALUATED when it
    does not. It never resolves to PASS, because ACP did not verify conformance (ADR 0016).

    That is exactly the matrix's Guided-review tier, so these pairs support Q even though
    remediation_capability.py has no lane for them. Missing this table would cap a dozen
    legitimately-detected cells at Human and report the matrix's correct Q claims as drift —
    the check would be loudest precisely where it was most wrong.

    Parsed rather than imported: store.py pulls in the database driver, and this script must
    run in a bare CI container with only the repo checked out.
    """
    tree = ast.parse((API / "store.py").read_text())
    node = next((n for n in tree.body
                 if isinstance(n, (ast.Assign, ast.AnnAssign))
                 and any(getattr(t, "id", None) == "REVIEW_FORMATS"
                         for t in ([n.target] if isinstance(n, ast.AnnAssign) else n.targets))),
                None)
    if node is None or not isinstance(node.value, ast.Dict):
        raise SystemExit("gen_matrix_coverage: store.REVIEW_FORMATS not found as a dict "
                         "literal — the review-lane scope table moved; update this generator.")
    out: dict[str, set[str]] = {}
    for k, v in zip(node.value.keys, node.value.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        fmts = {n.value for n in ast.walk(v)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        out[k.value] = fmts & set(FORMATS)
    return out


# ── 2. applier presence ───────────────────────────────────────────────────────────────
def load_appliers() -> dict[str, set[str]]:
    """{format: {SCs whose approved value is actually written back into the file}}.

    Read from handlers._apply_approved_values' calls to `_apply_one_value_kind`, which is the
    only path from an approved HITL row to bytes on disk. Each call names the SCs it clears
    (`scs_to_clear=`) and is gated on a module-level format constant; pairing the two gives the
    true applier surface. A proposal outside it is a no-op on approval no matter how confident
    the catalog is — see the module docstring.
    """
    src = (API / "handlers.py").read_text()
    tree = ast.parse(src)

    # Module-level format constants the gates are expressed with (dict of ext -> mime, or a
    # tuple of exts). Collected generically so renaming one doesn't silently drop a lane.
    consts: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name, val = node.targets[0].id, node.value
        if isinstance(val, ast.Dict):
            keys = {k.value for k in val.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if keys & set(FORMATS):
                consts[name] = keys
        elif isinstance(val, (ast.Tuple, ast.List, ast.Set)):
            items = {e.value for e in val.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if items & set(FORMATS):
                consts[name] = items

    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "_apply_approved_values"), None)
    if fn is None:
        raise SystemExit("gen_matrix_coverage: handlers._apply_approved_values not found — "
                         "the write-back path moved; update this generator.")

    # The function's own guard names the formats that reach ANY applier; a call may narrow
    # further with its own gate (link text is Office-only within that set).
    gate_names = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id in consts]
    if not gate_names:
        raise SystemExit("gen_matrix_coverage: no format gate found in "
                         "_apply_approved_values — update this generator.")
    outer = consts[gate_names[0]]

    out: dict[str, set[str]] = {f: set() for f in FORMATS}
    calls = 0
    for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
        fname = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        if fname != "_apply_one_value_kind":
            continue
        kw = {k.arg: k.value for k in call.keywords}
        scs_node = kw.get("scs_to_clear")
        if not isinstance(scs_node, (ast.Set, ast.List, ast.Tuple)):
            raise SystemExit("gen_matrix_coverage: _apply_one_value_kind called without a "
                             "literal scs_to_clear — update this generator.")
        scs = {e.value for e in scs_node.elts if isinstance(e, ast.Constant)}
        calls += 1
        # Narrow to this call's own gate when it has one, else the function-wide gate.
        exts = outer
        for nm, allowed in consts.items():
            if nm in gate_names[1:] and _guards(call, fn, nm):
                exts = outer & allowed
        for f in exts & set(FORMATS):
            out[f] |= scs
    if not calls:
        raise SystemExit("gen_matrix_coverage: no _apply_one_value_kind calls found — "
                         "update this generator.")
    return out


def _guards(call: ast.Call, fn: ast.FunctionDef, const_name: str) -> bool:
    """True when `call` sits under a conditional that tests `const_name`.

    Link-text write-back is wired as `if link_values:` where link_values was itself computed
    under an `ext in _OFFICE_LINK_EXTS` test. Rather than trace the dataflow, ask the cheaper
    structural question: does the assignment feeding this call's `values=` mention the
    constant? That is enough to tell a narrowed lane from a function-wide one.
    """
    kw = {k.arg: k.value for k in call.keywords}
    values = kw.get("values")
    target = getattr(values, "id", None)
    if not target:
        return False
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == target for t in node.targets):
            if any(getattr(n, "id", None) == const_name for n in ast.walk(node.value)):
                return True
    return False


# ── 3. AI in the decision path ────────────────────────────────────────────────────────
def load_ai_pairs() -> set[tuple[str, str]]:
    """{(sc, format)} whose proposer consults a model, so ground rule 2 caps them at AI-proposal.

    A proposer counts when it both imports api/ai.py and names an SC in the same function —
    the `suggest_fix("2.4.6", ...)` shape proposals.py uses throughout. Reading it structurally
    means a proposer that GAINS a model call lowers its own ceiling on the next run, with no
    list here to remember to update.

    The pairing MUST be per format, not per SC. Two different proposers draft 2.4.6 (slide
    titles for pptx, sheet/column labels for xlsx) while docx 2.4.6 is closed deterministically
    by the 1.3.1 outline fix with no model anywhere near it — an SC-only signal would cap docx
    2.4.6 on the strength of a pptx proposer. Each proposer self-gates on its format
    (`ext.lower().lstrip(".") != "pptx"`), so the format literals in its body ARE its scope;
    naming none means format-agnostic (the text proposers), which is every format.
    """
    tree = ast.parse((API / "proposals.py").read_text())
    out: set[tuple[str, str]] = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        uses_ai = any(
            (isinstance(n, ast.Import) and any(a.name == "ai" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "ai")
            for n in ast.walk(fn))
        if not uses_ai:
            continue
        strs = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        scs = {s for s in strs if re.fullmatch(r"\d+\.\d+\.\d+", s)}
        exts = {s.lstrip(".") for s in strs if s.lstrip(".") in FORMATS}
        for sc in scs:
            for fmt in (exts or FORMATS):
                out.add((sc, fmt))
    return out


# ── 4. detector inventory (corroborating evidence only) ───────────────────────────────
def load_detectors() -> dict[str, dict[str, list[str]]]:
    """{fmt: {sc: [rule id, ...]}} from the engine catalog plus the first-party Python checks.

    Never raises a ceiling — a rule existing in a catalog is not proof it runs, which is the
    drift ground rule 4 exists to describe. Carried so a drift PR can cite what backs a cell.
    """
    out: dict[str, dict[str, list[str]]] = {f: {} for f in FORMATS}
    catalog = json.loads(CATALOG.read_text())
    for fmt in FORMATS:
        for rule in catalog.get(fmt, []):
            out[fmt].setdefault(rule["wcag_sc"], []).append(rule["id"])

    # The first-party checks are not in the catalog by design (ADR 0002 restricts it to
    # A/AA engine rules with a per-rule doc). gen_rules_index already parses them from code
    # with their real dispatch formats; reuse it rather than re-deriving a second, drifting copy.
    try:
        gri = _load("acp_gen_rules_index", ROOT / "scripts" / "gen_rules_index.py")
        for sc, checks in gri.load_first_party().items():
            for chk in checks:
                for fmt in chk.get("formats", ()):
                    if fmt in out:
                        out[fmt].setdefault(sc, []).append(chk["id"])
    except SystemExit:
        raise
    except Exception as exc:                      # pragma: no cover - corroborating only
        print(f"note: first-party checks unavailable ({exc.__class__.__name__}: {exc})",
              file=sys.stderr)
    return {f: {sc: sorted(set(ids)) for sc, ids in scs.items()} for f, scs in out.items()}


def load_fix_modes() -> dict[str, dict[str, set[str]]]:
    """{fmt: {sc: {fix_mode, ...}}} as CLAIMED by the catalog — used only to note where the
    catalog and the proven lane table disagree, which is ground rule 4's subject matter."""
    out: dict[str, dict[str, set[str]]] = {f: {} for f in FORMATS}
    catalog = json.loads(CATALOG.read_text())
    for fmt in FORMATS:
        for rule in catalog.get(fmt, []):
            out[fmt].setdefault(rule["wcag_sc"], set()).add(rule.get("fix_mode", "?"))
    return out


# catalog fix_mode -> the lane it implies, for the disagreement note only.
_CATALOG_LANE = {"auto": "auto", "ai-assisted": "assisted", "human-only": "human"}


def build() -> dict:
    cap = load_capability()
    review_fmts = load_review_formats()
    appliers = load_appliers()
    ai_pairs = load_ai_pairs()
    detectors = load_detectors()
    fix_modes = load_fix_modes()

    cells: dict[str, dict[str, dict]] = {}
    for sc in TRACKED_SCS:
        cells[sc] = {}
        for fmt in FORMATS:
            cell = cap.get(fmt, {}).get(sc)
            a_lane = cell["assessment"] if cell else None
            r_lane = cell["remediation"] if cell else None
            in_review_lane = fmt in review_fmts.get(sc, set())
            has_detectors = bool(detectors[fmt].get(sc))

            a_ceiling = A_CEILING[a_lane]
            r_ceiling = R_CEILING[r_lane]
            notes: list[str] = []

            # No remediation lane does NOT mean no assessment. A pair can sit in the review-only
            # scope table, or simply have a dispatched detector: either way ACP surfaces evidence
            # a human adjudicates, which is the Guided tier — it just can never certify a PASS,
            # so the ceiling stops at Q and never reaches C.
            if cell is None and (in_review_lane or has_detectors):
                a_ceiling = "Q"
                because = ("store.REVIEW_FORMATS admits this pair as a review lane"
                           if in_review_lane else
                           "a dispatched detector emits this SC for this format")
                notes.append(
                    f"no remediation lane, but {because} — ACP surfaces evidence it cannot "
                    f"certify, so assessment tops out at Guided and remediation at none")

            # Ground rule 2 — a model in the decision path caps remediation at AI-proposal.
            model_backed = (sc, fmt) in ai_pairs
            ai_in_path = model_backed and r_lane == "assisted"
            if model_backed and r_lane == "auto":
                r_ceiling = "AI"
                notes.append(
                    "proposals.py consults api/ai.py for this SC while the lane table calls it "
                    "auto — ground rule 2 caps a model-backed decision at AI-proposal")

            # The risky-direction check: an approved proposal that never reaches the file.
            has_applier = sc in appliers.get(fmt, set())
            if r_lane == "assisted" and not has_applier:
                r_ceiling = "M"
                notes.append(
                    "assisted lane with no write-back applier in handlers.py — approving in the "
                    "HITL queue does not change the file, so the honest ceiling is guided-manual")

            # Catalog vs proven lane, reported not resolved (ground rule 4).
            claimed = {_CATALOG_LANE.get(m, m) for m in fix_modes[fmt].get(sc, set())}
            if claimed and r_lane and r_lane not in claimed:
                notes.append(
                    f"config/rule-catalog.json calls this {'/'.join(sorted(claimed))} but the "
                    f"round-trip-proven lane is {r_lane}")

            # A detector emitting into a pair NO scope table admits. Unlike the review-lane case
            # above, nothing here is deliberate: _rule_outcome still surfaces a blocking finding
            # as FAIL (the no-silent-gaps hoist), but the pair can never PASS and carries no
            # declared lane, so the criterion's status is decided by an accident of wiring.
            # Reported as acp's bug to fix, not the matrix's — the ceiling already handles it.
            orphaned = cell is None and has_detectors and not in_review_lane
            if orphaned:
                notes.append(
                    f"{len(detectors[fmt][sc])} detector(s) emit {sc} for {fmt} "
                    f"({', '.join(detectors[fmt][sc])}) but neither remediation_capability.py "
                    f"nor store.REVIEW_FORMATS declares the pair — findings surface as FAIL yet "
                    f"the pair can never PASS. Undeclared coverage; the fix belongs in acp")

            evidence = []
            if cell:
                evidence.append(f"api/remediation_capability.py:REMEDIATION[{fmt!r}][{sc!r}]"
                                f" = {r_lane}")
            if detectors[fmt].get(sc):
                evidence.append("detectors: " + ", ".join(detectors[fmt][sc]))
            if r_lane == "assisted":
                evidence.append(f"write-back applier: {'yes' if has_applier else 'NO'} "
                                f"(api/handlers.py:_apply_approved_values)")
            if ai_in_path:
                evidence.append("model in decision path: api/proposals.py -> api/ai.py")

            cells[sc][fmt] = {
                "in_scope": cell is not None,
                "assessment_lane": a_lane,
                "remediation_lane": r_lane,
                "ceiling_a": a_ceiling,
                "ceiling_r": r_ceiling,
                "detectors": detectors[fmt].get(sc, []),
                "catalog_fix_modes": sorted(fix_modes[fmt].get(sc, set())),
                "applier": has_applier,
                "ai_in_path": ai_in_path,
                "orphaned_detectors": orphaned,
                "notes": notes,
                "evidence": evidence,
            }

    return {
        "schema": 1,
        "source": "acp",
        "formats": list(FORMATS),
        "a_tiers": list(A_TIERS),
        "r_tiers": list(R_TIERS),
        "cells": cells,
    }


def explain(data: dict) -> None:
    print(f"{'SC':<8}{'format':<7}{'assess':<8}{'remediate':<11}{'ceiling':<10}notes")
    print("-" * 100)
    for sc, fmts in data["cells"].items():
        for fmt, c in fmts.items():
            ceil = f"{c['ceiling_a']}/{c['ceiling_r']}"
            lanes = f"{c['assessment_lane'] or '-':<8}{c['remediation_lane'] or '-':<11}"
            note = c["notes"][0][:52] + "…" if c["notes"] else ""
            print(f"{sc:<8}{fmt:<7}{lanes}{ceil:<10}{note}")


def check() -> int:
    """Fail loudly when a source this generator reads has changed shape.

    Every loader already raises SystemExit on a moved structure; running them is the check.
    The extra assertion is that the SC list here still matches gen_progress_log's, so the two
    matrix-facing scripts cannot disagree about which rows exist.
    """
    build()
    gpl = _load("acp_gen_progress_log", ROOT / "scripts" / "gen_progress_log.py")
    if set(gpl.TRACKED_SCS) != set(TRACKED_SCS):
        only_here = sorted(set(TRACKED_SCS) - set(gpl.TRACKED_SCS))
        only_there = sorted(set(gpl.TRACKED_SCS) - set(TRACKED_SCS))
        print(f"TRACKED_SCS disagree with gen_progress_log.py — "
              f"only here: {only_here or 'none'}; only there: {only_there or 'none'}",
              file=sys.stderr)
        return 1
    print("gen_matrix_coverage: all sources readable, SC lists agree")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--explain", action="store_true", help="human-readable table")
    ap.add_argument("--check", action="store_true", help="fail if a source's shape moved")
    ap.add_argument("--sources", action="store_true",
                    help="print the repo paths a ceiling depends on, one per line")
    args = ap.parse_args()
    if args.sources:
        print("\n".join(SOURCES))
        return 0
    if args.check:
        return check()
    data = build()
    if args.explain:
        explain(data)
    else:
        json.dump(data, sys.stdout, indent=1)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
