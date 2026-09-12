from pathlib import Path
import io
import json
import runpy

import pikepdf

from formats.pdf.detectors.table_headers import detect
from pdf_structure_repairs import propose_tagged_repairs
from remediate_pdf import apply_pdf_approved


def fixture():
    return runpy.run_path(str(Path(__file__).with_name('test_pdf_structure_repairs.py')))['fixture']()


def test_canonical_table_header_detector_clears_exact_saved_scope_defect(tmp_path):
    import office_structure
    data=fixture(); path=tmp_path/'tagged.pdf'; path.write_bytes(data)
    before=detect(path)
    assert len(before)==2 and all(f['ruleId']=='PDF_TABLE_HEADER_SCOPE_MISSING' for f in before)
    assert before==[f for f in office_structure.checks_for(path,'.pdf') if f['ruleId']=='PDF_TABLE_HEADER_SCOPE_MISSING']
    with pikepdf.open(io.BytesIO(data)) as pdf:
        proposals=[p for p in propose_tagged_repairs(pdf) if p['kind']=='pdf-table-header-scope']
    assert {p['locator'] for p in proposals}=={f['location'] for f in before}
    corrected,applied,unresolved=apply_pdf_approved(data,{p['locator']:p['proposed_value'] for p in proposals})
    assert len(applied)==2 and not unresolved
    path.write_bytes(corrected)
    assert detect(path)==[]
    import rule_registry
    from assessment import Coverage
    rule_registry.load()
    registration=rule_registry.get('1.3.1','pdf')
    assert registration.coverage is Coverage.PARTIAL
    assert rule_registry.evaluate('1.3.1','pdf',path).status=='REVIEW'


def test_explicit_complete_header_associations_clear_missing_scope_without_inventing_scope(tmp_path):
    data=fixture()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        table=pdf.Root.StructTreeRoot.K[0].K[2]
        table.K[0].K[0].ID='name'; table.K[0].K[1].ID='value'
        pdf.Root.StructTreeRoot.IDTree=pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(['name',table.K[0].K[0],'value',table.K[0].K[1]])))
        for cell in table.K[1].K:
            cell.A=pikepdf.Dictionary(O=pikepdf.Name.Table,Headers=pikepdf.Array(['name','value']))
        out=io.BytesIO(); pdf.save(out); linked=out.getvalue()
    path=tmp_path/'linked.pdf'; path.write_bytes(linked)
    assert detect(path)==[]
    with pikepdf.open(io.BytesIO(linked)) as pdf:
        pdf.Root.StructTreeRoot.K[0].K[2].K[1].K[0].A.Headers=pikepdf.Array(['invented'])
        pdf.save(path)
    assert len(detect(path))==2


def test_tag_tree_capability_is_actual_file_specific(tmp_path):
    from capabilities import capabilities_for,Capability
    tagged=tmp_path/'tagged.pdf'; tagged.write_bytes(fixture())
    assert Capability.TAG_TREE in capabilities_for('pdf',tagged)
    pdf=pikepdf.Pdf.new(); pdf.add_blank_page(); untagged=tmp_path/'untagged.pdf'; pdf.save(untagged)
    assert Capability.TAG_TREE not in capabilities_for('pdf',untagged)
    assert detect(untagged)==[]
