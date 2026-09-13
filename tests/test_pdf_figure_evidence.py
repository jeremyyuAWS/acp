"""Real PDF fixtures for narrow raster association, independent of vision/model guesses."""
import hashlib
import io

import pytest

pikepdf = pytest.importorskip('pikepdf')
from PIL import Image
from pdf_figure_evidence import FigureEvidenceError, exact_figure_image


def raster_pdf(*, ops='q 80 0 0 80 10 10 cm /Im0 Do Q', pixels=None, size=8):
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(100, 100))
    page.obj.StructParents = 0
    image = pdf.make_stream(pixels if pixels is not None else bytes([255, 0, 0])*(size*size))
    image.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
        Width=size, Height=size, ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8))
    page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
    page.obj.Contents = pdf.make_stream(('/Figure <</MCID 0>> BDC '+ops+' EMC').encode())
    figure = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
        S=pikepdf.Name.Figure, Pg=page.obj, K=0))
    doc = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
        S=pikepdf.Name.Document, K=pikepdf.Array([figure])))
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot, K=doc,
        ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([figure])]))))
    figure.P, doc.P = doc, root
    pdf.Root.StructTreeRoot = root
    return pdf, figure, image


def saved_bytes(pdf):
    output = io.BytesIO(); pdf.save(output)
    return output.getvalue()


def test_real_unique_tagged_raster_returns_only_exact_pixels_without_mutation():
    pdf, figure, image = raster_pdf()
    with pdf:
        source = saved_bytes(pdf)
        evidence = exact_figure_image(pdf, figure)
        png = evidence['image_bytes']
        pil = Image.open(io.BytesIO(png))
        assert pil.mode == 'RGB' and pil.size == (8, 8)
        assert {pil.getpixel((x, y)) for x in range(8) for y in range(8)} == {(255, 0, 0)}
        assert evidence['image_sha256'] == hashlib.sha256(png).hexdigest()
        assert (evidence['page'], evidence['mcid']) == (1, 0)
        assert saved_bytes(pdf) == source
        assert '/Alt' not in figure


@pytest.mark.parametrize('ops', [
    '/Im0 Do /Im0 Do', 'BT (body text) Tj ET /Im0 Do',
    '0 0 8 8 re f /Im0 Do', '0 0 8 8 re W n /Im0 Do', '/GS0 gs /Im0 Do',
    'q /Im0 Do', 'Q /Im0 Do', 'q 0 60 -80 0 80 0 cm /Im0 Do Q',
    'q -80 0 0 60 80 0 cm /Im0 Do Q', 'q 1000 0 0 60 0 0 cm /Im0 Do Q',
    '/Artifact BMC /Im0 Do EMC',
])
def test_mixed_transformed_duplicate_or_malformed_graphics_stay_unresolved(ops):
    pdf, figure, image = raster_pdf(ops=ops)
    with pdf, pytest.raises(FigureEvidenceError):
        exact_figure_image(pdf, figure)
    assert '/Alt' not in figure


@pytest.mark.parametrize('mutation', ['duplicate_mcid', 'wrong_parent', 'missing_parent',
    'multiple_k', 'form', 'mask', 'softmask', 'decode', 'imagemask', 'huge_image',
    'unsupported_color', 'rotate', 'inherited_rotate', 'annotation', 'external_text', 'user_unit', 'intent', 'nonuniform_scale', 'default_rgb', 'output_intent'])
