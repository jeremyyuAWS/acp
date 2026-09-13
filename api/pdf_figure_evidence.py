"""Exact raster evidence for a deliberately narrow existing PDF Figure association.

Never captions pages or invents MCIDs. Mixed/composited page content stays manual.
"""
from __future__ import annotations

import hashlib
import io
import math

MAX_PAGES = 64
MAX_CONTENT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_CONTENT_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 8 * 1024 * 1024
MAX_OPERATORS = 50_000


class FigureEvidenceError(ValueError):
    """Safe reason code; no source text or raw parser exceptions."""


def _reject(reason):
    raise FigureEvidenceError(reason)


def _decoded(stream, limit):
    """Decode only simple bounded streams; reject predictors and filter chains."""
    import pikepdf
    import zlib
    if not isinstance(stream, pikepdf.Stream) or int(stream.get('/Length', limit + 1)) > limit:
        _reject('pdf_figure_stream_limit')
    raw = stream.read_raw_bytes()
    if len(raw) > limit or stream.get('/DecodeParms') is not None:
        _reject('pdf_figure_stream_limit')
    filt = stream.get('/Filter')
    if filt is None:
        return raw
    if isinstance(filt, pikepdf.Array):
        if len(filt) != 1:
            _reject('pdf_figure_unsupported_stream_filter')
        filt = filt[0]
    if str(filt) != '/FlateDecode':
        _reject('pdf_figure_unsupported_stream_filter')
    decoder = zlib.decompressobj()
    output = decoder.decompress(raw, limit + 1)
    if len(output) > limit or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        _reject('pdf_figure_stream_limit')
    return output


def _content_limits(pdf):
    import pikepdf
    if len(pdf.pages) > MAX_PAGES:
        _reject('pdf_figure_document_limit')
    total, decoded = 0, []
    for page in pdf.pages:
        contents = page.obj.get('/Contents')
        streams = list(contents) if isinstance(contents, pikepdf.Array) else ([] if contents is None else [contents])
        if len(streams) > 16:
            _reject('pdf_figure_content_limit')
        parts = [_decoded(stream, MAX_CONTENT_BYTES) for stream in streams]
        page_total = sum(map(len, parts))
        total += page_total
        if page_total > MAX_CONTENT_BYTES or total > MAX_DOCUMENT_CONTENT_BYTES:
            _reject('pdf_figure_content_limit')
        decoded.append(b'\n'.join(parts))
    return decoded



def bounded_figures(pdf):
    """Preserve existing preorder locators while rejecting cyclic/huge tag trees."""
    import pikepdf
    from pdf_structure_repairs import _children
    root = pdf.Root.get('/StructTreeRoot')
    if not isinstance(root, pikepdf.Dictionary):
        return []
    stack = [(child, 0) for child in reversed(_children(root))]
    seen, figures = set(), []
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, pikepdf.Dictionary) or str(node.get('/Type')) != '/StructElem':
            continue
        identity = node.objgen if node.is_indirect else id(node)
        if depth > 32 or len(seen) >= 4000 or identity in seen:
            _reject('pdf_figure_tag_association_unavailable')
        seen.add(identity)
        if str(node.get('/S')) == '/Figure':
            figures.append(node)
        children = _children(node)
        if len(children) > 4000:
            _reject('pdf_figure_tag_association_unavailable')
        stack.extend((child, depth + 1) for child in reversed(children))
    return figures


