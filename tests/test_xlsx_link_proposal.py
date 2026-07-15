"""xlsx 2.4.4 Link Purpose remediation (assisted): a vague cell-hyperlink gets a descriptive
link-text proposal, mirroring the docx/pptx path. Detection-only before; now proposal-backed."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import proposals as prop  # noqa: E402

_RELNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _xlsx(tmp_path: Path, *, display: str, target: str) -> Path:
    ws = ('<?xml version="1.0"?><worksheet><sheetData/>'
          f'<hyperlinks><hyperlink ref="A1" r:id="rId1" display="{display}"/></hyperlinks></worksheet>')
    rels = (f'<?xml version="1.0"?><Relationships xmlns="{_RELNS}">'
            f'<Relationship Id="rId1" Type="{_RELNS}/hyperlink" Target="{target}" TargetMode="External"/>'
            '</Relationships>')
    p = tmp_path / "b.xlsx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Sheet1"/></sheets></workbook>')
        zf.writestr("xl/worksheets/sheet1.xml", ws)
        zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", rels)
    p.write_bytes(buf.getvalue())
    return p


def test_extract_office_links_reads_xlsx_cell_hyperlinks(tmp_path):
    p = _xlsx(tmp_path, display="click here", target="mailto:sales@acme.com")
    links = prop.extract_office_links(p, "xlsx")
    assert ("click here", "mailto:sales@acme.com") in links


def test_vague_xlsx_link_gets_a_descriptive_proposal(tmp_path):
    p = _xlsx(tmp_path, display="click here", target="mailto:sales@acme.com")
    props = prop.propose_link_texts(p, "xlsx", ai_enabled=False)   # deterministic derivation, no AI
    assert props, "expected a 2.4.4 proposal for a vague cell hyperlink"
    pr = props[0]
    assert pr["sc"] == "2.4.4"
    assert pr["before"] == "click here"
    assert pr["proposed_value"] == "Email sales@acme.com"          # derived deterministically from the target


def test_descriptive_xlsx_link_yields_no_proposal(tmp_path):
    # A link whose text already describes the destination is not flagged (self-gating).
    p = _xlsx(tmp_path, display="Email the sales team", target="mailto:sales@acme.com")
    assert prop.propose_link_texts(p, "xlsx", ai_enabled=False) == []


def test_xlsx_hyperlink_without_display_is_skipped(tmp_path):
    # No display attr → label is the cell value; the detector skips it and so must the proposer.
    ws = ('<?xml version="1.0"?><worksheet><sheetData/>'
          '<hyperlinks><hyperlink ref="A1" r:id="rId1"/></hyperlinks></worksheet>')
    rels = (f'<?xml version="1.0"?><Relationships xmlns="{_RELNS}">'
            f'<Relationship Id="rId1" Type="{_RELNS}/hyperlink" Target="mailto:x@y.com" TargetMode="External"/>'
            '</Relationships>')
    p = tmp_path / "n.xlsx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", ws)
        zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", rels)
    p.write_bytes(buf.getvalue())
    assert prop.extract_office_links(p, "xlsx") == []
