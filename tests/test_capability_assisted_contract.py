"""Contract test: every (pptx, pdf) ASSISTED lane is PROVEN by a round-trip fixture.

Scope: pptx and pdf only — the capability-audit scope. docx/xlsx/html ASSISTED chains
are tracked separately (task #175); their fixtures are read here too, but only pptx/pdf
lanes are held to the contract.

A lane is ASSISTED in name only if clicking "Apply" on its review card does nothing. The
chain can break at any of seven steps:
  1. Detector emits a reproducible finding.
  2. Proposer emits a card with a stable writable locator.
  3. Approval is stored.
  4. has_approved_values_to_write returns True (a getter reads this rule_id).
  5. apply_approved_values / apply_pdf_approved dispatches a real applier.
  6. The changed copy is uploaded and re-scanned.
  7. The targeted finding clears on re-scan.

THE REGISTRY IS DERIVED, NOT WRITTEN. This file used to hold a hand-maintained frozenset of
pairs "verified by tracing". Tracing is reading, and reading is how pptx 1.4.5 sat in that
set for months while its verify gate refused every approval (#1665): steps 1–6 were wired
and step 7 could never happen, and nothing ran the chain to find out. The set below is
collected from the tests that DO run it — tests/test_remediation_verified_*.py, each of
which drives handlers._apply_approved_values with the re-scan unpatched and asserts the row
was credited. A module declares what it proves:

    PROVES_LANES = {("pptx", "1.1.1")}

and the contract admits the declaration only if the module visibly runs the production
seam (calls handlers._apply_approved_values, asserts count_unapplied_approved_values, and
never stubs _verify_residual). Adding an ASSISTED lane for pptx or pdf therefore means
writing its round-trip fixture first — there is no list to append to.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from api.remediation_capability import ASSISTED, HUMAN, REMEDIATION

ACP = Path(__file__).resolve().parent.parent
TESTS = ACP / "tests"
FIXTURE_GLOB = "test_remediation_verified_*.py"
DECLARATION = "PROVES_LANES"

SCOPED_FORMATS = frozenset({"pptx", "pdf"})
_SC = re.compile(r"^\d+\.\d+\.\d+$")


def _declared(path: Path) -> set[tuple[str, str]]:
    """The (fmt, sc) pairs `path` declares in PROVES_LANES; empty when it declares nothing.

    A declaration must be a LITERAL set of (str, str) tuples — ast.literal_eval, never import:
    these modules importorskip heavy libraries and open the scanner at collection time.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == DECLARATION for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError as e:
                raise AssertionError(
                    f"{path.name}: {DECLARATION} must be a literal set of (fmt, sc) tuples "
                    f"so it can be read without importing the module: {e}") from e
            pairs = set(value)
            bad = [p for p in pairs if not (isinstance(p, tuple) and len(p) == 2
                                              and p[0] in REMEDIATION and _SC.match(p[1]))]
            assert not bad, f"{path.name}: malformed {DECLARATION} entries: {bad}"
            return pairs
    return set()


def _runs_the_production_seam(path: Path) -> list[str]:
    """Why a declaring module is (or is not) believed. Returns the list of missing evidence.

    The declaration is a claim; these are the three things a round-trip fixture in this repo
    always does and a unit test of a writer never does. A module that declares a lane without
    them is a registry entry by another name.
    """
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))
    nodes = list(ast.walk(tree))
    calls_handler = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_apply_approved_values" for n in nodes)
    asserts_credit = "count_unapplied_approved_values" in src
    # Structural, not a substring: a docstring SAYING "with _verify_residual_scs unpatched" is
    # the opposite of a stub. A stub is monkeypatch.setattr(handlers, "_verify_residual…", ...)
    # — the name as a whole string constant — or an assignment through the attribute. Both
    # seam names (`_verify_residual` and `_verify_residual_scs`) are stubbed elsewhere in
    # tests/, so the prefix is what is checked.
    def _is_seam(name) -> bool:
        return isinstance(name, str) and name.startswith("_verify_residual")
    stubs_rescan = any(
        (isinstance(n, ast.Constant) and _is_seam(n.value))
        or (isinstance(n, ast.Attribute) and _is_seam(n.attr))
        for n in nodes)
    missing = []
    if not calls_handler:
        missing.append("never calls handlers._apply_approved_values (the production seam)")
    if not asserts_credit:
        missing.append("never asserts store.count_unapplied_approved_values (the credit)")
    if stubs_rescan:
        missing.append("references _verify_residual — a stubbed re-scan proves nothing")
    return missing


def proven_lanes() -> dict[tuple[str, str], str]:
    """{(fmt, sc): fixture filename} for every lane a round-trip fixture proves."""
    out: dict[tuple[str, str], str] = {}
    for path in sorted(TESTS.glob(FIXTURE_GLOB)):
        pairs = _declared(path)
        if not pairs:
            continue
        missing = _runs_the_production_seam(path)
        assert not missing, (
            f"{path.name} declares {sorted(pairs)} but is not a round-trip fixture:\n  "
            + "\n  ".join(missing))
        src = path.read_text()
        for fmt, sc in pairs:
            assert f'"{sc}"' in src or f"'{sc}'" in src, (
                f"{path.name} declares ({fmt!r}, {sc!r}) but never mentions {sc!r}")
            assert fmt in src, f"{path.name} declares ({fmt!r}, {sc!r}) but never mentions {fmt!r}"
            assert (fmt, sc) not in out, (
                f"({fmt!r}, {sc!r}) is declared by both {out[(fmt, sc)]} and {path.name}")
            out[(fmt, sc)] = path.name
    return out