def _figure_row(pdf, figure):
    """Bounded tag ownership checks without parsing arbitrary MCR streams."""
    import pikepdf
    from pdf_structure_repairs import _children, _writable
    if not _writable(pdf):
        _reject('pdf_figure_protected_document')
    root = pdf.Root.get('/StructTreeRoot')
    if not isinstance(root, pikepdf.Dictionary):
        _reject('pdf_figure_tag_association_unavailable')
    pages = {page.obj.objgen: i for i, page in enumerate(pdf.pages)}
    seen, owners, candidates = set(), {}, []
    stack = [(child, root, None, 0) for child in _children(root)]
    while stack:
        node, parent, inherited_page, depth = stack.pop()
        if not isinstance(node, pikepdf.Dictionary) or str(node.get('/Type')) != '/StructElem':
            _reject('pdf_figure_tag_association_unavailable')
        if (depth > 32 or len(seen) >= 4000 or not node.is_indirect or node.objgen in seen
                or not isinstance(node.get('/P'), pikepdf.Dictionary) or node['/P'].objgen != parent.objgen):
            _reject('pdf_figure_tag_association_unavailable')
        seen.add(node.objgen)
        page = node.get('/Pg', inherited_page)
        page_index = pages.get(page.objgen) if isinstance(page, pikepdf.Dictionary) else None
        content = []
        for child in _children(node):
            if type(child) is int and child >= 0:
                key = (page_index, child)
                if page_index is None or key in owners:
                    _reject('pdf_figure_duplicate_tag_mcid')
                owners[key] = node.objgen
                content.append(['mcid', child])
            elif isinstance(child, pikepdf.Dictionary) and str(child.get('/Type')) == '/StructElem':
                stack.append((child, node, page, depth + 1))
                content.append(['tag'])
            else:
                _reject('pdf_figure_tag_association_unavailable')
        if node.objgen == figure.objgen and str(node.get('/S')) == '/Figure':
            candidates.append({'node': node, 'page': page_index, 'content': content})
    if len(candidates) != 1:
        _reject('pdf_figure_tag_association_unavailable')
    tree, seen, parent_values = root.get('/ParentTree'), set(), {}
    stack = [tree]
    while stack:
        node = stack.pop()
        if not isinstance(node, pikepdf.Dictionary):
            _reject('pdf_figure_parent_tree_unavailable')
        key = node.objgen if node.is_indirect else id(node)
        if key in seen or len(seen) >= 4000:
            _reject('pdf_figure_parent_tree_unavailable')
        seen.add(key)
        nums = node.get('/Nums', [])
        if len(nums) > 8000 or len(nums) % 2:
            _reject('pdf_figure_parent_tree_unavailable')
        for index in range(0, len(nums), 2):
            key = nums[index]
            if type(key) is not int or key < 0 or key in parent_values or len(parent_values) >= 4000:
                _reject('pdf_figure_parent_tree_unavailable')
            parent_values[key] = nums[index + 1]
        kids = list(node.get('/Kids', []))
        if len(kids) > 4000:
            _reject('pdf_figure_parent_tree_unavailable')
        stack.extend(kids)
    for (page_index, mcid), owner in owners.items():
        parents = parent_values.get(pdf.pages[page_index].obj.get('/StructParents'))
        if (not isinstance(parents, pikepdf.Array) or mcid >= len(parents)
                or not isinstance(parents[mcid], pikepdf.Dictionary) or parents[mcid].objgen != owner):
            _reject('pdf_figure_parent_tree_unavailable')
    return candidates[0]


def _instructions(content):
    import pikepdf
    with pikepdf.Pdf.new() as scratch:
        stream = scratch.make_stream(content)
        yield from pikepdf.parse_content_stream(stream)


def _matrix(values):
    if len(values) != 6:
        _reject('pdf_figure_graphics_malformed')
    try:
        out = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        _reject('pdf_figure_graphics_malformed')
    if not all(math.isfinite(value) and abs(value) <= 1_000_000 for value in out):
        _reject('pdf_figure_graphics_malformed')
    return out


def _compose(left, right):
    a, b, c, d, e, f = left
    aa, bb, cc, dd, ee, ff = right
    return _matrix((a*aa+c*bb, b*aa+d*bb, a*cc+c*dd, b*cc+d*dd,
                    a*ee+c*ff+e, b*ee+d*ff+f))


def _inherited(page, key):
    import pikepdf
    node, seen = page.obj, set()
    for _depth in range(32):
        identity = node.objgen if node.is_indirect else id(node)
        if identity in seen:
            _reject('pdf_figure_graphics_malformed')
        seen.add(identity)
        if node.get(key) is not None:
            return node[key]
        node = node.get('/Parent')
        if not isinstance(node, pikepdf.Dictionary):
            return None
    _reject('pdf_figure_graphics_malformed')


