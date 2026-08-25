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

The two axes are derived SEPARATELY, and the separation is load-bearing. Assessment asks what
the detector examines; remediation asks whether the fixer writes. Neither answers the other's
question, so no assessment-side source (the capability registry's `coverage`, a review-lane
entry, detector presence) may set a remediation ceiling, and a pair the lane table does not
mention gets a null remediation ceiling — unknown, not "none". `_remediation_ceiling` carries
the full account; pdf 4.1.2 is the case that made the coupling visible.

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
    "1.1.1", "1.3.1", "1.3.2", "1.3.3", "1.3.5", "1.4.1", "1.4.3", "1.4.4", "1.4.5",
    "1.4.10", "1.4.11", "1.4.12", "2.1.1", "2.1.2", "2.4.2", "2.4.3", "2.4.4",
    "2.4.6", "2.5.3", "3.1.1", "3.1.2", "4.1.2",
)

# Matrix vocabulary (index.html's AL/RL maps). Ordered weakest -> strongest claim; the
# consumer compares ranks, so this ordering IS the contract.
A_TIERS = ("NA", "H", "Q", "C")          # Not applicable < Human < Guided < Certified
R_TIERS = ("NA", "N", "M", "AI", "AP", "AC", "A")

# Every repo path a ceiling is computed from. Declared here, beside the loaders that read them,
# so the notify workflow can ask "did this push touch anything that could move a ceiling?"
# without keeping a second copy of the list in YAML that would drift from this one.
SOURCES = (
    "api/rule_registry.py",            # the capability registry — authoritative where migrated
    "api/capabilities.py",             # what each format can physically expose
    "api/assessment.py",               # the coverage vocabulary the ceilings map from
    "api/formats/",                    # per-format registrations + detectors
    "api/remediation_capability.py",   # the proven lane table (primary)
    "api/assessment_policy.py",        # REVIEW_FORMATS — the second, review-only scope table
    "api/handlers.py",                 # write-back applier surface
    "api/proposals.py",                # model-backed proposers
    "config/rule-catalog.json",        # detector inventory + claimed fix_mode
    "api/office_structure.py",         # first-party checks, via gen_rules_index
    "api/textchecks.py",
    "api/ocr.py",
    "scripts/gen_matrix_coverage.py",  # a change to the derivation itself moves ceilings too
    "scripts/gen_rules_index.py",
)

_SC_RE = re.compile(r"\d+\.\d+\.\d+")

# lane -> the strongest matrix tier that lane can honestly support.
# A missing lane (ACP does not evaluate this pair) is NOT "not applicable": the criterion may
# still apply to the format in WCAG terms, ACP simply automates nothing for it. So the assessment
# ceiling is "a human does it", which lets the matrix say H/NA but never C/Q.
A_CEILING = {"auto": "C", "review": "Q", "human": "H", None: "H"}
# The REMEDIATION map has no `None` entry ON PURPOSE — see `_remediation_ceiling` below. The two
# axes answer different questions, and a missing remediation lane is a fact about the lane table,
# never something an assessment-side source is entitled to answer on its behalf.
R_CEILING = {"auto": "A", "assisted": "AI", "human": "M"}


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


# ── 1a. the capability registry (authoritative wherever a pair has been migrated) ─────
# Maps the registry's coverage vocabulary onto the matrix's assessment tiers. The rule is the
# same one assessment.CAN_CERTIFY_PASS encodes: only FULL coverage can certify a pass, so only
# FULL can reach Certified. A partial or heuristic technique genuinely runs and genuinely
# reports — that is Guided, not Human.
_COVERAGE_CEILING_A = {
    "full": "C",
    "partial": "Q",
    "heuristic": "Q",
    "declared": "H",       # applicable, nothing built — a human is the only route today
    "unsupported": "NA",   # the format cannot express it; not a gap, a fact
}


