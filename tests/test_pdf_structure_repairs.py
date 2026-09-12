import io
import json
from pathlib import Path

import pikepdf
import pytest

from pdf_structure_repairs import collect_structure_targets, apply_pdf_structure_repairs, propose_tagged_repairs
from remediate_pdf import apply_pdf_approved


CONTENT = b'\n'.join((f'/P << /MCID {i} >> BDC BT /F1 {20 if i == 0 else 12} Tf 10 {700-i*30} Td ({text}) Tj ET EMC').encode() for i,text in enumerate(['Introduction','Body paragraph','Name','Value','Patient','42']))

def fixture(*, pages=5, scope=None, span=1):
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        page = pdf.add_blank_page()
        page.obj['/Contents'] = pdf.make_stream(b'')
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    pdf.Root['/StructTreeRoot'] = root
    doc = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
    root['/K'] = pikepdf.Array([doc])
    def node(role, parent, text=None, mcid=None):
        child = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name('/'+role), P=parent, Pg=pdf.pages[0].obj))
        if text is not None: child['/ActualText'] = text
        if mcid is not None: child['/K'] = mcid
        return child
    heading = node('P', doc, 'Introduction', 0)
    paragraph = node('P', doc, 'Body paragraph', 1)
    table = node('Table', doc)
    tr1, tr2 = node('TR', table), node('TR', table)
    th1, th2 = node('TH', tr1, 'Name', 2), node('TH', tr1, 'Value', 3)
    td1, td2 = node('TD', tr2, 'Patient', 4), node('TD', tr2, '42', 5)
    if scope or span != 1:
        th1['/A'] = pikepdf.Dictionary(O=pikepdf.Name.Table, ColSpan=span)
        if scope: th1.A['/Scope'] = pikepdf.Name('/'+scope)
    tr1['/K'] = pikepdf.Array([th1, th2]); tr2['/K'] = pikepdf.Array([td1, td2])
    table['/K'] = pikepdf.Array([tr1, tr2]); doc['/K'] = pikepdf.Array([heading, paragraph, table])
    pdf.pages[0].obj['/Resources'] = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))))
    pdf.pages[0].obj['/Contents'] = pdf.make_stream(CONTENT)
    pdf.pages[0].obj['/StructParents'] = 0
    root['/ParentTree'] = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([heading,paragraph,th1,th2,td1,td2])])))
    annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
        Rect=pikepdf.Array([0,0,10,10]), A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://example.org')))
    pdf.pages[0].obj['/Annots'] = pikepdf.Array([annotation])
    field = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Tx, T='unchanged', V='patient value'))
    pdf.Root['/AcroForm'] = pikepdf.Dictionary(Fields=pikepdf.Array([field]))
    out = io.BytesIO(); pdf.save(out); return out.getvalue()