def test_round_trip_fixtures_exist_and_declare_lanes():
    """The derivation has a source. An empty set here would make the contract below vacuous,
    so the fixture family and its declarations are asserted to exist before anything is
    derived from them."""
    files = sorted(TESTS.glob(FIXTURE_GLOB))
    assert files, f"no {FIXTURE_GLOB} under tests/ — the registry has nothing to derive from"
    silent = [p.name for p in files if not _declared(p)]
    assert not silent, (
        f"round-trip fixtures with no {DECLARATION} declaration (say what they prove):\n  "
        + "\n  ".join(silent))


def test_every_pptx_pdf_assisted_lane_is_proven_by_a_round_trip_fixture():
    """Every ASSISTED lane for pptx/pdf must be declared by a fixture that runs the chain.

    Fails on any lane that claims ASSISTED without a round-trip proof. The fix is never to
    edit this file: write tests/test_remediation_verified_<fmt>_<lane>.py, or downgrade the
    lane to HUMAN.
    """
    proven = proven_lanes()
    missing = []
    for fmt in sorted(SCOPED_FORMATS):
        for sc, lane in REMEDIATION.get(fmt, {}).items():
            if lane == ASSISTED and (fmt, sc) not in proven:
                missing.append((fmt, sc))
    assert not missing, (
        "ASSISTED lanes with no round-trip fixture — write one (see tests/"
        "test_remediation_verified_*.py) or downgrade the lane to HUMAN:\n"
        + "\n".join(f"  ({fmt!r}, {sc!r})" for fmt, sc in sorted(missing))
    )


def test_no_proven_pptx_pdf_lane_is_human():
    """A round-trip fixture that proves a lane the table calls HUMAN is a contradiction: either
    the fixture is wrong about what it proves, or the table is understating the product.
    AUTO is fine — an approved-value round trip on a lane that also has a deterministic fixer
    (pdf 4.1.2) proves more, not less."""
    contradictions = [
        (fmt, sc, name) for (fmt, sc), name in proven_lanes().items()
        if fmt in SCOPED_FORMATS and REMEDIATION.get(fmt, {}).get(sc) == HUMAN
    ]
    assert not contradictions, (
        "Lanes proven end-to-end by a fixture but marked HUMAN in REMEDIATION:\n"
        + "\n".join(f"  ({fmt!r}, {sc!r}) — {name}" for fmt, sc, name in sorted(contradictions))
    )


def test_a_declaration_without_a_round_trip_is_refused():
    """The bite check, on the mechanism itself: a file that declares a lane but only unit-tests
    a writer (no handler call, no credit assertion) must be rejected, or the derivation is a
    hand-written registry with extra steps."""
    fake = TESTS / "test_remediation_verified_zz_fake.py"
    assert not fake.exists(), "leftover fake fixture; delete it"
    try:
        fake.write_text(
            '"""Looks like a proof, is a writer unit test."""\n'
            'PROVES_LANES = {("pptx", "9.9.9")}\n'
            "def test_writer():\n"
            "    from apply_pptx_slide_titles import apply_pptx_slide_titles\n"
            "    assert apply_pptx_slide_titles(b'', {}) == (b'', [], [])\n"
        )
        try:
            proven_lanes()
        except AssertionError as e:
            assert "_apply_approved_values" in str(e) and "count_unapplied" in str(e)
        else:
            raise AssertionError("a declaration with no round trip was admitted")
    finally:
        fake.unlink(missing_ok=True)


def test_the_verified_list_in_gen_capability_levels_matches_the_fixtures():
    """scripts/gen_capability_levels.REMEDIATION_VERIFIED is the same fact, hand-written as
    prose citations for the coverage report. Two sources for one fact drift — that dict was
    the corroboration that ("pptx", "2.4.6") had no proof while the old registry said it did.
    Read by AST (importing the script runs its argparse), keyed (sc, fmt) there, (fmt, sc) here.
    """
    tree = ast.parse((ACP / "scripts" / "gen_capability_levels.py").read_text())
    node = next((n.value for n in tree.body if isinstance(n, ast.AnnAssign)
                 and isinstance(n.target, ast.Name) and n.target.id == "REMEDIATION_VERIFIED"), None)
    assert node is not None, "REMEDIATION_VERIFIED not found in gen_capability_levels.py"
    cited = {(fmt, sc) for (sc, fmt) in ast.literal_eval(node)}
    proven = set(proven_lanes())
    assert cited == proven, (
        "gen_capability_levels.REMEDIATION_VERIFIED and the PROVES_LANES declarations disagree:\n"
        f"  cited but not proven by any fixture: {sorted(cited - proven)}\n"
        f"  proven by a fixture but not cited:   {sorted(proven - cited)}")
