"""1.4.1 and 1.4.11 on .docx: declared detectors, and a lane that carries the measurement.

WHAT WAS WRONG. Both detectors have shipped since ADR 0023 Phase 1b and their findings already
reached users through `office_structure.checks_for`. Neither pair was DECLARED: no registry
entry, so the capability matrix could not say what technique reached them, and no
`remediation_capability` lane, so the fix axis read "No Remediation" — an absence, when what
actually existed was work with nowhere to record it.

THE LANE IS `human`, NOT `assisted`, AND THAT IS THE LOAD-BEARING CHOICE. An assisted lane emits
a PREFILLED value a reviewer confirms with one click. Neither of these has a value to prefill:
the replacement for a colour-only cue is an editorial decision about how the document
communicates, and recolouring a shape outline changes its visual design. A tool that guessed
either would overwrite the author's intent with its own — and the re-scan could not tell, because
the finding clears whichever colour is written.

So the ceiling is guidance, and what makes it worth having is that the guidance carries the
MEASUREMENT: 1.4.11 states the ratio it measured and the 3:1 it needed; 1.4.1 states how many
links lost their underline. A reviewer decides without re-measuring.
"""
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import formats.docx  # noqa: E402,F401  — importing the package is what runs register()
import assessment_policy as pol  # noqa: E402
import remediation_capability as cap  # noqa: E402


# ── the declarations ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("sc", ["1.4.1", "1.4.11"])
def test_the_pair_is_registered(sc):
    reg = pol._registry_for(sc, "docx")
    assert reg is not None, f"{sc} on docx has a shipping detector but no registry declaration"
    assert reg.detector is not None


@pytest.mark.parametrize("sc", ["1.4.1", "1.4.11"])
def test_coverage_is_partial_not_full(sc):
    """FULL would assert we had looked at every way the criterion can fail. We have not: 1.4.1
    reads one signal (a link's removed underline) and 1.4.11 reads solid-outline-on-solid-fill
    shapes. Declaring FULL is how a matrix cell becomes a claim nobody checked."""
    from assessment import Coverage
    assert pol._registry_for(sc, "docx").coverage is Coverage.PARTIAL


@pytest.mark.parametrize("sc", ["1.4.1", "1.4.11"])
def test_the_reason_names_what_is_NOT_examined(sc):
    """A PARTIAL coverage whose reason only says what it does check is indistinguishable from
    FULL to anyone reading the matrix. The boundary is the point of the field."""
    reason = pol._registry_for(sc, "docx").reason
    assert "not examined" in reason, f"{sc}'s reason does not state its boundary: {reason!r}"


@pytest.mark.parametrize("sc", ["1.4.1", "1.4.11"])
def test_the_lane_is_human_not_assisted(sc):
    """The distinction this whole change turns on. `assisted` promises a prefilled value; there
    is none to prefill for either criterion, and promising one would be the overstatement the
    capability table exists to prevent."""
    assert cap.REMEDIATION["docx"][sc] == "human"


@pytest.mark.parametrize("sc", ["1.4.1", "1.4.11"])
def test_the_criterion_still_cannot_pass_on_docx(sc):
    """Declaring a detector must not turn into certifying conformance. Both are review-lane: a
    signal reads REVIEW, silence reads NOT_EVALUATED, and neither is ever PASS."""
    assert pol._rule_outcome(sc, "docx", 0, 1, "AA", None) == pol.REVIEW
    assert pol._rule_outcome(sc, "docx", 0, 0, "AA", None) != "PASS"


# ── the findings still fire, and carry their numbers ──────────────────────────

def _docx_with_underlineless_link(path: Path) -> Path:
    import gen_demo_fixtures as gen
    from docx import Document
    d = Document()
    d.core_properties.title = "Colour only"
    p = d.add_paragraph("Read the ")
    gen._add_hyperlink(p, "https://example.org/policy", "accessibility policy")
    d.save(path)
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].decode().replace(
        "<w:rPr/>", '<w:rPr><w:u w:val="none"/></w:rPr>').encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in parts.items():
            z.writestr(n, b)
    return path


def test_the_registered_141_detector_still_fires(tmp_path):
    """The registration must point at the working implementation, not a stub. A declaration whose
    detector finds nothing is worse than no declaration: the matrix gains a claim and the product
    loses none of its blind spot."""
    from formats.docx.detectors import use_of_color
    out = use_of_color.detect(_docx_with_underlineless_link(tmp_path / "c.docx"))
    assert [f["ruleId"] for f in out] == ["DOCX_COLOR_ONLY_LINK"]
    assert out[0]["severity"] == "REVIEW"


def test_the_141_finding_says_how_many_links(tmp_path):
    """Carrying the count is what makes a human lane useful rather than a shrug."""
    from formats.docx.detectors import use_of_color
    out = use_of_color.detect(_docx_with_underlineless_link(tmp_path / "c.docx"))
    assert re.search(r"\b1 hyperlink", out[0]["detail"])
    assert out[0].get("evidence", {}).get("value") == 1


def test_a_normal_document_is_silent(tmp_path):
    """A link that kept its underline is not a 1.4.1 finding. Without this the detector could
    fire on everything and every assertion above would still pass."""
    import gen_demo_fixtures as gen
    from docx import Document
    from formats.docx.detectors import use_of_color
    d = Document()
    d.core_properties.title = "Fine"
    p = d.add_paragraph("Read the ")
    gen._add_hyperlink(p, "https://example.org/policy", "accessibility policy")
    path = tmp_path / "ok.docx"
    d.save(path)
    assert use_of_color.detect(path) == []


def test_the_registered_1411_detector_is_the_shipping_one():
    """Wrapper, not a reimplementation — the risk in this change is a declaration drifting from
    the code it describes, and a second copy of the measurement is how that starts."""
    import inspect

    from formats.docx.detectors import nontext_contrast
    src = inspect.getsource(nontext_contrast.detect)
    assert "docx_nontext_contrast_checks" in src


def test_the_1411_finding_carries_the_ratio_and_the_target():
    """The measurement is the whole value of a human lane here: a reviewer should never have to
    re-measure a contrast ratio ACP already computed. Asserted on the detector's own contract
    rather than by authoring a shape, which python-docx cannot express."""
    import inspect

    import office_structure as osx
    src = inspect.getsource(osx.docx_nontext_contrast_checks)
    assert '"required": 3.0' in src, "the 3:1 target must travel with the finding"
    assert "needs 3:1" in src, "the detail must state the target a reviewer is judging against"
    assert '"metric": "Contrast"' in src
