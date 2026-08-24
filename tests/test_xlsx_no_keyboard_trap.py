"""2.1.2 No Keyboard Trap on .xlsx — declared, with the ceiling stated.

The detector is registered in api/formats/xlsx/__init__.py (not a separate detectors/ file,
because xlsx keeps all its registrations in one place — same rationale as 1.4.1 and 4.1.2
there). The function is _no_keyboard_trap; the tests access it via the registry and directly.

WHY THE LANE IS `human` AND WILL STAY THAT WAY. Whether keyboard focus can move away from an
embedded ActiveX/OLE control or form control depends on the control's own implementation and on
Excel's handling — neither is recorded in the OOXML file. No static read settles it. The detector
names the controls for a reviewer, but cannot confirm a trap exists or verify a fix.

That is identical to the docx and pptx reasoning, and it is a conclusion, not a placeholder.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import formats.xlsx  # noqa: E402,F401  — importing the package runs register()
import assessment_policy as pol  # noqa: E402
import remediation_capability as cap  # noqa: E402


def _xlsx(tmp_path: Path, *, with_control: bool) -> Path:
    parts: dict[str, str] = {"xl/worksheets/sheet1.xml": "<worksheet/>"}
    name = "controls.xlsx" if with_control else "static.xlsx"
    if with_control:
        parts["xl/ctrlProps/ctrlProp1.xml"] = "<formControlPr/>"
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for entry, data in parts.items():
            z.writestr(entry, data)
    return p


def _detect(path: Path) -> list[dict]:
    reg = pol._registry_for("2.1.2", "xlsx")
    assert reg is not None
    return reg.detector(path)


# ── the declaration ───────────────────────────────────────────────────────────

def test_the_pair_is_registered():
    reg = pol._registry_for("2.1.2", "xlsx")
    assert reg is not None, "2.1.2 on xlsx has a shipping detector but no registry declaration"


def test_coverage_is_partial_and_the_reason_names_the_ceiling():
    """The reason must say what is NOT examined — here, runtime behaviour."""
    from assessment import Coverage
    reg = pol._registry_for("2.1.2", "xlsx")
    assert reg.coverage is Coverage.PARTIAL
    assert "runtime behaviour" in reg.reason


def test_the_lane_is_human_and_that_is_a_conclusion():
    """xlsx 2.1.2 cannot be prefilled: no signal names which control traps focus."""
    assert cap.REMEDIATION["xlsx"]["2.1.2"] == "human"


def test_it_can_never_certify_a_pass():
    """Registry-backed PARTIAL coverage: the detector runs over the embedded-control subset and
    returns []. NEEDS_REVIEW_ON_CLEAN takes effect because PARTIAL means 'we checked what we can
    reach, not everything'. A clean file therefore reads REVIEW — 'nothing found in the subset
    we checked' — not NOT_EVALUATED (which means 'we did not look'). A finding reads REVIEW too
    (advisory). Neither is ever PASS, and no future detector changes that, because the evidence
    does not exist statically."""
    assert pol._rule_outcome("2.1.2", "xlsx", 0, 1, "AA", None) == pol.REVIEW
    assert pol._rule_outcome("2.1.2", "xlsx", 0, 0, "AA", None) == pol.REVIEW


# ── the detector ─────────────────────────────────────────────────────────────

def test_a_workbook_with_a_form_control_is_flagged_for_review(tmp_path):
    out = _detect(_xlsx(tmp_path, with_control=True))
    assert len(out) == 1
    assert out[0]["ruleId"] == "OFFICE_INTERACTIVE_CONTROL_KEYBOARD"
    assert out[0]["severity"] == "REVIEW"


def test_the_finding_names_the_controls_and_admits_the_limit(tmp_path):
    """Naming the control makes the review actionable; admitting the static limit is honest."""
    detail = _detect(_xlsx(tmp_path, with_control=True))[0]["detail"]
    assert "keyboard focus" in detail
    assert "can't confirm this statically" in detail


def test_a_static_workbook_produces_nothing(tmp_path):
    """No controls → no finding → NOT_EVALUATED, not a pass."""
    assert _detect(_xlsx(tmp_path, with_control=False)) == []


def test_it_returns_only_its_own_criterion(tmp_path):
    """office_control_review_checks emits BOTH 2.1.2 and 4.1.2; this lane must filter to 2.1.2."""
    out = _detect(_xlsx(tmp_path, with_control=True))
    assert all(str(f["wcag"]).startswith("2.1.2") for f in out), \
        f"leaked another criterion's findings: {[f['wcag'] for f in out]}"


def test_it_is_a_wrapper_over_the_shipping_implementation():
    """The risk in a declaration is that it drifts from the code it describes."""
    import inspect
    assert "office_control_review_checks" in inspect.getsource(formats.xlsx._no_keyboard_trap)
