"""Optional page evidence, grounded in the exact published PDF version.

Never download a live source or infer a visible repair from a metadata edit.
"""
import base64
from contextlib import closing
from hashlib import sha256
from html import escape
import re

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 3
MAX_EDGE = 900


def target_locators(row):
    """Only writer-minted, one-based page locators; object IDs are not pages."""
    tokens = set()
    for key in ('locator', 'location', 'note'):
        tokens.update(re.findall(r'(?<![\w:])pdf:(?:fig|field):[1-9]\d*:\d+(?![\w:])', str(row.get(key) or '')[:4000]))
    return sorted(tokens)


def evidence_location(row):
    locators = target_locators(row)
    return '; '.join(locators) if locators else None


def evidence_links(row):
    return ' '.join(f'<a href="#pdf-evidence-page-{p}">Page {p} evidence</a>' for p in page_numbers([row])[:MAX_PAGES])


def render_pairs(source, candidate, pages):
    import io
    import pypdfium2 as pdfium
    if max(len(source), len(candidate)) > MAX_BYTES:
        raise ValueError('PDF exceeds the visual evidence size limit')
    with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(candidate) as after:
        if len(before) != len(after):
            raise ValueError('Page counts differ; comparable page mapping is unavailable')
        pairs = []
        for number in pages[:MAX_PAGES]:
            if number < 1 or number > len(before):
                raise ValueError('Recorded page is unavailable')
            with closing(before[number - 1]) as a, closing(after[number - 1]) as b:
                if a.get_size() != b.get_size():
                    raise ValueError('Page geometry changed; comparable page mapping is unavailable')
                scale = min(1, MAX_EDGE / max(a.get_size()))
                images = []
                for page in (a, b):
                    with closing(page.render(scale=scale)) as bitmap:
                        image = bitmap.to_pil()
                        stream = io.BytesIO()
                        image.save(stream, format='PNG')
                        images.append(stream.getvalue())
                pairs.append((number, images, images[0] == images[1]))
        return pairs


def page_numbers(records):
    pages = set()
    for row in records:
        value = row.get('page_number', row.get('page'))
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            pages.add(value)
        for value in row.get('pages') or [] if isinstance(row.get('pages'), (list, tuple)) else []:
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                pages.add(value)
        pages.update(int(loc.split(':')[2]) for loc in target_locators(row))
        # Only explicit one-based page labels, never anonymous field or xref IDs.
        for match in re.finditer(r'\bpage\s*[:= ]\s*(\d+)\b', str(row.get('locator') or row.get('location') or ''), re.I):
            if int(match[1]) > 0:
                pages.add(int(match[1]))
    return sorted(pages)


def field_crops(source, candidate, records):
    """Crop only exact fields with unchanged, unrotated zero-origin geometry."""
    import io
    from PIL import Image
    import pypdfium2 as pdfium
    from experiments.document_wide_ai.packaging.pdf_packager import package_pdf
    old, new = package_pdf(source, max_text_chars=60000), package_pdf(candidate, max_text_chars=60000)
    crops = []
    locators = sorted({loc for row in records for loc in target_locators(row) if loc.startswith('pdf:field:')})
    with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(candidate) as after:
        for locator in locators[:MAX_PAGES]:
            a, b = old.field_by_locator(locator), new.field_by_locator(locator)
            if (not a or not b or not a.rectangle or a.rectangle != b.rectangle
                    or a.page_index != b.page_index or a.page_index is None
                    or a.preserved_state_sha256 != b.preserved_state_sha256):
                continue
            with closing(before[a.page_index]) as page, closing(after[a.page_index]) as corrected:
                width, height = page.get_size()
                if (page.get_rotation() or corrected.get_rotation() or corrected.get_size() != (width, height)
                        or page.get_bbox() != (0, 0, width, height) or corrected.get_bbox() != page.get_bbox()):
                    continue
            x0, y0, x1, y1 = a.rectangle
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                continue
            pair = render_pairs(source, candidate, [a.page_index + 1])[0]
            images = []
            for data in pair[1]:
                image = Image.open(io.BytesIO(data))
                sx, sy = image.width / width, image.height / height
                box = (max(0, int((x0 - 32) * sx)), max(0, int((height - y1 - 32) * sy)),
                       min(image.width, int((x1 + 32) * sx + 1)), min(image.height, int((height - y0 + 32) * sy + 1)))
                stream = io.BytesIO()
                image.crop(box).save(stream, format='PNG')
                images.append(stream.getvalue())
            crops.append((locator, images, a.current_tu, b.current_tu))
    return crops


