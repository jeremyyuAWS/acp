"""Writing an approved accessible name onto a Word form field (WCAG 4.1.2).

The Word twin of `remediate_pdf.apply_pdf_field_name`, which had no counterpart: every
unlabeled content control got a drafted label and the approval stopped in the review queue,
so the criterion stayed failing however many names a reviewer signed off.

The round trip at the bottom is the test that matters. The applier's own assertions prove the
write lands; only a re-scan proves the criterion CLEARS, and that is what decides whether the
lane ever credits the approval. Two lanes on this project shipped writes that landed and never
cleared, and both were invisible until a re-scan was run against the real detector.
"""
from __future__ import annotations
import io
import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from apply_field_name import apply_docx_field_name  # noqa: E402
import office_structure as osx  # noqa: E402
import propose_forms  # noqa: E402

_DOC = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>{body}</w:body></w:document>"""


def _field(kind: str = "date", *, sid: str | None = "101", alias: str | None = None,
           label: str = "Date of birth") -> str:
    pr = f'<w:id w:val="{sid}"/>' if sid else ""
    if alias is not None:
        pr += f'<w:alias w:val="{alias}"/>'
    pr += f"<w:{kind}/>"
    return (f"<w:p><w:r><w:t>{label}</w:t></w:r></w:p>"
            f"<w:sdt><w:sdtPr>{pr}</w:sdtPr>"
            f"<w:sdtContent><w:r><w:t> </w:t></w:r></w:sdtContent></w:sdt>")


def _pkg(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", _DOC.format(body=body))
    return buf.getvalue()


def _doc(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _scs(data: bytes, tmp_path) -> set[str]:
    """What a re-scan sees — the first-party checks the residual verifier runs in-process."""
    p = tmp_path / "f.docx"
    p.write_bytes(data)
    return {f.get("wcag", "").split()[0]
            for f in osx.docx_checks(p) + osx.checks_for(p, ".docx")}


# ── the write ─────────────────────────────────────────────────────────────────

def test_the_approved_name_is_written_as_the_control_title():
    pkg = _pkg(_field())
    out, applied, unresolved = apply_docx_field_name(pkg, {"docx:sdt:101": "Date of birth"})
    assert not unresolved and len(applied) == 1
    assert '<w:alias w:val="Date of birth"/>' in _doc(out)


def test_an_existing_name_is_never_overwritten():
    """That field is not a finding; the author's own value wins."""
    pkg = _pkg(_field(alias="Author's own title"))
    out, applied, unresolved = apply_docx_field_name(pkg, {"docx:sdt:101": "Something else"})
    assert not applied
    assert unresolved == ["docx:sdt:101"]
    assert out == pkg


def test_an_empty_alias_is_replaced_not_duplicated():
    pkg = _pkg(_field(alias=""))
    out, applied, _ = apply_docx_field_name(pkg, {"docx:sdt:101": "Date of birth"})
    assert applied
    assert _doc(out).count("<w:alias") == 1
    assert 'w:val="Date of birth"' in _doc(out)


def test_only_the_addressed_field_is_named():
    pkg = _pkg(_field(sid="1", label="First") + _field(kind="comboBox", sid="2", label="Second"))
    out, applied, _ = apply_docx_field_name(pkg, {"docx:sdt:2": "Second field"})
    assert [a["locator"] for a in applied] == ["docx:sdt:2"]
    doc = _doc(out)
    assert doc.count("<w:alias") == 1 and 'w:val="Second field"' in doc


def test_a_locator_that_no_longer_resolves_is_reported_not_approximated():
    """Naming a neighbouring field is worse than leaving it unnamed — it reads as authoritative."""
    pkg = _pkg(_field(sid="101"))
    out, applied, unresolved = apply_docx_field_name(pkg, {"docx:sdt:999": "Gone"})
    assert not applied
    assert unresolved == ["docx:sdt:999"]
    assert out == pkg
    assert "<w:alias" not in _doc(out)


def test_a_field_with_no_w_id_resolves_by_ordinal():
    pkg = _pkg(_field(sid=None))
    out, applied, unresolved = apply_docx_field_name(pkg, {"docx:sdt:#1": "Date of birth"})
    assert applied and not unresolved
    assert '<w:alias w:val="Date of birth"/>' in _doc(out)


def test_non_input_content_controls_are_not_counted_for_the_ordinal():
    """The ordinal must count the same population the proposer counted, or the fallback
    addresses a different field than the one the reviewer saw."""
    rich = ('<w:sdt><w:sdtPr><w:id w:val="9"/></w:sdtPr>'
            '<w:sdtContent><w:r><w:t>a TOC block</w:t></w:r></w:sdtContent></w:sdt>')
    pkg = _pkg(rich + _field(sid=None))
    out, applied, _ = apply_docx_field_name(pkg, {"docx:sdt:#1": "Date of birth"})
    assert len(applied) == 1
    assert '<w:alias w:val="Date of birth"/>' in _doc(out)


def test_the_name_is_xml_escaped():
    pkg = _pkg(_field())
    out, _, _ = apply_docx_field_name(pkg, {"docx:sdt:101": 'Ben & Jerry\'s "size"'})
    doc = _doc(out)
    assert "&amp;" in doc and "&quot;" in doc
    assert zipfile.ZipFile(io.BytesIO(out))          # still a readable package


def test_empty_values_are_a_no_op():
    pkg = _pkg(_field())
    out, applied, unresolved = apply_docx_field_name(pkg, {"docx:sdt:101": "   "})
    assert not applied and not unresolved and out == pkg


# ── proposer / applier agreement ─────────────────────────────────────────────

def test_a_proposals_locator_resolves_in_the_applier():
    """The two mint and consume the same key. If they drift, every approval strands."""
    body = _field(sid="55", label="Full name")
    doc = _DOC.format(body=body)
    props = propose_forms.proposals_from_document_xml(doc, ai_enabled=False)
    assert len(props) == 1, props
    locator = props[0]["locator"]
    assert locator == "docx:sdt:55"
    out, applied, unresolved = apply_docx_field_name(_pkg(body), {locator: "Full name"})
    assert applied and not unresolved


# ── the round trip that decides whether the approval earns credit ────────────

def test_writing_the_name_clears_the_criterion(tmp_path):
    pkg = _pkg(_field())
    assert "4.1.2" in _scs(pkg, tmp_path)
    out, applied, _ = apply_docx_field_name(pkg, {"docx:sdt:101": "Date of birth"})
    assert applied
    assert "4.1.2" not in _scs(out, tmp_path)


def test_naming_one_of_two_fields_does_not_clear_it(tmp_path):
    """Partial remediation must not certify. The criterion is about every control."""
    pkg = _pkg(_field(sid="1") + _field(kind="comboBox", sid="2"))
    out, applied, _ = apply_docx_field_name(pkg, {"docx:sdt:1": "First"})
    assert len(applied) == 1
    assert "4.1.2" in _scs(out, tmp_path)


def test_the_same_write_also_clears_the_visible_label_criterion(tmp_path):
    """w:alias is both the accessible name (4.1.2) and the visible label (3.3.2), so one
    approval settles both — the reason the detector flags them together."""
    pkg = _pkg(_field())
    assert {"3.3.2", "4.1.2"} <= _scs(pkg, tmp_path)
    out, _, _ = apply_docx_field_name(pkg, {"docx:sdt:101": "Date of birth"})
    assert not ({"3.3.2", "4.1.2"} & _scs(out, tmp_path))