def targets(data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return collect_structure_targets(pdf)


def target(data, role, text=None):
    return next(r for r in targets(data) if r['role'] == '/'+role and (text is None or r['text'] == text))['locator']


def test_exact_heading_promotion_clears_canonical_detector_and_preserves_document(tmp_path):
    from office_structure import pdf_headings_labels_check
    data = fixture()
    path = tmp_path/'tagged.pdf'; path.write_bytes(data)
    assert pdf_headings_labels_check(path)
    locator = target(data, 'P', 'Introduction')
    candidate, applied, unresolved = apply_pdf_approved(data, {locator: json.dumps({'op':'heading','role':'H1'})})
    assert not unresolved and applied[0]['rule_id'] == 'SC_2_4_6'
    path.write_bytes(candidate)
    assert pdf_headings_labels_check(path) == []
    with pikepdf.open(io.BytesIO(candidate)) as pdf:
        assert len(pdf.pages) == 5
        assert str(pdf.Root.StructTreeRoot.K[0].K[0].S) == '/H1'
        assert pdf.Root.StructTreeRoot.K[0].K[0].K == 0
        assert str(pdf.Root.StructTreeRoot.K[0].K[0].ActualText) == 'Introduction'
        assert pdf.pages[0].Contents.read_bytes() == CONTENT
        assert str(pdf.pages[0].Annots[0].A.URI) == 'https://example.org'
        assert str(pdf.Root.AcroForm.Fields[0].V) == 'patient value'


def test_existing_table_header_scope_preserves_cells_and_spans():
    data = fixture(span=2)
    locator = target(data, 'TH','Name')
    candidate, applied, unresolved = apply_pdf_approved(data, {locator: {'op':'header-scope','scope':'Column'}})
    assert applied and not unresolved
    with pikepdf.open(io.BytesIO(candidate)) as pdf:
        table = pdf.Root.StructTreeRoot.K[0].K[2]
        assert table.K[0].K[0].A.ColSpan == 2
        assert str(table.K[0].K[0].A.Scope) == '/Column'
        assert [str(c.ActualText) for c in table.K[1].K] == ['Patient','42']


def test_explicit_reading_order_reorders_existing_tags_only():
    data = fixture()
    candidate, applied, unresolved = apply_pdf_approved(data, {target(data,'Document'): {'op':'reading-order','order':[1,0,2]}})
    assert applied and not unresolved
    with pikepdf.open(io.BytesIO(candidate)) as pdf:
        doc = pdf.Root.StructTreeRoot.K[0]
        assert [str(c.get('/ActualText','')) for c in doc.K] == ['Body paragraph','Introduction','']
        assert doc.K[0].K == 1 and doc.K[1].K == 0
        assert doc.K[0].P.objgen == doc.objgen
        assert pdf.pages[0].Contents.read_bytes() == CONTENT


@pytest.mark.parametrize('plan', [ {'op':'heading','role':'H0'}, {'op':'heading','role':'H7'},
    {'op':'heading','role':'H1','text':'invented'}, {'op':'reading-order','order':[0,0,2]},
    {'op':'reading-order','order':[0,1]}, {'op':'reading-order','order':[True,0,2]},
    {'op':'header-scope','scope':'Column'}, {'op':'ocr','text':'invented'}, 'not json'])
def test_invalid_or_wrong_target_plans_are_atomic_no_ops(plan):
    data = fixture()
    locator = target(data,'P','Introduction')
    candidate, applied, unresolved = apply_pdf_structure_repairs(data, {locator:plan})
    assert candidate == data and not applied and unresolved == [locator]


def test_stale_content_and_stale_tree_cannot_be_approved():
    data = fixture(); locator = target(data,'P','Introduction')
    for mutation in ['content','tree']:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            if mutation == 'content': pdf.pages[0].Contents = pdf.make_stream(b'BT (changed source) Tj ET')
            else: pdf.Root.StructTreeRoot.K[0].K[1].ActualText = 'Changed passage'
            out=io.BytesIO(); pdf.save(out); changed=out.getvalue()
        assert apply_pdf_structure_repairs(changed, {locator:{'op':'heading','role':'H1'}}) == (changed,[],[locator])


def test_signed_cycle_and_inconsistent_parent_fail_closed():
    data=fixture(); locator=target(data,'P','Introduction')
    for mutation in ['signed','cycle','parent']:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            if mutation == 'signed': pdf.Root.AcroForm.SigFlags = 3
            elif mutation == 'cycle': pdf.Root.StructTreeRoot.K[0].K[0].K = pdf.Root.StructTreeRoot.K[0]
            else: pdf.Root.StructTreeRoot.K[0].K[0].P = pdf.Root.StructTreeRoot
            out=io.BytesIO(); pdf.save(out); changed=out.getvalue()
        assert apply_pdf_structure_repairs(changed,{locator:{'op':'heading','role':'H1'}}) == (changed,[],[locator])


def test_tagged_proposals_have_concrete_writable_values_and_complex_table_not_guessed():
    data=fixture()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        proposals=propose_tagged_repairs(pdf,[('Introduction',0,20)])
    assert sorted(p['kind'] for p in proposals) == ['pdf-table-header-scope','pdf-table-header-scope','pdf-tag-heading']
    assert all(not p.get('explain_only') for p in proposals)
    candidate, applied, unresolved = apply_pdf_approved(data,{p['locator']:p['proposed_value'] for p in proposals})
    assert len(applied)==3 and not unresolved and candidate != data
    with pikepdf.open(io.BytesIO(fixture(span=2))) as pdf:
        assert not propose_tagged_repairs(pdf)


def test_scanned_untagged_and_nonmatching_text_do_not_get_fabricated_headings():
    pdf=pikepdf.Pdf.new(); pdf.add_blank_page()
    assert not propose_tagged_repairs(pdf,[('invented',0,20)])
    with pikepdf.open(io.BytesIO(fixture())) as tagged:
        assert not any(p['kind']=='pdf-tag-heading' for p in propose_tagged_repairs(tagged,[('different',0,20)]))


def test_complex_table_explicit_header_associations_preserve_spans_and_ids():
    data = fixture(span=2)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        table=pdf.Root.StructTreeRoot.K[0].K[2]
        table.K[0].K[0].ID = 'group-name'
        table.K[0].K[1].ID = 'value-column'
        pdf.Root.StructTreeRoot.IDTree = pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(['group-name',table.K[0].K[0],'value-column',table.K[0].K[1]])))
        out=io.BytesIO(); pdf.save(out); data=out.getvalue()
    locator=target(data,'TD','Patient')
    candidate, applied, unresolved=apply_pdf_approved(data,{locator:{'op':'table-headers','headers':['group-name','value-column']}})
    assert applied and not unresolved
    with pikepdf.open(io.BytesIO(candidate)) as pdf:
        table=pdf.Root.StructTreeRoot.K[0].K[2]
        assert table.K[0].K[0].A.ColSpan == 2
        assert str(table.K[0].K[0].ID) == 'group-name'
        assert [str(h) for h in table.K[1].K[0].A.Headers] == ['group-name','value-column']
    bad={locator:{'op':'table-headers','headers':['invented']}}
    assert apply_pdf_structure_repairs(data,bad) == (data,[],[locator])


