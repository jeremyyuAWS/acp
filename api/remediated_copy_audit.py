"""Read saved bytes without crediting accessibility or changing any run state."""
import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
from pypdf.errors import PyPdfError

_IMAGE_TAGS = {
    '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr',
    '{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr',
    '{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}cNvPr',
}
_ROOTS = {'docx': 'word/document.xml', 'xlsx': 'xl/workbook.xml', 'pptx': 'ppt/presentation.xml'}
_ROOT_TAGS = {
    'docx': '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document',
    'xlsx': '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook',
    'pptx': '{http://schemas.openxmlformats.org/presentationml/2006/main}presentation',
}


def inspect(data, extension):
    """Inventory exact Office properties or PDF readability; never infer full compliance."""
    result = {'sha256': hashlib.sha256(data).hexdigest(), 'readable': False,
              'images': [], 'errors': [], 'accessibility_checker_pass': 'not established'}
    extension = extension.lower().lstrip('.')
    try:
        if extension == 'pdf':
            from pypdf import PdfReader
            document = PdfReader(io.BytesIO(data), strict=True)
            if document.is_encrypted:
                raise ValueError('PDF requires a password.')
            result['pages'] = len(document.pages)
            for page in document.pages:
                page.extract_text()
            result['readable'] = True
            return result
        if extension not in _ROOTS:
            raise ValueError('Unsupported file format for this audit.')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate package entries make property identity ambiguous.')
            if _ROOTS[extension] not in names or '[Content_Types].xml' not in names:
                raise ValueError('Required Office package parts are missing.')
            total = 0
            for info in archive.infolist():
                if not info.filename.endswith(('.xml', '.rels')):
                    continue
                total += info.file_size
                if info.file_size > 32 * 1024 * 1024 or total > 128 * 1024 * 1024:
                    raise ValueError('Office XML exceeds the audit size limit.')
                raw = archive.read(info)
                declarations = raw.upper().replace(b'\x00', b'')
                if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
                    raise ValueError('XML entity declarations are not supported.')
                root = ET.fromstring(raw)
                if info.filename == _ROOTS[extension] and root.tag != _ROOT_TAGS[extension]:
                    raise ValueError('Office main part has an unexpected document root.')
                for node in root.iter():
                    if node.tag not in _IMAGE_TAGS:
                        continue
                    result['images'].append({
                        'part': info.filename, 'tag': node.tag, 'id': node.get('id'),
                        'name': node.get('name'), 'description': node.get('descr', ''),
                        'title': node.get('title', ''),
                        'decorative': any(child.tag.endswith('}decorative') and
                                          child.get('val', '').lower() in {'1', 'true'}
                                          for child in node.iter()),
                    })
            result['readable'] = True
    except (ValueError, zipfile.BadZipFile, ET.ParseError, RuntimeError, PyPdfError, OSError, NotImplementedError) as exc:
        result['errors'].append(str(exc))
    return result


def audit(original, corrected, extension, *, expected_sha256=None, expected_images=None):
    """Compare exact supplied claims. Missing expectations remain explicitly unestablished."""
    before, after = inspect(original, extension), inspect(corrected, extension)
    checks = []
    if expected_sha256 is not None:
        checks.append({'check': 'recorded corrected hash',
                       'passed': after['sha256'] == expected_sha256.lower()})
    if expected_images is not None:
        for expected in expected_images:
            identity_present = all(isinstance(expected.get(key), str) and expected[key].strip()
                                   for key in ('part', 'tag', 'id'))
            matches = [row for row in after['images'] if all(
                row.get(key) == expected.get(key) for key in ('part', 'tag', 'id'))]
            fields = [key for key in ('description', 'title', 'decorative') if key in expected]
            checks.append({'check': 'recorded image properties',
                           'location': {key: expected.get(key) for key in ('part', 'tag', 'id')},
                           'passed': identity_present and bool(fields) and len(matches) == 1 and after['readable'] and
                           all(matches[0].get(key) == expected[key] for key in fields)})
    return {'original': before, 'corrected': after,
            'bytes_changed': before['sha256'] != after['sha256'], 'checks': checks,
            'supplied_claims_verified': bool(checks) and before['readable'] and after['readable'] and
                                        all(check['passed'] for check in checks),
            'all_recorded_changes_verified': 'not established',
            'accessibility_checker_pass': 'not established'}
