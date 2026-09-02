"""Three registered detectors — now wired into office_structure.checks_for.

WHAT THIS TESTS. `api/formats/<fmt>/__init__.py` registers a detector for each (criterion,
format) pair it claims. For three pairs the detector is written and returns a real finding when
called, and `office_structure.checks_for` now invokes them via thin wrapper functions:

    docx 1.3.5   docx_input_purpose_checks   -> DOCX_INPUT_NO_PURPOSE
    pdf  1.3.5   pdf_input_purpose_checks     -> PDF_INPUT_NO_PURPOSE
    pdf  2.5.3   pdf_label_in_name_checks     -> PDF_LABEL_NOT_IN_NAME

These are HEURISTIC/LOW (1.3.5) and PARTIAL/HIGH (2.5.3) registrations. The 1.3.5 ones flag
personal-data field names — "organisational forms (company address, billing contact) will
false-positive" is the registration's own prediction. Callers should treat findings as advisory.

HOW THIS WAS FOUND. Not by reading: a static check of "is the registered detector reachable
from checks_for" flags ELEVEN of the 32 registrations, of which three are real — the registered
detector and the scan-path implementation are frequently different code emitting the same
criterion, so there is no sound static link between them. What found these was building a
document that should trip the criterion and running both lanes on it.

WHY RULE_REGISTRY.EVALUATE IS STILL NOT CALLED. The wiring adds direct wrapper functions to
checks_for (same pattern as pdf_form_field_checks, pdf_focus_order_checks, etc.) rather than
routing through rule_registry.evaluate. The registry's role remains declarations and metadata;
the scan-path wiring is explicit in checks_for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import office_structure as osx  # noqa: E402

pikepdf = pytest.importorskip("pikepdf")
docx_mod = pytest.importorskip("docx")

from formats.docx.detectors import input_purpose as docx_input_purpose  # noqa: E402
from formats.pdf.detectors import input_purpose as pdf_input_purpose  # noqa: E402
from formats.pdf.detectors import label_in_name as pdf_label_in_name  # noqa: E402


# ── the triggers, built from what each registration says it looks for ────────────

def _docx_personal_control(path: Path) -> None:
    """An interactive content control whose w:alias matches the personal-data vocabulary —
    exactly what the docx 1.3.5 registration describes as its trigger."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc = Document()
    doc.add_paragraph("Please complete the form below.")
    sdt = OxmlElement("w:sdt")
    pr = OxmlElement("w:sdtPr")
    alias = OxmlElement("w:alias")
    alias.set(qn("w:val"), "Home address")
    tag = OxmlElement("w:tag")
    tag.set(qn("w:val"), "addr")
    ddl = OxmlElement("w:dropDownList")
    for value in ("Yes", "No"):
        item = OxmlElement("w:listItem")
        item.set(qn("w:displayText"), value)
        item.set(qn("w:value"), value)
        ddl.append(item)
    for el in (alias, tag, ddl):
        pr.append(el)
    content = OxmlElement("w:sdtContent")
    para = OxmlElement("w:p")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Choose"
    run.append(text)
    para.append(run)
    content.append(para)
    sdt.append(pr)
    sdt.append(content)
    body = doc.element.body
    body.insert(len(body) - 1, sdt)
    doc.save(str(path))


def _blank_pdf():
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(400, 300))
    return pdf


def _pdf_personal_field(path: Path) -> None:
    """An AcroForm text field named with personal-data vocabulary — the pdf 1.3.5 trigger."""
    from pikepdf import Array, Dictionary, Name, String
    pdf = _blank_pdf()
    field = pdf.make_indirect(Dictionary(
        Type=Name.Annot, Subtype=Name.Widget, FT=Name.Tx,
        T=String("Home address"), TU=String("Home address"),
        Rect=Array([50, 200, 300, 230]), F=4))
    pdf.pages[0].Annots = Array([field])
    pdf.Root.AcroForm = Dictionary(Fields=Array([field]), DA=String("/Helv 0 Tf 0 g"))
    pdf.save(str(path))


def _pdf_mislabelled_button(path: Path) -> None:
    """A push button whose accessible name does not contain its visible caption — the pdf 2.5.3
    trigger. A speech-input user says what they SEE ("Submit payment") and the name it would have
    to match is something else entirely."""
    from pikepdf import Array, Dictionary, Name, String
    pdf = _blank_pdf()
    button = pdf.make_indirect(Dictionary(
        Type=Name.Annot, Subtype=Name.Widget, FT=Name.Btn,
        T=String("btn1"), TU=String("Continue to the next step"),
        MK=Dictionary(CA=String("Submit payment")),
        Rect=Array([50, 120, 260, 160]), F=4, Ff=65536))
    pdf.pages[0].Annots = Array([button])
    pdf.Root.AcroForm = Dictionary(Fields=Array([button]), DA=String("/Helv 0 Tf 0 g"))
    pdf.save(str(path))