def test_unsupported_association_or_composite_is_manual(mutation):
    pdf, figure, image = raster_pdf()
    page = pdf.pages[0]
    if mutation == 'default_rgb':
        page.obj.Resources.ColorSpace = pikepdf.Dictionary(DefaultRGB=pikepdf.Array([pikepdf.Name.CalRGB, pikepdf.Dictionary(WhitePoint=pikepdf.Array([1, 1, 1]))]))
    elif mutation == 'output_intent':
        pdf.Root.OutputIntents = pikepdf.Array([pikepdf.Dictionary(S=pikepdf.Name.GTS_PDFA1)])
    elif mutation == 'user_unit':
        page.obj.UserUnit = 2
    elif mutation == 'intent':
        image.Intent = pikepdf.Name.Perceptual
    elif mutation == 'nonuniform_scale':
        page.obj.Contents = pdf.make_stream(b'/Figure <</MCID 0>> BDC q 80 0 0 40 10 10 cm /Im0 Do Q EMC')
    elif mutation == 'duplicate_mcid':
        page.obj.Contents = pdf.make_stream(page.obj.Contents.read_bytes()*2)
    elif mutation == 'wrong_parent':
        pdf.Root.StructTreeRoot.ParentTree.Nums[1][0] = figure.P
    elif mutation == 'missing_parent':
        del pdf.Root.StructTreeRoot['/ParentTree']
    elif mutation == 'multiple_k':
        figure.K = pikepdf.Array([0, 0])
    elif mutation == 'form':
        image.Subtype = pikepdf.Name.Form
    elif mutation == 'mask':
        image.Mask = pikepdf.Array([0, 255, 0, 255, 0, 255])
    elif mutation == 'softmask':
        image.SMask = image
    elif mutation == 'decode':
        image.Decode = pikepdf.Array([1, 0, 1, 0, 1, 0])
    elif mutation == 'imagemask':
        image.ImageMask = True
    elif mutation == 'huge_image':
        image.Width = 100_000
    elif mutation == 'unsupported_color':
        image.ColorSpace = pikepdf.Name.DeviceCMYK
    elif mutation == 'rotate':
        page.obj.Rotate = 90
    elif mutation == 'inherited_rotate':
        page.obj.Parent.Rotate = 180
    elif mutation == 'annotation':
        page.obj.Annots = pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name.Annot)])
    elif mutation == 'external_text':
        page.obj.Contents = pdf.make_stream(page.obj.Contents.read_bytes()+b' BT (outside) Tj ET')
    with pdf, pytest.raises(FigureEvidenceError):
        exact_figure_image(pdf, figure)
    assert '/Alt' not in figure


def test_canonical_caption_uses_only_exact_image_and_preserves_render_source_and_fresh_findings(monkeypatch, tmp_path):
    import ai, remediate_pdf
    from formats.pdf.detectors import non_text_content
    pdf, figure, image = raster_pdf(size=32)
    source = saved_bytes(pdf)
    path = tmp_path/'source.pdf'; path.write_bytes(source)
    before_render = remediate_pdf._render_page_png(str(path), 1)
    assert before_render and non_text_content.detect(path)
    seen = []
    def describe(png, **kwargs):
        exact = Image.open(io.BytesIO(png)); assert exact.size == (32, 32)
        assert exact.getpixel((0, 0)) == (255, 0, 0)
        seen.append(png)
        return {'alt': 'A solid red image.', 'grounded': False, 'model': 'fixture', 'ai_call_id': 'fixture'}
    monkeypatch.setattr(ai, 'describe_image_structured', describe)
    props = remediate_pdf.alt_proposals_for_pdf(source, context_file='source.pdf')
    assert len(props) == len(seen) == 1
    proposal = props[0]
    assert proposal['proposed_value'] == 'The image is a solid red color.'
    assert proposal['automatic_write_blocked'] is False
    assert proposal['source_sha256'] == hashlib.sha256(source).hexdigest()
    assert remediate_pdf.validate_exact_figure_proposals(source, props) is True
    changed = dict(proposal, proposed_value='The image is a solid blue color.')
    assert remediate_pdf.validate_exact_figure_proposals(source, [changed]) is False
    corrected, applied, unresolved = remediate_pdf.apply_pdf_approved(source,
        {proposal['locator']: proposal['proposed_value']})
    assert len(applied) == 1 and not unresolved
    done = tmp_path/'corrected.pdf'; done.write_bytes(corrected)
    assert non_text_content.detect(done) == []  # actual written artifact, not draft
    assert remediate_pdf._render_page_png(str(done), 1) == before_render
    assert path.read_bytes() == source
    with pikepdf.open(io.BytesIO(corrected)) as check:
        assert check.pages[0].obj.Contents.read_bytes() == pdf.pages[0].obj.Contents.read_bytes()
        assert check.pages[0].obj.Resources.XObject.Im0.read_bytes() == image.read_bytes()
    fixes, manual = [], []
    messages, deferred = remediate_pdf._fix_pdf_figure_alt(pdf, str(path), ai_enabled=True,
        scan_id=None, file='source.pdf', applied_fixes=fixes, proposals=manual)
    assert messages and deferred == 0 and not manual
    assert fixes[0]['caption_validation']['approved'] is True
    assert fixes[0]['figure_image_sha256'] == proposal['figure_image_sha256']
    assert '/Alt' in figure
    pdf.close()


