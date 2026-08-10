"""docx 2.4.4 and 3.1.2 are gated by the capability registry, verdict-for-verdict as before.

ADR 0031 asked for one certification mechanism, not two. Before this, docx 4.1.2/1.4.1/1.4.11/
2.1.2 reached REVIEW through the registry's coverage gate while 1.1.1/2.4.4/3.1.2 reached the SAME
REVIEW through the older `store.RULE_FORMATS` + `_certify` path — two mechanisms agreeing by
coincidence of values, which is the "disagreeing tables" hazard the registry exists to end.

This pins the migration of all three — 1.1.1, 2.4.4 and 3.1.2. 1.1.1 needed a capability the enum
did not carry (IMAGES, added in capabilities.py alongside this), which is why it moved last. The
load-bearing property is that it changed NO verdict: a clean docx still reviews, a defect still
fails. If a future edit makes the migration alter an outcome, this file fails rather than the
change shipping a silent reclassification on the most consequential path ACP has.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import assessment_policy as ap  # noqa: E402
import formats.docx  # noqa: E402,F401  (triggers the registrations)
import rule_registry as reg  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

MIGRATED = ["1.1.1", "2.4.4", "3.1.2"]


@pytest.mark.parametrize("sc", MIGRATED)
def test_pair_is_registry_backed_and_not_in_the_legacy_table(sc):
    """The mechanism moved: registry owns the scope, RULE_FORMATS no longer lists docx."""
    cov = reg.coverage_for(sc, "docx")
    assert cov is reg.Coverage.PARTIAL, f"{sc} docx should be registered PARTIAL, got {cov}"
    assert cov not in reg.CAN_CERTIFY_PASS, f"{sc} docx must not be able to certify a pass"
    assert "docx" not in ap.RULE_FORMATS.get(sc, frozenset()), (
        f"{sc} docx is in BOTH the registry and RULE_FORMATS — the double-declaration the "
        "migration removes; the drift check derives ground truth minus registry pairs")


@pytest.mark.parametrize("sc", MIGRATED)
def test_verdict_is_unchanged_by_the_migration(sc):
    """The whole point. Same outcome for every finding-state as the legacy path produced:
    clean -> REVIEW (assessed, not certified), a blocking finding -> FAIL, an advisory -> REVIEW."""
    assert ap._rule_outcome(sc, "docx", 0, 0, target="AA") == "REVIEW"
    assert ap._rule_outcome(sc, "docx", 1, 0, target="AA") == "FAIL"
    assert ap._rule_outcome(sc, "docx", 0, 1, target="AA") == "REVIEW"


def test_1_1_1_required_capability_is_in_the_docx_baseline():
    """1.1.1 required a substrate the enum did not carry. IMAGES was added for it, and a
    registration may only require a capability the format's baseline declares (test_rule_registry
    pins that generally); this states the specific reachability the migration depended on."""
    import capabilities
    assert reg.coverage_for("1.1.1", "docx") is reg.Coverage.PARTIAL
    assert capabilities.Capability.IMAGES in capabilities.BASELINE["docx"]


def _docx(tmp_path, body_xml, rels_xml=None):
    p = tmp_path / "d.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body_xml}</w:body></w:document>')
        if rels_xml:
            z.writestr("word/_rels/document.xml.rels", rels_xml)
    return p


def test_the_registered_detector_actually_fires_2_4_4(tmp_path):
    """A registered PARTIAL pair must have a detector that runs (test_rule_registry pins callable;
    this pins that it returns the criterion's finding, so evaluate() agrees with the scan)."""
    from formats.docx.detectors import link_purpose
    rels = (f'<Relationships xmlns="{R}/relationships"><Relationship Id="rId1" '
            f'Type="{R}/hyperlink" Target="https://x.org" TargetMode="External"/></Relationships>')
    doc = _docx(tmp_path, '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink></w:p>', rels)
    found = link_purpose.detect(doc)
    assert any(f["wcag"].startswith("2.4.4") for f in found), "the 2.4.4 detector found nothing"


def test_the_registered_detector_actually_fires_3_1_2(tmp_path):
    from formats.docx.detectors import language_parts
    en = "Please review the accessibility policy for the coming plan year before the deadline in March."
    fr = "Veuillez consulter la politique d accessibilite de notre etablissement avant le trente et un mars prochain."
    doc = _docx(tmp_path, f'<w:p><w:r><w:t>{en}</w:t></w:r></w:p><w:p><w:r><w:t>{fr}</w:t></w:r></w:p>')
    found = language_parts.detect(doc)
    assert any(f["wcag"].startswith("3.1.2") for f in found), "the 3.1.2 detector found nothing"


def test_the_registered_detector_actually_fires_1_1_1(tmp_path):
    from formats.docx.detectors import non_text_content
    WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    # an inline image whose wp:docPr carries no descr and no decorative marker -> 1.1.1
    body = (f'<w:p><w:r><w:drawing><wp:inline xmlns:wp="{WP}">'
            f'<wp:docPr id="1" name="Picture 1"/></wp:inline></w:drawing></w:r></w:p>')
    found = non_text_content.detect(_docx(tmp_path, body))
    assert any(f["wcag"].startswith("1.1.1") for f in found), "the 1.1.1 detector found nothing"