def load_registry() -> dict[tuple[str, str], dict]:
    """{(sc, fmt): {coverage, confidence, reason, detector}} for every migrated pair.

    Imported rather than parsed: the registry is the authoritative statement and importing it
    means this generator cannot misread its own source of truth. api/ goes on the path because
    the registry's modules import each other by bare name, the way the running app does.
    """
    # A plain import, NOT _load(). The format packages register themselves with
    # `from rule_registry import register`, which resolves to the canonical module — loading a
    # second copy under a private name here would mean the registrations land in one module
    # object while this function reads an empty `_REGISTRY` on another, and the failure is
    # silent (zero entries, no error, ceilings quietly falling back to the legacy tables).
    sys.path.insert(0, str(API))
    try:
        import rule_registry as reg
        reg.load()
    except Exception as exc:
        # The matrix must still be derivable when the format parsers aren't installed — this
        # script runs in a bare CI container. An unmigrated-looking registry degrades to the
        # legacy tables, which is exactly the pre-registry behaviour.
        print(f"note: capability registry unavailable ({exc.__class__.__name__}: {exc}) — "
              f"falling back to the legacy tables", file=sys.stderr)
        return {}
    return {(r.rule, r.fmt): {"coverage": r.coverage.value,
                              "confidence": r.confidence.value,
                              "reason": r.reason,
                              "detector": r.detector is not None}
            for r in reg.all_registrations()}


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
    tree = ast.parse((API / "assessment_policy.py").read_text())
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
def load_appliers(*, keyword: str = "scs_to_clear") -> dict[str, set[str]]:
    """{format: {SCs whose approved value is actually written back into the file}}.

    Read from handlers._apply_approved_values' calls to `_apply_one_value_kind`, which is the
    only path from an approved HITL row to bytes on disk. Each call names the SCs it clears
    (`scs_to_clear=`) and is gated on a module-level format constant; pairing the two gives the
    true applier surface. A proposal outside it is a no-op on approval no matter how confident
    the catalog is — see the module docstring.

    `keyword` selects which of the call's SC arguments to read. The default is what the lane
    VERIFIES on the re-scan; pass "credit_rule_ids" for what it CREDITS, which is how
    tests/test_applier_detector_parity.py asserts the second never outruns the first.

    `scs_to_clear` comes in two shapes, and both are read here. A LITERAL set is one lane for
    every format the call is gated to. A module-level PER-FORMAT map ({fmt: (sc, ...)}, as the
    link-text lane uses) says the lane clears different criteria per format — because a
    criterion no detector emits for a format can only be "cleared" vacuously on the re-scan, so
    it is not claimed there. Flattening that map to its union would hand the matrix exactly the
    over-claim this generator exists to catch.
    """
    src = (API / "handlers.py").read_text()
    tree = ast.parse(src)

    # Module-level format constants the gates are expressed with (dict of ext -> mime, or a
    # tuple of exts). Collected generically so renaming one doesn't silently drop a lane.
    consts: dict[str, set[str]] = {}
    # …and the per-format SC maps ({fmt: (sc, ...)}), which are also format constants.
    sc_maps: dict[str, dict[str, set[str]]] = {}

    def _exts(val) -> set[str] | None:
        """The format set a constant's VALUE denotes, or None when it isn't one.

        Recursive so a gate assembled from the others resolves too
        (`_APPLY_VALUE_EXTS = tuple(_OFFICE_ALT_MIME) + ("pdf",)`). A gate spelled out by hand
        instead would be a second list of formats to keep in step with the lanes; resolving the
        expression means the widest gate stays derived from the narrow ones.
        """
        if isinstance(val, ast.Dict):
            return {k.value for k in val.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)} or None
        if isinstance(val, (ast.Tuple, ast.List, ast.Set)):
            return {e.value for e in val.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)} or None
        if isinstance(val, ast.Name):
            return consts.get(val.id)
        if (isinstance(val, ast.Call) and getattr(val.func, "id", None) in
                ("tuple", "list", "set", "frozenset") and len(val.args) == 1):
            # `_OFFICE_LINK_EXTS = tuple(_LINK_SCS_BY_EXT)` — the gate derived from the map's
            # own keys, so the two can never disagree. Resolve it rather than dropping the gate.
            return _exts(val.args[0])
        if isinstance(val, ast.BinOp) and isinstance(val.op, ast.Add):
            left, right = _exts(val.left), _exts(val.right)
            if left is not None and right is not None:
                return left | right
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
            continue
        name, val = node.targets[0].id, node.value
        resolved = _exts(val)
        if resolved and resolved & set(FORMATS):
            consts[name] = resolved
        # …and the per-format SC maps ({fmt: (sc, ...)}) among them.
        if isinstance(val, ast.Dict) and name in consts:
            per_fmt = {k.value: {e.value for e in v.elts if isinstance(e, ast.Constant)}
                       for k, v in zip(val.keys, val.values)
                       if isinstance(k, ast.Constant) and isinstance(v, (ast.Tuple, ast.List, ast.Set))}
            if per_fmt and all(all(_SC_RE.fullmatch(str(s)) for s in scs)
                               for scs in per_fmt.values()):
                sc_maps[name] = per_fmt

    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "_apply_approved_values"), None)
    if fn is None:
        raise SystemExit("gen_matrix_coverage: handlers._apply_approved_values not found — "
                         "the write-back path moved; update this generator.")

    # The function's own guard names the formats that reach ANY applier; a call may narrow
    # further with its own gate (link text is Office-only within that set).
    #
    # The outer gate is the WIDEST format constant the function mentions, not the first one
    # ast.walk happens to reach. A per-lane gate is by construction a subset of the guard that
    # let the format in at all, so "widest" identifies the guard unambiguously — whereas walk
    # order is an accident of expression nesting, and reading a narrow lane's gate as the outer
    # one silently drops every other format's lane from the matrix.
    gate_names = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id in consts]
    if not gate_names:
        raise SystemExit("gen_matrix_coverage: no format gate found in "
                         "_apply_approved_values — update this generator.")
    outer_name = max(gate_names, key=lambda n: len(consts[n]))
    outer = consts[outer_name]
    inner_names = [n for n in gate_names if n != outer_name]

    out: dict[str, set[str]] = {f: set() for f in FORMATS}
    calls = 0
    for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
        fname = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        if fname != "_apply_one_value_kind":
            continue
        kw = {k.arg: k.value for k in call.keywords}
        scs_node = kw.get(keyword)
        per_fmt = _per_format_scs(scs_node, fn, sc_maps)
        if per_fmt is not None:
            calls += 1
            for f, fmt_scs in per_fmt.items():
                if f in outer and f in out:
                    out[f] |= fmt_scs
            continue
        if not isinstance(scs_node, (ast.Set, ast.List, ast.Tuple)):
            raise SystemExit(f"gen_matrix_coverage: _apply_one_value_kind called without a "
                             f"literal {keyword} or a per-format SC map — update this "
                             f"generator.")
        scs = {e.value for e in scs_node.elts if isinstance(e, ast.Constant)}
        calls += 1
        # Narrow to this call's own gate when it has one, else the function-wide gate.
        exts = outer
        for nm, allowed in consts.items():
            if nm in inner_names and _guards(call, fn, nm):
                exts = outer & allowed
        for f in exts & set(FORMATS):
            out[f] |= scs
    if not calls:
        raise SystemExit("gen_matrix_coverage: no _apply_one_value_kind calls found — "
                         "update this generator.")
    return out