def build_visual_evidence(store, scan_id, owner, name, outcome, records):
    if not name.lower().endswith('.pdf') or not records:
        return ''
    heading = '<h2>Original and released PDF evidence</h2>'
    def unavailable(reason):
        return heading + '<p>Page images unavailable: ' + escape(reason) + '. Textual before and after evidence remains above.</p>'
    expected = outcome.get('artifact_digest')
    if outcome.get('status') != 'published' or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(expected or '')):
        return unavailable('an exact published artifact digest was not recorded')
    try:
        import blob
        record = store.get_file_record(scan_id, name) or {}
        candidate = blob.download_report_evidence(owner, scan_id, name, max_bytes=MAX_BYTES)
        if not candidate:
            return unavailable('the saved corrected PDF is unavailable')
        if len(candidate) > MAX_BYTES:
            return unavailable('the corrected PDF exceeds the visual evidence size limit')
        if 'sha256:' + sha256(candidate).hexdigest() != expected:
            return unavailable('the current saved copy differs from this release; images from another version are not shown')
        source = blob.download_report_evidence(owner, scan_id, name, original=True, checksum=record.get('checksum'), max_bytes=MAX_BYTES)
        if not source:
            return unavailable('the cached original PDF is unavailable')
        if len(source) > MAX_BYTES:
            return unavailable('the original PDF exceeds the visual evidence size limit')
        pages = page_numbers(records)
        # A first-page preview is explicitly orientation, not asserted target geometry.
        orientation = not pages
        pairs = render_pairs(source, candidate, pages or [1])
        body = heading + '<p>Cached original SHA-256: ' + sha256(source).hexdigest() + '<br>Released candidate SHA-256: ' + expected[7:] + '</p>'
        body += '<p>The corrected images match the recorded release digest. Images do not prove semantic accessibility; use the change values and verification outcomes above.</p>'
        if orientation:
            body += '<p>Finding page locations were not recorded. Page 1 is an orientation preview, not a located finding.</p>'
        if len(pages) > MAX_PAGES:
            body += f'<p>Showing {MAX_PAGES} of {len(pages)} recorded pages to keep this report compact.</p>'
        for number, images, unchanged in pairs:
            body += f'<section class="pdf-evidence-pair" id="pdf-evidence-page-{number}"><h3>Page {number}</h3>'
            matched = [r for r in records if number in page_numbers([r])]
            if matched:
                refs = [str(r.get('finding_id') or 'Change ' + str(r.get('seq', index + 1))) + ' / ' + str(r.get('rule_id') or r.get('wcag') or 'criterion not recorded') for index, r in enumerate(matched)]
                body += '<p>Recorded references: ' + escape('; '.join(refs)) + '. Outcomes and before/after values are listed above.</p>'
            body += '<p>' + ('Visual appearance unchanged. Accessibility metadata or structure can change without changing the page image.' if unchanged else 'Page appearance differs. Consult the recorded edits; visual differences alone do not establish a fix.') + '</p><div class="pdf-evidence-images">'
            for label, data in zip(('Original', 'Released corrected copy'), images):
                body += '<figure><figcaption>' + label + '</figcaption><img alt="' + label + f', page {number}' + '" src="data:image/png;base64,' + base64.b64encode(data).decode('ascii') + '"></figure>'
            body += '</div></section>'
        try:
            crops = field_crops(source, candidate, records)
        except Exception:
            crops = []
        for locator, images, old_name, new_name in crops:
            body += '<section class="pdf-evidence-pair"><h3>Form field: ' + escape(locator) + '</h3><p>Located crop from unchanged field geometry. Accessible name (/TU): <strong>' + escape(old_name or '(not set)') + '</strong> → <strong>' + escape(new_name or '(not set)') + '</strong>. This property can change without changing appearance.</p><div class="pdf-evidence-images pdf-evidence-crops">'
            for label, data in zip(('Original field', 'Released field'), images):
                body += '<figure><figcaption>' + label + '</figcaption><img alt="' + label + '" src="data:image/png;base64,' + base64.b64encode(data).decode('ascii') + '"></figure>'
            body += '</div></section>'
        if any(target_locators(row) for row in records) and not crops:
            body += '<p>Located component crops are unavailable without comparable verified geometry; full-page evidence is retained.</p>'
        return body
    except Exception:
        # Optional evidence cannot fail a valid release or expose parser/storage errors.
        return unavailable('the PDFs could not be rendered safely with comparable page geometry')