def _raster(pdf, page, mcid, content):
    import pikepdf
    allowed = {'q', 'Q', 'cm', 'BDC', 'BMC', 'EMC', 'Do'}
    matrix, stack, marked = (1., 0., 0., 1., 0., 0.), [], []
    hits, sections, paint_count = [], 0, 0
    for count, instruction in enumerate(_instructions(content)):
        if count >= MAX_OPERATORS or not hasattr(instruction, 'operator'):
            _reject('pdf_figure_content_limit')
        op, args = str(instruction.operator), instruction.operands
        if op not in allowed:
            # Reject even outside the Figure: text, paths, forms, clipping and
            # transparency can obscure pixels or make the page a composite.
            _reject('pdf_figure_mixed_or_composited_page')
        if op == 'q':
            if args or len(stack) >= 32:
                _reject('pdf_figure_graphics_malformed')
            stack.append(matrix)
        elif op == 'Q':
            if args or not stack:
                _reject('pdf_figure_graphics_malformed')
            matrix = stack.pop()
        elif op == 'cm':
            matrix = _compose(matrix, _matrix(args))
        elif op in {'BDC', 'BMC'}:
            if len(marked) >= 32 or any(marked):
                _reject('pdf_figure_nested_marked_content')
            if op == 'BMC':
                if len(args) != 1:
                    _reject('pdf_figure_graphics_malformed')
                marked.append(False)
                continue
            if len(args) != 2:
                _reject('pdf_figure_graphics_malformed')
            props = args[1]
            if isinstance(props, pikepdf.Name):
                props = page.obj.get('/Resources', {}).get('/Properties', {}).get(props)
            target = isinstance(props, pikepdf.Dictionary) and props.get('/MCID') == mcid
            if target and (str(args[0]) != '/Figure' or any(props.get(key) is not None for key in ('/ActualText', '/Alt', '/E', '/OC'))):
                _reject('pdf_figure_semantic_override')
            marked.append(target)
            sections += int(target)
        elif op == 'EMC':
            if args or not marked:
                _reject('pdf_figure_graphics_malformed')
            marked.pop()
        elif op == 'Do':
            paint_count += 1
            if len(args) != 1 or not marked or not marked[-1]:
                _reject('pdf_figure_unassociated_or_multiple_image')
            image = page.obj.get('/Resources', {}).get('/XObject', {}).get(args[0])
            if not isinstance(image, pikepdf.Stream) or str(image.get('/Subtype')) != '/Image':
                _reject('pdf_figure_form_or_nonraster')
            a, b, c, d, e, f = matrix
            if b != 0 or c != 0 or a <= 0 or d <= 0:
                _reject('pdf_figure_transformed_or_clipped')
            box = _inherited(page, '/CropBox')
            if box is None:
                box = _inherited(page, '/MediaBox')
            if box is None or len(box) != 4:
                _reject('pdf_figure_graphics_malformed')
            x0, y0, x1, y1 = map(float, box)
            if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or not (x0 <= e < e+a <= x1 and y0 <= f < f+d <= y1):
                _reject('pdf_figure_transformed_or_clipped')
            width, height = image.get('/Width'), image.get('/Height')
            if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
                    or not math.isclose(a / width, d / height, rel_tol=1e-9, abs_tol=1e-12)):
                _reject('pdf_figure_nonuniform_visual_scale')
            hits.append(image)
    if stack or marked or sections != 1:
        _reject('pdf_figure_graphics_malformed')
    if len(hits) != 1 or paint_count != 1:
        _reject('pdf_figure_unassociated_or_multiple_image')
    return hits[0]