def _per_format_scs(scs_node, fn: ast.FunctionDef,
                    sc_maps: dict[str, dict[str, set[str]]]) -> dict[str, set[str]] | None:
    """{fmt: {sc, ...}} when this call's SC argument resolves to a per-format SC map, else None.

    The map is rarely named at the call site — the lane reads it into a local first
    (`link_scs = _LINK_SCS_BY_EXT.get(ext, ())` … `scs_to_clear=set(link_scs)`), so follow one
    hop through the local's assignment, the same cheap structural question `_guards` asks.
    """
    if scs_node is None:
        return None
    names = {n.id for n in ast.walk(scs_node) if isinstance(n, ast.Name)}
    for local in list(names):
        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.Assign) and any(
                    getattr(t, "id", None) == local for t in stmt.targets):
                names |= {n.id for n in ast.walk(stmt.value) if isinstance(n, ast.Name)}
    hits = [sc_maps[n] for n in sorted(names) if n in sc_maps]
    if not hits:
        return None
    merged: dict[str, set[str]] = {}
    for m in hits:
        for fmt, scs in m.items():
            merged.setdefault(fmt, set()).update(scs)
    return merged


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


def _remediation_ceiling(r_lane: str | None, *, has_applier: bool,
                         covered: bool) -> tuple[str | None, list[str], bool]:
    """The remediation ceiling for a cell, derived ONLY from remediation-axis evidence.

    Returns `(ceiling, notes, is_gap)`. The ceiling is None when no lane is declared, and that
    is the whole point of this function existing.

    The axes are independent, and this is the one place that was quietly pretending otherwise.
    `R_CEILING[None] = "N"` used to turn "the lane table does not mention this pair" into R1
    "No Remediation" — a positive, confident claim that nothing remediates it. Nothing in the
    code proved that. Worse, the claim was reached via the ASSESSMENT axis: a pair migrated to
    the capability registry got an assessment ceiling from its `coverage` value, that same
    registry entry suppressed the undeclared-coverage warning below, and the remediation axis
    was left holding a default nobody had to defend. pdf 4.1.2 is the case that exposed it — a
    registry entry reading `coverage=partial` (a statement about which parts of the criterion
    the DETECTOR examines) capped a fixer that demonstrably writes /TU at "No Remediation", and
    the matrix's drift guard duly reported the matrix for over-claiming. It was not.

    So: no lane, no ceiling. A null ceiling means "the code makes no claim here" — the drift
    consumer skips a null rather than ranking against it (check_grid_drift.find_drift), so a
    gap can no longer masquerade as a proven upper bound. The gap travels as a loud note and
    the `is_gap` flag instead, which is what a gap actually is.

    `is_gap` is narrower than "the lane is missing", because those are not the same thing and
    conflating them just moves the dishonesty into the reporting. A missing lane is only a GAP
    where ACP touches the pair at all — `covered` (a detector emits it, a review lane admits
    it, or the registry declares it) or `has_applier` (handlers.py writes an approved value for
    it). Where nothing in the code mentions the pair on either axis, the lane table is not
    incomplete; ACP has simply never claimed the pair, and shouting about all 13 of those would
    bury the 21 that need someone to act. The ceiling stays null in both cases — silence is
    still not proof — but only one of them is a defect.

    Applier presence gets the sharpest wording because it is the strongest evidence available
    that a null is right and R1 was wrong: `handlers._apply_approved_values` writing this pair
    back into the file is remediation-axis proof that SOMETHING remediates it, whatever the
    lane table forgot to say. That was pdf 4.1.2's exact shape.
    """
    if r_lane is not None:
        return R_CEILING[r_lane], [], False
    if not (has_applier or covered):
        return None, ["no remediation lane, and nothing in the code detects or remediates this "
                      "pair on either axis — ACP makes no claim here, so the remediation "
                      "ceiling is unknown rather than 'none'"], False
    why = ("api/handlers.py wires a write-back applier for this pair, so the code demonstrably "
           "remediates it" if has_applier else
           "ACP assesses this pair (a detector emits it, a review lane admits it, or the "
           "registry declares it)")
    return None, [
        f"NO REMEDIATION LANE: api/remediation_capability.py:REMEDIATION declares nothing for "
        f"this pair, and {why}. The remediation ceiling is therefore unknown, NOT 'none' — "
        f"deriving one from the assessment axis (registry coverage, detector presence) is a "
        f"cross-axis inference this generator refuses to make. Close the gap by adding the lane "
        f"with a round-trip proof in tests/test_remediation_capability.py"], True