@pytest.mark.parametrize('caption', ['The image is a solid blue color.', 'A solid red image with a patient chart.'])
def test_rejected_or_unknown_semantics_stay_manual_even_if_provider_grounded(caption, monkeypatch):
    import ai, remediate_pdf
    pdf, figure, image = raster_pdf(size=32)
    monkeypatch.setattr(ai, 'describe_image_structured', lambda *a, **k: {'alt': caption, 'grounded': True, 'model': 'fixture', 'ai_call_id': 'fixture'})
    fixes, props = [], []
    messages, deferred = remediate_pdf._fix_pdf_figure_alt(pdf, '', ai_enabled=True,
        scan_id=None, file='source.pdf', applied_fixes=fixes, proposals=props)
    assert messages == [] and deferred == 1 and fixes == [] and '/Alt' not in figure
    assert props[0]['proposed_value'] == caption and props[0]['automatic_write_blocked'] is True
    pdf.close()


@pytest.mark.parametrize('target', ['content', 'image'])
def test_compressed_bombs_rejected_before_unbounded_pdf_decode(target, monkeypatch):
    import zlib
    import pdf_figure_evidence as evidence
    pdf, figure, image = raster_pdf()
    if target == 'content':
        pdf.pages[0].obj.Contents = pdf.make_stream(zlib.compress(b' '*4096), pikepdf.Dictionary(Filter=pikepdf.Name.FlateDecode))
        monkeypatch.setattr(evidence, 'MAX_CONTENT_BYTES', 1024)
    else:
        image.write(zlib.compress(b'\x00'*4096), filter=pikepdf.Name.FlateDecode)
    with pdf, pytest.raises(FigureEvidenceError, match='stream_limit'):
        exact_figure_image(pdf, figure)


def test_exact_image_thumbnail_is_png_bounded_for_review_and_has_no_page_context(monkeypatch):
    import base64
    import ai, remediate_pdf
    pdf, _, _ = raster_pdf(size=512)
    data = saved_bytes(pdf); pdf.close()
    seen = []
    def describe(png, **kw):
        seen.append(Image.open(io.BytesIO(png)).size)
        return {'alt': 'A solid red image.', 'model': 'fixture', 'ai_call_id': 'fixture'}
    monkeypatch.setattr(ai, 'describe_image_structured', describe)
    proposal = remediate_pdf.alt_proposals_for_pdf(data)[0]
    thumb = Image.open(io.BytesIO(base64.b64decode(proposal['thumb'].split(',', 1)[1])))
    assert thumb.size == (320, 320) and seen == [(512, 512)]
    assert thumb.getpixel((0, 0)) == (255, 0, 0)


def test_cyclic_structure_never_reaches_vision_or_an_automatic_writer(monkeypatch):
    import ai, remediate_pdf
    pdf, figure, _ = raster_pdf(size=32)
    figure.K = figure
    source = saved_bytes(pdf)
    monkeypatch.setattr(ai, 'describe_image_structured', lambda *a, **k: pytest.fail('cyclic tags must not consume vision'))
    assert remediate_pdf.alt_proposals_for_pdf(source) == []
    assert '/Alt' not in figure
    pdf.close()