ORPHANS = [
    ("docx 1.3.5", "1.3.5", ".docx", _docx_personal_control,
     lambda p: docx_input_purpose.detect(p), "DOCX_INPUT_NO_PURPOSE"),
    ("pdf 1.3.5", "1.3.5", ".pdf", _pdf_personal_field,
     lambda p: pdf_input_purpose.detect(p), "PDF_INPUT_NO_PURPOSE"),
    ("pdf 2.5.3", "2.5.3", ".pdf", _pdf_mislabelled_button,
     lambda p: pdf_label_in_name.detect(p), "PDF_LABEL_NOT_IN_NAME"),
]


def _scan_wcags(path: Path, ext: str) -> set[str]:
    return {(f.get("wcag") or "").split()[0] for f in osx.checks_for(path, ext) if f.get("wcag")}


# ── each detector works ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,sc,ext,build,detect,rule_id", ORPHANS,
                         ids=[o[0] for o in ORPHANS])
def test_the_detector_returns_a_finding_when_called_directly(
        tmp_path, label, sc, ext, build, detect, rule_id):
    """Half of the point. If the detector did not work, this would be an unfinished feature and
    not worth a test — the finding is specifically that WORKING code is disconnected."""
    path = tmp_path / f"{label.replace(' ', '-').replace('.', '')}{ext}"
    build(path)
    found = detect(path)
    assert found, (
        f"{label}: the registered detector reported nothing on a document built from its own "
        f"registration's description of its trigger — if the trigger is wrong, fix it here; if "
        f"the detector broke, this file's whole premise has changed")
    assert (found[0].get("wcag") or "").startswith(sc)
    assert found[0].get("ruleId") == rule_id


# ── and no scan runs it ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,sc,ext,build,detect,rule_id", ORPHANS,
                         ids=[o[0] for o in ORPHANS])
def test_a_real_scan_reports_the_criterion(
        tmp_path, label, sc, ext, build, detect, rule_id):
    """A document that trips a registered detector has that criterion reported by a real scan.

    Asserted on the SAME document the test above proves the detector fires on, so the two results
    cannot be explained by a bad fixture."""
    path = tmp_path / f"{label.replace(' ', '-').replace('.', '')}-scan{ext}"
    build(path)
    assert detect(path), "the trigger stopped working — see the test above"
    fired = _scan_wcags(path, ext)
    assert sc in fired, (
        f"{label}: the detector reports {sc} when called directly, but a real scan reported "
        f"{sorted(fired) or 'nothing'} — the registration is not connected to the scan path")


def test_nothing_in_the_scan_path_executes_the_registry():
    """Checks_for wires detectors explicitly, not via rule_registry.evaluate.

    `rule_registry.evaluate(rule, fmt, path)` is NOT called by scanner.py or office_structure.py.
    The three pairs above are wired by adding wrapper functions to checks_for directly (e.g.
    docx_input_purpose_checks), following the same pattern as pdf_form_field_checks. If evaluate
    ever appears here, re-derive whether explicit wrapper functions are still needed.

    Scoped to the two modules that make up the scan path rather than the whole tree, because the
    generators and tests legitimately call it."""
    for name in ("scanner.py", "office_structure.py"):
        src = (ROOT / "api" / name).read_text()
        assert "rule_registry.evaluate" not in src and "_r.evaluate" not in src, (
            f"api/{name} now calls rule_registry.evaluate — registered detectors may finally be "
            f"running, so re-derive whether the three pairs above are still orphaned")


def test_the_ceiling_generator_still_claims_these_cells():
    """Deliberately NOT a failure — the point is that the claim and the behaviour disagree.

    gen_matrix_coverage derives each cell's ceiling from the registry, so all three read as
    assessable. Pinning it here means that if someone resolves this by DOWNGRADING the ceiling
    rather than by wiring the detector, that shows up as this test failing and gets a sentence
    written about which of the two was chosen."""
    import rule_registry as reg
    reg.load()
    for _label, sc, ext, _b, _d, _r in ORPHANS:
        fmt = ext.lstrip(".")
        assert reg.is_registered(sc, fmt), (
            f"({sc}, {fmt}) is no longer registered — if the registration was removed to stop the "
            f"ceiling over-claiming, say so here and delete this file's entry for it")
