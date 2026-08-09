"""2.1.2 No Keyboard Trap on .docx — declared, with the ceiling stated.

THE LAST CORE-17 CRITERION WITH NO .DOCX DECLARATION, and the one where the limit belongs to
documents rather than to ACP. Whether keyboard focus can move AWAY from a control is runtime
behaviour: it depends on the control's own implementation and on Word's handling, neither of
which is recorded in the file. No static read settles it, and better parsing would not help.

So the detector answers what it can — which interactive controls the document embeds — and hands
the list to a reviewer. That is a real contribution rather than a shrug: a 40-page consent pack
with two content controls tells someone exactly where to press Tab, instead of leaving them to
read the whole document looking for something to try.

WHY THE LANE IS `human` AND WILL STAY THAT WAY. 1.4.1 and 1.4.11 shipped as `human` earlier today
and were corrected to `assisted` within hours, because each turned out to have an exact remedy
hiding in the detected SIGNAL — restore the underline, use this shade. 2.1.2 has no such signal.
ACP cannot know a trap exists, cannot name which control traps, and could not verify a fix if one
were written. Anything prefilled would be a guess the re-scan could not check.

That distinction is the point of these tests: `human` here is a conclusion, not a placeholder.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import formats.docx  # noqa: E402,F401  — importing the package runs register()
import assessment_policy as pol  # noqa: E402
import remediation_capability as cap  # noqa: E402
from formats.docx.detectors import no_keyboard_trap  # noqa: E402


def _docx(tmp_path, *, with_control: bool) -> Path:
    import gen_demo_fixtures as gen
    from docx import Document
    d = Document()
    d.core_properties.title = "Consent"
    p = d.add_paragraph("I consent to the release of my records ")
    if with_control:
        gen._add_unlabeled_checkbox(p)
    out = tmp_path / ("controls.docx" if with_control else "static.docx")
    d.save(out)
    return out


# ── the declaration ───────────────────────────────────────────────────────────

def test_the_pair_is_registered():
    reg = pol._registry_for("2.1.2", "docx")
    assert reg is not None, "2.1.2 on docx has a shipping detector but no registry declaration"


def test_coverage_is_partial_and_the_reason_names_the_ceiling():
    """The reason must say what is NOT examined, and here that is the whole criterion's runtime
    half. A PARTIAL whose reason lists only what it does check reads as FULL to anyone scanning
    the matrix."""
    from assessment import Coverage
    reg = pol._registry_for("2.1.2", "docx")
    assert reg.coverage is Coverage.PARTIAL
    assert "not examined" in reg.reason
    assert "runtime behaviour" in reg.reason


def test_the_lane_is_human_and_that_is_a_conclusion():
    """Not a placeholder. 1.4.1 and 1.4.11 shipped `human` this morning and were corrected to
    `assisted` the same day once the exact remedy in their detected signal became clear. There is
    no equivalent here: no signal identifies WHICH control traps, so nothing can be prefilled and
    nothing written could be verified."""
    assert cap.REMEDIATION["docx"]["2.1.2"] == "human"


def test_it_can_never_certify_a_pass():
    """The clearest case in the registry. A document with no controls has nothing to trap focus
    in — the criterion never ARISES rather than being satisfied — and NOT_EVALUATED is the honest
    word for that. A signal reads REVIEW. Neither is ever PASS, and no future detector changes
    that, because the evidence does not exist statically."""
    assert pol._rule_outcome("2.1.2", "docx", 0, 1, "AA", None) == pol.REVIEW
    assert pol._rule_outcome("2.1.2", "docx", 0, 0, "AA", None) == pol.NOT_EVALUATED


# ── the detector ──────────────────────────────────────────────────────────────

def test_a_document_with_a_control_is_flagged_for_review(tmp_path):
    out = no_keyboard_trap.detect(_docx(tmp_path, with_control=True))
    assert len(out) == 1
    assert out[0]["ruleId"] == "OFFICE_INTERACTIVE_CONTROL_KEYBOARD"
    assert out[0]["severity"] == "REVIEW"


def test_the_finding_names_the_controls_and_admits_the_limit(tmp_path):
    """Both halves matter. Naming the controls is what makes the review actionable; admitting
    ACP cannot confirm it statically is what stops the finding being read as a detected trap."""
    detail = no_keyboard_trap.detect(_docx(tmp_path, with_control=True))[0]["detail"]
    assert "content control" in detail
    assert "keyboard focus" in detail
    assert "can't confirm this statically" in detail


def test_a_static_document_produces_nothing(tmp_path):
    """No controls, no finding — and so NOT_EVALUATED rather than a pass. A detector that spoke
    up here would put a review item on every Word document in an estate."""
    assert no_keyboard_trap.detect(_docx(tmp_path, with_control=False)) == []


def test_it_returns_only_its_own_criterion(tmp_path):
    """The shared implementation emits 4.1.2 findings too, and docx declares that criterion
    separately via name_role_value. Declaring one criterion must not smuggle in another's
    findings — they would be counted twice and credited to the wrong lane."""
    out = no_keyboard_trap.detect(_docx(tmp_path, with_control=True))
    assert all(str(f["wcag"]).startswith("2.1.2") for f in out), \
        f"leaked another criterion's findings: {[f['wcag'] for f in out]}"


def test_it_is_a_wrapper_over_the_shipping_implementation():
    """The risk in a declaration is that it drifts from the code it describes; a second copy of
    the control inventory is how that starts."""
    import inspect
    assert "office_control_review_checks" in inspect.getsource(no_keyboard_trap.detect)


# ── end to end ────────────────────────────────────────────────────────────────

def test_the_verdict_reaches_a_real_scan(tmp_path):
    """A registration is only worth having if the finding survives the whole path — detector,
    scan, split, outcome gate."""
    import shutil
    import tempfile

    import scanner
    src = _docx(tmp_path, with_control=True)
    work = Path(tempfile.mkdtemp())
    shutil.copy(src, work / src.name)
    res, _ = scanner.analyse_and_assess(work, src.name)
    issues = list((res or {}).get("issues") or [])
    fail, review = pol._split_sc_counts(issues)
    assert pol._rule_outcome("2.1.2", "docx", fail.get("2.1.2", 0), review.get("2.1.2", 0),
                             "AA", None) == pol.REVIEW
