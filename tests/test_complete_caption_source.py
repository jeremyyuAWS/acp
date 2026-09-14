"""Faithful source derivation must not silently drop author-written caption content."""
from html import escape, unescape
import re
import zipfile
import remediate_office
from test_remediate_office import _make_docx_with_body, _doc_xml


def test_complete_adjacent_caption_reaches_alt_and_preserves_original(tmp_path):
    caption = ' '.join(['Connect the controller and inspect the hose before operating the device.'] * 5)
    caption += ' Final step: Disconnect the power & drain the container.'
    source = tmp_path / 'caption.docx'
    _make_docx_with_body(source,
        '<w:p><w:r><w:drawing><wp:docPr id="1" name="Picture 1"/></w:drawing></w:r></w:p>'
        f'<w:p><w:r><w:t>{escape("Figure 2: " + caption)}</w:t></w:r></w:p>')
    original = source.read_bytes()
    output, applied, skipped = remediate_office.remediate_office(source, ai_enabled=False)
    assert source.read_bytes() == original
    document = _doc_xml(output)
    alt = unescape(re.search(r'descr="([^"]*)"', document).group(1))
    assert alt == caption
    assert 'Final step: Disconnect the power & drain the container.' in alt
    assert escape('Figure 2: ' + caption) in document
    assert any('adjacent caption' in row for row in applied)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
