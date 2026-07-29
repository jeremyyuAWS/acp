"""Contract: a criterion may only be CREDITED on a format that can actually DETECT it.

The write-back lane (handlers._apply_one_value_kind) grants credit by re-scanning the written
bytes and finding the criterion gone. That gate is only evidence if something emits the
criterion for that format in the first place: where nothing does, the criterion is missing from
every re-scan there will ever be, the gate passes vacuously, and the file is certified against a
criterion nobody ever checked. It fails silently and in the risky direction — the file looks
MORE conformant than it is — so it is asserted here rather than left to review.

This is a general trap, not a property of any one lane: it is available to every future
`scs_to_clear=` that names a criterion the format has no detector for. Both sides are derived
from code (scripts/gen_matrix_coverage.py's own loaders, the same ones the WCAG matrix's drift
check consumes), so a new lane or a moved detector is covered without editing this file.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _link_scs_by_ext() -> dict[str, tuple[str, ...]]:
    """handlers._LINK_SCS_BY_EXT, parsed rather than imported — importing handlers drags in the
    scheduler and the database driver, which a unit test has no business needing."""
    tree = ast.parse((ACP / "api" / "handlers.py").read_text())
    for node in tree.body:
        if (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None)
                == "_LINK_SCS_BY_EXT" and isinstance(node.value, ast.Dict)):
            return {k.value: tuple(e.value for e in v.elts)
                    for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError("handlers._LINK_SCS_BY_EXT is no longer a module-level dict literal — "
                         "the link-text lane's per-format scope moved; update this test.")


@pytest.fixture(scope="module")
def gen():
    return _load("acp_gen_matrix_coverage", ACP / "scripts" / "gen_matrix_coverage.py")


def test_no_applier_credits_a_criterion_no_detector_emits_for_that_format(gen):
    """Every (format, SC) the write-back lane clears must have a detector emitting it there.

    Detectors = the partner engine catalog + the first-party Python checks (load_detectors),
    i.e. everything the re-scan can possibly report.
    """
    detectors = gen.load_detectors()
    offenders = [
        f"{fmt} {sc}: applier clears it, no detector emits it"
        for fmt, scs in gen.load_appliers().items()
        for sc in sorted(scs)
        if not detectors.get(fmt, {}).get(sc)
    ]
    assert not offenders, (
        "vacuous credit — the re-scan cannot observe these criteria, so clearing them proves "
        "nothing:\n" + "\n".join(offenders))


def test_nothing_is_credited_beyond_what_the_re_scan_verifies(gen):
    """`credit_rule_ids` must never outrun `scs_to_clear` on the same call.

    The two are separate arguments, so a lane can verify one criterion and credit two. Whatever
    is credited beyond the verified set is credited on no evidence at all.
    """
    verified = gen.load_appliers()
    credited = gen.load_appliers(keyword="credit_rule_ids")
    offenders = [f"{fmt}: credits {sorted(scs - verified.get(fmt, set()))} without verifying it"
                 for fmt, scs in credited.items() if scs - verified.get(fmt, set())]
    assert not offenders, "credited but never verified:\n" + "\n".join(offenders)


def test_link_text_lane_is_verifiable_without_the_partner_engine():
    """The Office link-text lane must clear only criteria a FIRST-PARTY check emits.

    Stricter than the catalog-wide check above, and deliberately so: the proposals this lane
    approves are first-party (proposals.propose_link_texts), and the re-scan that credits them
    (proposals.verify_residual_scs) runs in-process. Resting the credit on a catalog rule from
    the partner .NET analyser would make certification depend on that analyser being reachable
    and enabled at verify time — when it is not, the criterion vanishes from the re-scan and the
    gate is vacuous again, which is exactly the failure this file exists to prevent.
    """
    link_scs = _link_scs_by_ext()
    gri = _load("acp_gen_rules_index", ACP / "scripts" / "gen_rules_index.py")
    first_party = gri.load_first_party()
    offenders = []
    for fmt, scs in link_scs.items():
        for sc in scs:
            if not any(fmt in chk.get("formats", ()) for chk in first_party.get(sc, [])):
                offenders.append(f"{fmt} {sc}: no first-party check emits it")
    assert not offenders, (
        "the link-text lane would depend on the partner engine to verify its own fix:\n"
        + "\n".join(offenders))
