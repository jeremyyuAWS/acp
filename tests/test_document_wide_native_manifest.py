from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pikepdf
import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from document_wide_manifest import build_manifest, package_images, package_native_pdf
from document_wide_native_pdf import figure_regions, validate_native_pdf
from test_document_wide_manifest import setup_manifest


def figures(*, boxes=True, overlap=False, rotation=0):
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=(400, 400))
    c.setFillColorRGB(1, 0, 0); c.rect(30, 200, 100, 100, fill=1)
    c.setFillColorRGB(0, 0, 1); c.rect(230, 200, 100, 100, fill=1)
    c.save()
    with pikepdf.open(BytesIO(stream.getvalue())) as pdf:
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
        tags = []
        for i, box in enumerate(((30,200,130,300), (30,200,130,300) if overlap else (230,200,330,300))):
            tag = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/Figure'), Pg=pdf.pages[0].obj, P=root, K=i))
            if boxes:
                tag.A = pikepdf.Dictionary(O=pikepdf.Name('/Layout'), BBox=pikepdf.Array(box))
            tags.append(tag)
        root.K = pikepdf.Array(tags)
        pdf.Root.StructTreeRoot = root
        pdf.pages[0].obj.Rotate = rotation
        out=BytesIO();pdf.save(out);return out.getvalue()


def manifest_for(store, monkeypatch, data, mode='native_pdf'):
    rows = setup_manifest(store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0', 'pdf:fig:1:1'])
    import llm_waterfall_provider
    context = llm_waterfall_provider.managed_context()
    context.policy = SimpleNamespace(document_wide_input_mode=mode)
    return build_manifest(store, 'scan', 'a.pdf', data), rows


def test_native_multiple_figures_use_exact_boxes_and_frozen_ids(isolated_store, monkeypatch):
    data=figures()
    manifest, rows=manifest_for(isolated_store, monkeypatch, data)
    assert {f.finding_id for f in manifest.findings} == {r['finding_id'] for r in rows}
    assert len(manifest.evidence) == 2
    assert all('Layout BBox' in e.reason and 'native_pdf_region' in e.text for e in manifest.evidence)
    images=package_images(data, manifest)
    assert len(images)==2
    colors=[]
    for e in manifest.evidence:
        with Image.open(BytesIO(images[e.image_ref])) as image:
            colors.append(image.convert('RGB').getpixel((image.width//2,image.height//2)))
    assert colors==[(255,0,0),(0,0,255)]
    assert package_native_pdf(data, manifest) is data
    assert manifest.assessment_revision=='saved-assessment'
    assert {op.op for op in manifest.allowed_operations}=={'set_pdf_figure_alt_text'}


@pytest.mark.parametrize('kwargs', [{'boxes':False}, {'overlap':True}, {'rotation':90}])
def test_ambiguous_native_figures_stay_without_visual_authorization(isolated_store, monkeypatch, kwargs):
    manifest,_=manifest_for(isolated_store, monkeypatch, figures(**kwargs))
    assert not manifest.evidence
    assert len([i for i in manifest.extraction_issues if i.kind=='missing_visual_evidence'])==2


def test_extracted_mode_does_not_silently_enable_native_regions(isolated_store, monkeypatch):
    manifest,_=manifest_for(isolated_store, monkeypatch, figures(), 'extracted')
    assert not manifest.evidence


def test_native_bytes_reject_changed_identity_and_context_limit(isolated_store, monkeypatch):
    data=figures();manifest,_=manifest_for(isolated_store, monkeypatch, data)
    with pytest.raises(ValueError, match='document_source_changed'):
        package_native_pdf(data+b'changed',manifest)
    with pytest.raises(ValueError, match='document_too_large'):
        package_native_pdf(data,replace(manifest,text_context='x'*60001))


def test_native_readability_encryption_and_size_bounds(monkeypatch):
    from document_wide_native_pdf import MAX_BYTES
    with pytest.raises(ValueError,match='document_too_large'):
        validate_native_pdf(b'x'*(MAX_BYTES+1))
    with pytest.raises(ValueError,match='document_format_unsupported'):
        validate_native_pdf(b'not a PDF')
    with pytest.raises(ValueError,match='document_native_pdf'):
        validate_native_pdf(b'%PDF-1.7\nbroken')
    with pikepdf.open(BytesIO(figures())) as pdf:
        out=BytesIO();pdf.save(out,encryption=pikepdf.Encryption(owner='owner',user=''))
        with pytest.raises(ValueError,match='document_native_pdf'):
            validate_native_pdf(out.getvalue())
        for _ in range(100):pdf.add_blank_page()
        out=BytesIO();pdf.save(out)
        with pytest.raises(ValueError,match='document_native_pdf'):
            validate_native_pdf(out.getvalue())


def test_native_run_keeps_docx_extracted_image_context(isolated_store, monkeypatch):
    from experiments.document_wide_ai.fixtures.make_fixtures import make_docx
    import llm_waterfall_provider
    data = make_docx()
    setup_manifest(isolated_store, monkeypatch, data, 'a.docx', '1.1.1', ['aggregate-instance:s:1'])
    llm_waterfall_provider.managed_context().policy = SimpleNamespace(document_wide_input_mode='native_pdf')
    manifest = build_manifest(isolated_store, 'scan', 'a.docx', data)
    assert manifest.document_format.value == 'docx'
    assert len(manifest.findings) == 1 and len(package_images(data, manifest)) == 1
    with pytest.raises(ValueError, match='document_format_unsupported'):
        package_native_pdf(data, manifest)
