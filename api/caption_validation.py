"""Narrow independent caption evidence gate; transport/structure success is not semantics.

Only exact flat fills and one/two isolated flat circles/squares are understood.
Unsupported imagery remains manual. OCR can contradict claims, never prove them.
No model, provider, store or network calls occur here.
"""
import hashlib
import re
from io import BytesIO

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 1_000_000
COLORS = ('red', 'blue', 'green', 'yellow', 'black', 'white', 'gray')
SHAPES = ('circle', 'square', 'rectangle', 'triangle')


def _color(rgb):
    # Exact CSS named-color primaries only: no hue threshold establishes semantics.
    return {(255, 0, 0): 'red', (0, 0, 255): 'blue', (0, 128, 0): 'green',
            (255, 255, 0): 'yellow', (0, 0, 0): 'black',
            (255, 255, 255): 'white', (128, 128, 128): 'gray'}.get(rgb)


def _facts(data):
    from PIL import Image, ImageChops, ImageDraw
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        return None
    try:
        with Image.open(BytesIO(data)) as source:
            w, h = source.size
            if min(w, h) < 16 or w * h > MAX_PIXELS or getattr(source, 'n_frames', 1) != 1:
                return None
            if source.mode not in ('RGB', 'RGBA', 'L'):
                return None
            if source.mode == 'RGBA' and source.getchannel('A').getextrema() != (255, 255):
                return None
            image = source.convert('RGB')
        histogram = image.getcolors(8)
        if not histogram:
            return None
        if len(histogram) == 1:
            color = _color(histogram[0][1])
            if color:
                return {'kind': 'solid_fill', 'color': color}
            return None
        if len(histogram) not in (2, 3):
            return None
        background = max(histogram)[1]
        if _color(background) != 'white':
            return None
        objects = []
        pixels = image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()
        for _, rgb in histogram:
            if rgb == background:
                continue
            color = _color(rgb)
            if color is None or color in ('white', 'gray', 'black'):
                return None
            mask = Image.new('1', image.size)
            mask.putdata([pixel == rgb for pixel in pixels])
            box = mask.getbbox()
            if not box or min(box[0], box[1], w-box[2], h-box[3]) < 2:
                return None
            bw, bh = box[2]-box[0], box[3]-box[1]
            if min(bw, bh) < 12 or abs(bw-bh) > 1:
                return None
            shape = None
            # Exact raster equality deliberately excludes photos, approximations and holes.
            for name, draw in [('square', 'rectangle'), ('circle', 'ellipse')]:
                ideal = Image.new('1', image.size)
                painter = ImageDraw.Draw(ideal)
                getattr(painter, draw)((box[0], box[1], box[2]-1, box[3]-1), fill=1)
                if ImageChops.logical_xor(mask, ideal).getbbox() is None:
                    shape = name
                    break
            if shape is None:
                return None
            objects.append({'color': color, 'shape': shape, 'box': list(box)})
        objects.sort(key=lambda obj: obj['box'][0])
        if len(objects) == 2 and objects[0]['box'][2] >= objects[1]['box'][0]:
            return None
        return {'kind': 'flat_shapes', 'background': 'white', 'objects': objects}
    except Exception:
        # Invalid/unsupported pixels do not become evidence that a description is right.
        return None


def _normalize(text):
    return re.sub(r'\s+', ' ', text.lower().strip().rstrip('.')).strip()


def _approved_templates(facts):
    if facts['kind'] == 'solid_fill':
        color = facts['color']
        return {f'the image is a solid {color} color', f'a solid {color} color',
                f'a solid {color} image', f'the image is solid {color}'}, f'The image is a solid {color} color.'
    objects = facts['objects']
    if len(objects) == 1:
        obj = objects[0]
        sentence = f'a {obj["color"]} {obj["shape"]} on a white background'
    else:
        left, right = objects
        sentence = (f'a {left["color"]} {left["shape"]} on the left and a '
                    f'{right["color"]} {right["shape"]} on the right on a white background')
    return {sentence, *(f'the image {verb} {sentence}' for verb in ('shows', 'displays', 'contains'))}, sentence[0].upper()+sentence[1:]+'.'


