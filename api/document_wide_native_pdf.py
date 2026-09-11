"""Read-only native-PDF admission and explicit tagged Figure region evidence."""
import hashlib
import io
import math

import pikepdf

MAX_BYTES = 20 * 1024 * 1024


def validate_native_pdf(data, *, source_sha256=None):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise ValueError('document_too_large')
    if source_sha256 is not None and hashlib.sha256(data).hexdigest() != source_sha256:
        raise ValueError('document_source_changed')
    if not data.startswith(b'%PDF-'):
        raise ValueError('document_format_unsupported')
    try:
        with pikepdf.open(io.BytesIO(data), attempt_recovery=False) as pdf:
            if pdf.is_encrypted or not 0 < len(pdf.pages) <= 100:
                raise ValueError('document_native_pdf_unreadable_or_over_limit')
            if pdf.check_pdf_syntax():
                raise ValueError('document_native_pdf_unreadable_or_over_limit')
    except Exception as exc:
        raise ValueError('document_native_pdf_unreadable_or_over_limit') from exc
    return data


def figure_regions(data):
    """Only standard explicit layout boxes on simple, unrotated page coordinates.

    No inferred image ordering, area matching, anonymous MCID guessing, or visual
    association from two tags merely sharing a page. Overlapping boxes are excluded.
    """
    from experiments.document_wide_ai.application.production_adapters import collect_pdf_figures, pdf_figure_locators
    regions = {}
    with pikepdf.open(io.BytesIO(data)) as pdf:
        figures = collect_pdf_figures(pdf.Root.get('/StructTreeRoot'))
        locators = pdf_figure_locators(figures, pdf)
        for figure in figures:
            locator = locators[id(figure)]
            try:
                page_index = int(locator.split(':')[2]) - 1
                if not 0 <= page_index < len(pdf.pages):
                    continue
                page = pdf.pages[page_index]
                media = tuple(float(v) for v in page.mediabox)
                crop = tuple(float(v) for v in page.cropbox)
                if media != crop or media[:2] != (0, 0) or int(page.obj.get('/Rotate', 0)) % 360 or float(page.obj.get('/UserUnit', 1)) != 1:
                    continue
                attrs = figure.get('/A')
                attrs = list(attrs) if isinstance(attrs, pikepdf.Array) else [attrs]
                boxes = [tuple(float(v) for v in a['/BBox']) for a in attrs
                         if isinstance(a, pikepdf.Dictionary) and a.get('/O') == pikepdf.Name('/Layout') and '/BBox' in a]
                if len(boxes) != 1:
                    continue
                box = boxes[0]
                if len(box) != 4 or not all(math.isfinite(v) for v in box):
                    continue
                x0, y0, x1, y1 = box
                if not 0 <= x0 < x1 <= media[2] or not 0 <= y0 < y1 <= media[3]:
                    continue
                regions[locator] = (page_index, box, media[2:])
            except (TypeError, ValueError, KeyError, IndexError):
                continue
    ambiguous = set()
    for key, (page, a, _) in regions.items():
        for other, (other_page, b, _) in regions.items():
            if key != other and page == other_page and max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]):
                ambiguous.update((key, other))
    return {key: value for key, value in regions.items() if key not in ambiguous}


def region_image(data, region):
    from PIL import Image
    from experiments.document_wide_ai.packaging.pdf_images import render_pdf_page
    page, (x0, y0, x1, y1), (width, height) = region
    rendered = render_pdf_page(data, page)
    if not rendered:
        return None
    with Image.open(io.BytesIO(rendered)) as image:
        bounds = (math.floor(x0 * image.width / width), math.floor((height-y1) * image.height / height),
                  math.ceil(x1 * image.width / width), math.ceil((height-y0) * image.height / height))
        crop = image.crop(bounds)
        try:
            out = io.BytesIO()
            crop.save(out, format='PNG')
            return out.getvalue() if out.tell() <= 1024 * 1024 else None
        finally:
            crop.close()