def build() -> dict:
    cap = load_capability()
    registry = load_registry()
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
            has_applier = sc in appliers.get(fmt, set())
            reg = registry.get((sc, fmt))

            a_ceiling = A_CEILING[a_lane]
            r_ceiling, notes, r_gap = _remediation_ceiling(
                r_lane, has_applier=has_applier,
                covered=has_detectors or in_review_lane or reg is not None)

            # No remediation lane does NOT mean no assessment. A pair can sit in the review-only
            # scope table, or simply have a dispatched detector: either way ACP surfaces evidence
            # a human adjudicates, which is the Guided tier — it just can never certify a PASS,
            # so the ceiling stops at Q and never reaches C. Note the traffic is one-way: this
            # block reads remediation-axis facts to bound the ASSESSMENT ceiling, and says
            # nothing about the remediation ceiling, which `_remediation_ceiling` already
            # settled from remediation-axis evidence alone.
            # The registry outranks every heuristic below it: where a pair has been migrated,
            # its coverage is an explicit, tested statement of how much the technique reaches,
            # rather than something inferred from which table happens to mention the pair.
            if reg is not None:
                a_ceiling = _COVERAGE_CEILING_A.get(reg["coverage"], "H")
                notes.append(
                    f"capability registry: coverage={reg['coverage']}, "
                    f"confidence={reg['confidence']} — {reg['reason'] or 'no reason recorded'}")
            elif cell is None and (in_review_lane or has_detectors):
                a_ceiling = "Q"
                because = ("store.REVIEW_FORMATS admits this pair as a review lane"
                           if in_review_lane else
                           "a dispatched detector emits this SC for this format")
                notes.append(
                    f"no remediation lane, but {because} — ACP surfaces evidence it cannot "
                    f"certify, so assessment tops out at Guided")

            # Ground rule 2 — a model in the decision path caps remediation at AI-proposal.
            model_backed = (sc, fmt) in ai_pairs
            ai_in_path = model_backed and r_lane == "assisted"
            if model_backed and r_lane == "auto":
                r_ceiling = "AI"
                notes.append(
                    "proposals.py consults api/ai.py for this SC while the lane table calls it "
                    "auto — ground rule 2 caps a model-backed decision at AI-proposal")

            # The risky-direction check: an approved proposal that never reaches the file.
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
            # A registered pair is by definition declared, so it can never be orphaned — that
            # is what migrating it to the registry accomplished.
            orphaned = (cell is None and has_detectors and not in_review_lane
                        and reg is None)
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
            # Applier presence is remediation-axis evidence whenever it could change the reading:
            # for an assisted lane it decides AI vs guided-manual, and for a MISSING lane it is
            # the proof that "no lane" must not be read as "nothing remediates this".
            if r_lane == "assisted" or r_lane is None:
                evidence.append(f"write-back applier: {'yes' if has_applier else 'NO'} "
                                f"(api/handlers.py:_apply_approved_values)")
            if ai_in_path:
                evidence.append("model in decision path: api/proposals.py -> api/ai.py")

            cells[sc][fmt] = {
                "in_scope": cell is not None,
                "assessment_lane": a_lane,
                "remediation_lane": r_lane,
                "ceiling_a": a_ceiling,
                # null when no lane is declared: unknown, not "none". See _remediation_ceiling.
                "ceiling_r": r_ceiling,
                # Two different statements, deliberately both kept: the lane is absent, and
                # that absence is a defect someone should close (as opposed to a pair ACP has
                # simply never claimed on either axis).
                "remediation_lane_missing": r_lane is None,
                "remediation_gap": r_gap,
                "detectors": detectors[fmt].get(sc, []),
                "catalog_fix_modes": sorted(fix_modes[fmt].get(sc, set())),
                "applier": has_applier,
                "ai_in_path": ai_in_path,
                "orphaned_detectors": orphaned,
                # None when the pair hasn't been migrated yet. That is a different statement
                # from "unsupported", and the matrix renders the two differently.
                "registry_coverage": reg["coverage"] if reg else None,
                "registry_confidence": reg["confidence"] if reg else None,
                "notes": notes,
                "evidence": evidence,
            }

    # The support-maturity grid the matrix renders: {sc: {fmt: coverage}}, migrated pairs only.
    # An absent cell means "not migrated", NOT "unsupported" — conflating the two would turn
    # an incomplete migration into a false claim about what the format can do.
    maturity = {}
    for (sc, fmt), reg in sorted(registry.items()):
        maturity.setdefault(sc, {})[fmt] = {
            "coverage": reg["coverage"],
            "confidence": reg["confidence"],
            "reason": reg["reason"],
        }

    return {
        # 3: `ceiling_r` became nullable (no lane -> no claim, see _remediation_ceiling) and
        # cells gained `remediation_lane_missing`. The drift consumer already skips a null
        # ceiling, so this is additive for it; nothing else reads the version.
        "schema": 3,
        "source": "acp",
        "formats": list(FORMATS),
        "a_tiers": list(A_TIERS),
        "r_tiers": list(R_TIERS),
        "coverage_levels": ["unsupported", "declared", "heuristic", "partial", "full"],
        "maturity": maturity,
        "cells": cells,
    }


def explain(data: dict) -> None:
    print(f"{'SC':<8}{'format':<7}{'assess':<8}{'remediate':<11}{'ceiling':<10}notes")
    print("-" * 100)
    for sc, fmts in data["cells"].items():
        for fmt, c in fmts.items():
            # "?" is a null remediation ceiling — no lane declared, so no claim. It reads
            # differently from "N" on purpose: N asserts nothing remediates this, ? admits
            # the code has not said.
            ceil = f"{c['ceiling_a']}/{c['ceiling_r'] or '?'}"
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
