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
        # Only explicit one-based page labels, never anonymous field or xref IDs.
        for match in re.finditer(r'\bpage\s*[:= ]\s*(\d+)\b', str(row.get('locator') or row.get('location') or ''), re.I):
            if int(match[1]) > 0:
                pages.add(int(match[1]))
    return sorted(pages)


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
            body += f'<section class="pdf-evidence-pair"><h3>Page {number}</h3>'
            matched = [r for r in records if number in page_numbers([r])]
            if matched:
                refs = [str(r.get('finding_id') or 'Change ' + str(r.get('seq', index + 1))) + ' / ' + str(r.get('rule_id') or r.get('wcag') or 'criterion not recorded') for index, r in enumerate(matched)]
                body += '<p>Recorded references: ' + escape('; '.join(refs)) + '. Outcomes and before/after values are listed above.</p>'
            body += '<p>' + ('Visual appearance unchanged. Accessibility metadata or structure can change without changing the page image.' if unchanged else 'Page appearance differs. Consult the recorded edits; visual differences alone do not establish a fix.') + '</p><div class="pdf-evidence-images">'
            for label, data in zip(('Original', 'Released corrected copy'), images):
                body += '<figure><figcaption>' + label + '</figcaption><img alt="' + label + f', page {number}' + '" src="data:image/png;base64,' + base64.b64encode(data).decode('ascii') + '"></figure>'
            body += '</div></section>'
        return body
    except Exception:
        # Optional evidence cannot fail a valid release or expose parser/storage errors.
        return unavailable('the PDFs could not be rendered safely with comparable page geometry')