def test_valid_and_invalid_batch_does_not_partially_modify_tags():
    data=fixture()
    values={target(data,'P','Introduction'):{'op':'heading','role':'H1'}, target(data,'TH','Name'):{'op':'header-scope','scope':'Invalid'}}
    assert apply_pdf_structure_repairs(data,values) == (data,[],list(values))


def test_signature_field_without_sigflags_is_not_resaved_or_proposed():
    data=fixture()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.Root.AcroForm.Fields[0].FT = pikepdf.Name.Sig
        out=io.BytesIO(); pdf.save(out); signed=out.getvalue()
    locator=target(signed,'P','Introduction')
    assert apply_pdf_structure_repairs(signed,{locator:{'op':'heading','role':'H1'}}) == (signed,[],[locator])
    with pikepdf.open(io.BytesIO(signed)) as pdf:
        assert propose_tagged_repairs(pdf,[('Introduction',0,20)]) == []


def test_real_remediation_emits_plans_that_apply_to_its_saved_candidate(tmp_path):
    from remediate_pdf import remediate_pdf, _extract_pdf_headings
    data=fixture(); source=tmp_path/'tagged.pdf'; source.write_bytes(data)
    assert _extract_pdf_headings(str(source)) == [('Introduction',0,20)]
    proposals=[]
    saved, _, _ = remediate_pdf(source, ai_enabled=False, proposals=proposals)
    candidate=Path(saved).read_bytes() if saved else data
    concrete=[p for p in proposals if p.get('kind') in {'pdf-tag-heading','pdf-table-header-scope'}]
    assert len(concrete)==3
    changed, applied, unresolved = apply_pdf_approved(candidate,{p['locator']:p['proposed_value'] for p in concrete})
    assert len(applied)==3 and unresolved == [] and changed != candidate


@pytest.mark.parametrize('mutation',['missing-content','duplicate-content','wrong-parent-tree','missing-parent-tree'])
def test_broken_tag_to_content_associations_never_get_repaired(mutation):
    data=fixture(); locator=target(data,'P','Introduction')
    with pikepdf.open(io.BytesIO(data)) as pdf:
        if mutation=='missing-content': pdf.pages[0].Contents=pdf.make_stream(b'')
        elif mutation=='duplicate-content': pdf.pages[0].Contents=pdf.make_stream(CONTENT+b'\n'+CONTENT)
        elif mutation=='wrong-parent-tree': pdf.Root.StructTreeRoot.ParentTree.Nums[1][0]=pdf.Root.StructTreeRoot.K[0].K[1]
        else: del pdf.Root.StructTreeRoot['/ParentTree']
        out=io.BytesIO(); pdf.save(out); invalid=out.getvalue()
    assert apply_pdf_structure_repairs(invalid,{locator:{'op':'heading','role':'H1'}}) == (invalid,[],[locator])
    with pikepdf.open(io.BytesIO(invalid)) as pdf:
        assert propose_tagged_repairs(pdf,[('Introduction',0,20)]) == []
