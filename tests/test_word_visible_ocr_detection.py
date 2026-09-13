"""Real native Word crop placements determine detector input, not hidden media."""
import io
import zipfile
from PIL import Image
from docx import Document
from lxml import etree as E
import ocr
from office_visible_image import NS


def package(tmp_path, crops, *, rotation=False, orphan=False):
    image=Image.new('RGB',(400,400),'white'); image.paste('red',(0,0,400,200))
    out=io.BytesIO();image.save(out,format='PNG')
    d=Document()
    for _ in crops:
        d.add_picture(io.BytesIO(out.getvalue()))
    buf=io.BytesIO();d.save(buf)
    path=tmp_path/'native.docx'
    with zipfile.ZipFile(buf) as z,zipfile.ZipFile(path,'w') as target:
        for n in z.namelist():
            b=z.read(n)
            if n=='word/document.xml':
                root=E.fromstring(b)
                for blip,crop in zip(root.xpath('.//a:blip',namespaces=NS),crops):
                    if crop is not None:E.SubElement(blip.getparent(),'{'+NS['a']+'}srcRect',t=crop)
                if rotation:root.xpath('.//a:xfrm',namespaces=NS)[0].set('rot','60000')
                b=E.tostring(root)
            target.writestr(n,b)
        if orphan:target.writestr('word/media/image99.png',out.getvalue())
    return path


def pixel_reader(data,**kwargs):
    return 'Hidden instruction text contains many readable words that must remain selectable today' if Image.open(io.BytesIO(data)).getpixel((0,0))==(255,0,0) else ''


def test_hidden_prose_is_not_detected_for_eight_shared_visible_diagram_crops(tmp_path,monkeypatch):
    path=package(tmp_path,['50000']*8,orphan=True)
    monkeypatch.setattr(ocr,'is_available',lambda:True);monkeypatch.setattr(ocr,'read_image_text',pixel_reader)
    assert ocr.images_of_text(path,'.docx')==[]
    assert ocr.images_of_text_no_exception(path,'.docx')==[]
    images,total=ocr._embedded_images_and_total(path,'.docx',visible_word=True)
    assert total==1 and len(images[0].placements)==8


def test_one_uncropped_shared_placement_preserves_visible_text_finding(tmp_path,monkeypatch):
    path=package(tmp_path,['50000',None])
    monkeypatch.setattr(ocr,'is_available',lambda:True);monkeypatch.setattr(ocr,'read_image_text',pixel_reader)
    assert ocr.images_of_text(path,'.docx')[0]['ruleId']=='OCR_IMAGE_OF_TEXT'


def test_unsupported_geometry_is_unread_never_full_raster_fallback(tmp_path,monkeypatch):
    path=package(tmp_path,['50000'],rotation=True)
    monkeypatch.setattr(ocr,'is_available',lambda:True)
    monkeypatch.setattr(ocr,'read_image_text',lambda *a,**k: (_ for _ in ()).throw(AssertionError('hidden raster must not be read')))
    assert ocr.images_of_text(path,'.docx')[0]['ruleId']=='OCR_IMAGE_UNREAD'


def test_invalid_crop_is_unread(tmp_path,monkeypatch):
    path=package(tmp_path,['oops'])
    monkeypatch.setattr(ocr,'is_available',lambda:True)
    assert ocr.images_of_text(path,'.docx')[0]['ruleId']=='OCR_IMAGE_UNREAD'


def test_legacy_proposal_media_enumeration_stays_raw_and_index_stable(tmp_path):
    path=package(tmp_path,['50000'],orphan=True)
    raw=ocr._embedded_images(path,'.docx')
    visible=ocr._embedded_images_and_total(path,'.docx',visible_word=True)[0]
    assert len(raw)==2 and len(visible)==1
    assert Image.open(io.BytesIO(raw[0])).size==(400,400)
    assert visible[0].media_number==1


def test_shared_placements_cannot_multiply_document_ocr_budget(tmp_path,monkeypatch):
    path=package(tmp_path,['50000']*8)
    monkeypatch.setattr(ocr,'_MAX_IMAGES',3)
    monkeypatch.setattr(ocr,'is_available',lambda:True)
    monkeypatch.setattr(ocr,'read_image_text',lambda *a,**k: (_ for _ in ()).throw(AssertionError('overbudget crop must not be read')))
    assert ocr.images_of_text(path,'.docx')[0]['ruleId']=='OCR_IMAGE_UNREAD'