def exact_figure_image(pdf, figure):
    """Return pixels only when unique tags and paint establish a sole opaque raster.

    The caller still needs independent caption validation; association is not
    proof of caption semantics or whole-document accessibility.
    """
    import pikepdf
    try:
        if pdf.is_encrypted or pdf.Root.get('/Perms') is not None or pdf.Root.get('/OutputIntents'):
            _reject('pdf_figure_protected_document')
        decoded = _content_limits(pdf)
        row = _figure_row(pdf, figure)
        if any(figure.get(key) is not None for key in ('/ActualText', '/E', '/Ref')):
            _reject('pdf_figure_semantic_override')
        if not figure.is_indirect or figure.get('/Pg') is None:
            _reject('pdf_figure_tag_association_unavailable')
        links = row['content']
        if row['page'] is None or len(links) != 1 or links[0][0] != 'mcid':
            _reject('pdf_figure_tag_association_unavailable')
        page = pdf.pages[row['page']]
        if (float(_inherited(page, '/UserUnit') or 1) != 1 or int(_inherited(page, '/Rotate') or 0)) or page.obj.get('/Group') is not None or page.obj.get('/Annots'):
            _reject('pdf_figure_transformed_or_composited_page')
        resources = _inherited(page, '/Resources') or {}
        color_spaces = resources.get('/ColorSpace', {})
        if any(color_spaces.get(key) is not None for key in ('/DefaultRGB', '/DefaultGray', '/DefaultCMYK')):
            _reject('pdf_figure_default_color_transform')
        image = _raster(pdf, page, links[0][1], decoded[row['page']])
        if any(image.get(key) is not None for key in ('/Mask', '/SMask', '/Alternates', '/OPI', '/Decode', '/Matte', '/Intent', '/OC')) or image.get('/ImageMask', False) or int(image.get('/SMaskInData', 0)) or image.get('/Interpolate', False):
            _reject('pdf_figure_mask_or_pixel_transform')
        width, height = image.get('/Width'), image.get('/Height')
        if type(width) is not int or type(height) is not int or not (4 <= width <= 4096 and 4 <= height <= 4096) or width*height > MAX_IMAGE_PIXELS:
            _reject('pdf_figure_image_limit')
        if image.get('/BitsPerComponent') != 8 or str(image.get('/ColorSpace')) not in {'/DeviceRGB', '/DeviceGray'}:
            _reject('pdf_figure_unsupported_pixels')
        filt = image.get('/Filter')
        if isinstance(filt, pikepdf.Array):
            if len(filt) != 1:
                _reject('pdf_figure_unsupported_pixels')
            filt = filt[0]
        from PIL import Image
        if str(filt) == '/DCTDecode':
            if int(image.get('/Length', MAX_IMAGE_BYTES + 1)) > MAX_IMAGE_BYTES or image.get('/DecodeParms') is not None:
                _reject('pdf_figure_image_limit')
            encoded = image.read_raw_bytes()
            if len(encoded) > MAX_IMAGE_BYTES:
                _reject('pdf_figure_image_limit')
            pil = Image.open(io.BytesIO(encoded))
            if pil.mode not in {'RGB', 'L'} or pil.size != (width, height) or pil.info.get('icc_profile') or pil.getexif():
                _reject('pdf_figure_unsupported_pixels')
            pil.load()
        else:
            mode = 'RGB' if str(image['/ColorSpace']) == '/DeviceRGB' else 'L'
            expected = width * height * (3 if mode == 'RGB' else 1)
            raw = _decoded(image, min(MAX_IMAGE_BYTES, expected))
            if len(raw) != expected:
                _reject('pdf_figure_pixel_size_mismatch')
            pil = Image.frombytes(mode, (width, height), raw)
        output = io.BytesIO()
        pil.save(output, format='PNG')
        png = output.getvalue()
        if len(png) > MAX_IMAGE_BYTES:
            _reject('pdf_figure_image_limit')
        return {'image_bytes': png, 'image_sha256': hashlib.sha256(png).hexdigest(),
                'page': row['page'] + 1, 'mcid': links[0][1], 'method': 'unique-mcid-parenttree-sole-opaque-raster-v1'}
    except FigureEvidenceError:
        raise
    except Exception:
        _reject('pdf_figure_tag_or_pixels_unavailable')