def validate_caption(caption, image_bytes, *, ocr_tokens=None):
    """Return validated/rejected/needs_manual; only validated permits automatic writing.

    Candidate text is never evidence. A known contradiction is rejected; claims
    outside the finite grammar remain unknown even if structural checks passed.
    """
    evidence = {'version': 'caption-pixels.v1', 'method': 'unsupported',
                'image_sha256': hashlib.sha256(image_bytes).hexdigest() if isinstance(image_bytes, bytes) and len(image_bytes) <= MAX_BYTES else None}
    def result(status, reason, canonical=None):
        return {'approved': status == 'validated', 'status': status,
                'reason_codes': [reason], 'evidence': evidence, 'canonical_caption': canonical}
    if not isinstance(caption, str) or not caption.strip() or len(caption) > 4000:
        return result('needs_manual', 'caption_input_unavailable')
    text = _normalize(caption)
    # OCR is only a negative constraint; neither OCR nor model agreement approves prose.
    if isinstance(ocr_tokens, (list, tuple)):
        if len(ocr_tokens) > 1000 or any(isinstance(item, str) and len(item) > 256 for item in ocr_tokens):
            return result('needs_manual', 'ocr_evidence_input_limit')
        visible_numbers = {token for item in ocr_tokens if isinstance(item, str)
                           for token in re.findall(r'\b\d+(?:\.\d+)?\b', item)}
        evidence['ocr_number_count'] = len(visible_numbers)
        global_denials = {'the chart does not provide any numerical values',
                          'the chart has no numerical values',
                          'the image has no numbers', 'there are no numbers in the image'}
        if visible_numbers and text in global_denials:
            return result('rejected', 'visible_numbers_denied')
        claimed_numbers = set(re.findall(r'\b\d+(?:\.\d+)?\b', text))
        if claimed_numbers - visible_numbers:
            return result('needs_manual', 'number_claim_unverified_by_ocr')
    facts = _facts(image_bytes)
    if facts is None:
        return result('needs_manual', 'pixel_semantics_unsupported')
    evidence.update(method='exact_flat_raster', facts=facts)
    templates, canonical = _approved_templates(facts)
    if text in templates:
        return result('validated', 'exact_pixel_facts_match', canonical)
    # Reject only complete finite factual statements. Free regex extraction would
    # misread negation, scope or extra assertions as facts that the caption claims.
    color_pattern = '(' + '|'.join(COLORS) + ')'
    shape_pattern = '(' + '|'.join(SHAPES) + ')'
    if facts['kind'] == 'solid_fill':
        match = re.fullmatch(r'(?:the image is a solid|a solid) ' + color_pattern + r' (?:color|image)', text)
        if match and match[1] != facts['color']:
            return result('rejected', 'pixel_color_contradiction', canonical)
    else:
        prefix = r'(?:the image (?:shows|displays|contains) )?'
        if len(facts['objects']) == 1:
            pattern = prefix + r'a ' + color_pattern + ' ' + shape_pattern + r' on a ' + color_pattern + r' background'
            match = re.fullmatch(pattern, text)
            if match:
                obj = facts['objects'][0]
                if (match[1], match[2], match[3]) != (obj['color'], obj['shape'], 'white'):
                    return result('rejected', 'pixel_shape_or_color_contradiction', canonical)
        else:
            pattern = (prefix + r'a ' + color_pattern + ' ' + shape_pattern + r' on the left and a '
                       + color_pattern + ' ' + shape_pattern + r' on the right on a ' + color_pattern + r' background')
            match = re.fullmatch(pattern, text)
            if match:
                left, right = facts['objects']
                expected = (left['color'], left['shape'], right['color'], right['shape'], 'white')
                if match.groups() != expected:
                    return result('rejected', 'pixel_shape_or_color_contradiction', canonical)
    return result('needs_manual', 'semantic_claims_outside_validated_grammar', canonical)
