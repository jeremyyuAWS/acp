"""Deterministic labelling of docx content-control form fields (WCAG 3.3.2).

form_labels reads the VISIBLE text adjacent to an unlabelled Word form field
(checkbox / date / dropdown / combo box / picture) and the remediator writes it
into the control's <w:alias>. These tests pin: the adjacent label is extracted
and written; a genuinely BARE field (no adjacent text) is NOT auto-fixed but
routed to review; the write clears the office_structure detector; and every
other byte round-trips. The adjacent-vs-bare gate is mutation-checked — flipping
the presence of adjacent text must flip the routing.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

etree = pytest.importorskip("lxml.etree")

import form_labels as fl  # noqa: E402
import office_structure as os_  # noqa: E402
import remediate_office as R  # noqa: E402

W = fl.W
_DOC = (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>{body}</w:body></w:document>"
)


def _root(body: str):
    return etree.fromstring(_DOC.format(body=body).encode("utf-8"))


def _sdt(kind: str, *, alias: str | None = None, content: str = " ") -> str:
    """One content control of the given input gallery type."""
    alias_xml = f'<w:alias w:val="{alias}"/>' if alias is not None else ""
    return (
        "<w:sdt><w:sdtPr>"
        f"{alias_xml}<w:{kind}/>"
        "</w:sdtPr>"
        f"<w:sdtContent><w:r><w:t>{content}</w:t></w:r></w:sdtContent>"
        "</w:sdt>"
    )


def _run(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def _para(*inner: str) -> str:
    return "<w:p>" + "".join(inner) + "</w:p>"


def _detector_findings(root) -> list[dict]:
    """Serialize the (possibly fixed) tree and run the real office_structure detector."""
    doc = _detector_findings._tmp / "doc.docx"
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr("word/document.xml", etree.tostring(root))
    return [f for f in os_.docx_checks(doc) if f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL"]


@pytest.fixture(autouse=True)
def _tmp_for_detector(tmp_path):
    _detector_findings._tmp = tmp_path
    yield


# --- inline caption in the same paragraph -----------------------------------

def test_inline_label_extracted_and_written():
    root = _root(_para(_run("Date of birth:"), _sdt("date")))
    labelled, bare = fl.plan_labels(root)
    assert bare == 0
    assert len(labelled) == 1
    sdt, label = labelled[0]
    assert label == "Date of birth"          # trailing colon stripped

    assert _detector_findings(root)          # trips before the fix
    fl.set_alias(sdt, label)
    assert not _detector_findings(root)      # cleared after the fix
    assert fl.current_alias(sdt) == "Date of birth"


def test_two_fields_on_one_line_each_get_their_own_caption():
    root = _root(_para(_run("First name:"), _sdt("date", content="a"),
                       _run(" Last name:"), _sdt("date", content="b")))
    labelled, bare = fl.plan_labels(root)
    labels = sorted(l for _, l in labelled)
    assert bare == 0
    assert labels == ["First name", "Last name"]


# --- preceding table cell (two-column form) ---------------------------------

def test_cell_label_from_preceding_cell():
    row = ("<w:tbl><w:tr>"
           f"<w:tc>{_para(_run('Full name'))}</w:tc>"
           f"<w:tc>{_para(_sdt('checkbox'))}</w:tc>"
           "</w:tr></w:tbl>")
    root = _root(row)
    labelled, bare = fl.plan_labels(root)
    assert bare == 0
    assert [l for _, l in labelled] == ["Full name"]


def test_cell_label_skips_a_neighbouring_field_cell():
    # left cell is itself a field, not a label → no adjacent text → bare.
    row = ("<w:tbl><w:tr>"
           f"<w:tc>{_para(_sdt('checkbox'))}</w:tc>"
           f"<w:tc>{_para(_sdt('checkbox'))}</w:tc>"
           "</w:tr></w:tbl>")
    root = _root(row)
    labelled, bare = fl.plan_labels(root)
    assert labelled == []
    assert bare == 2


# --- preceding paragraph (label on its own line) ----------------------------

def test_prev_paragraph_label_when_it_reads_like_one():
    root = _root(_para(_run("Manager approval:")) + _para(_sdt("checkbox")))
    labelled, bare = fl.plan_labels(root)
    assert bare == 0
    assert [l for _, l in labelled] == ["Manager approval"]


def test_prev_paragraph_prose_is_not_treated_as_a_label():
    prose = ("Please read the following terms carefully before you continue "
             "and only then complete the section that follows this notice")
    root = _root(_para(_run(prose)) + _para(_sdt("checkbox")))
    labelled, bare = fl.plan_labels(root)
    assert labelled == []                    # a long sentence is not a label
    assert bare == 1


# --- bare field routes to review, never invented ----------------------------

def test_bare_field_routes_to_review_not_fixed():
    root = _root(_para(_sdt("checkbox")))    # nothing adjacent at all
    labelled, bare = fl.plan_labels(root)
    assert labelled == []
    assert bare == 1
    assert _detector_findings(root)          # still a finding → review picks it up


def test_already_labelled_field_untouched():
    root = _root(_para(_run("Ignore me:"), _sdt("date", alias="Chosen date")))
    labelled, bare = fl.plan_labels(root)
    assert labelled == [] and bare == 0
    assert not _detector_findings(root)


# --- mutation-check: the adjacent-vs-bare gate must depend on adjacency ------

def test_gate_flips_with_presence_of_adjacent_text():
    with_text = _root(_para(_run("Signature:"), _sdt("date")))
    lab_w, bare_w = fl.plan_labels(with_text)
    assert (len(lab_w), bare_w) == (1, 0)    # adjacent text → auto-fix

    without_text = _root(_para(_sdt("date")))
    lab_b, bare_b = fl.plan_labels(without_text)
    assert (len(lab_b), bare_b) == (0, 1)    # no adjacent text → defer

    # A gate that always-labelled would fail the bare case; always-deferred would
    # fail the labelled case. Requiring both directions pins the real behaviour.


# --- other bytes preserved on write -----------------------------------------

def test_set_alias_preserves_other_bytes():
    root = _root(_para(_run("Country:"),
                       "<w:sdt><w:sdtPr><w:id w:val=\"77\"/><w:dropDownList>"
                       "<w:listItem w:displayText=\"Canada\" w:value=\"CA\"/>"
                       "</w:dropDownList></w:sdtPr>"
                       "<w:sdtContent><w:r><w:t>Choose</w:t></w:r></w:sdtContent></w:sdt>"))
    labelled, bare = fl.plan_labels(root)
    assert bare == 0 and len(labelled) == 1
    sdt, label = labelled[0]
    fl.set_alias(sdt, label)
    out = etree.tostring(root, encoding="unicode")
    # the alias was added...
    assert 'w:val="Country"' in out
    # ...and everything else round-trips untouched.
    assert 'w:id w:val="77"' in out
    assert 'w:displayText="Canada"' in out and 'w:value="CA"' in out
    assert "<w:t>Choose</w:t>" in out
    assert "<w:t>Country:</w:t>" in out


# --- wiring through the remediator's deterministic docx path -----------------

def test_wiring_records_diff_and_defers_bare(tmp_path):
    body = (_para(_run("Employee name:"), _sdt("date")) +   # has an adjacent label
            _para(_sdt("checkbox")))                        # bare
    entries = {"word/document.xml":
               _DOC.format(body=body).encode("utf-8")}
    diffs: list = []
    skipped: list = []
    applied = R._remediate_docx_structure(entries, diffs, skipped)

    assert any("form field" in a.lower() and "3.3.2" in a for a in applied)
    fix = next(d for d in diffs if d["rule_id"] == "3.3.2")
    assert "Employee name" in fix["after"]
    assert fix["before"] != fix["after"]
    # the bare field is surfaced as routed-to-review, not silently dropped.
    assert any("routed to review" in s for s in skipped)

    # the written document actually clears the labelled field for the detector,
    # while the bare one remains a finding.
    doc = tmp_path / "out.docx"
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr("word/document.xml", entries["word/document.xml"])
    remaining = [f for f in os_.docx_checks(doc)
                 if f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL"]
    assert len(remaining) == 1               # only the bare field is left


def test_wiring_default_no_skipped_collector_is_noop():
    """Omitting the skipped collector keeps the old contract (no crash)."""
    body = _para(_run("City:"), _sdt("date"))
    entries = {"word/document.xml": _DOC.format(body=body).encode("utf-8")}
    applied = R._remediate_docx_structure(entries)   # diffs=None, skipped=None
    assert any("3.3.2" in a for a in applied)
