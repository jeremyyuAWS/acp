"""Native controls prove a specific write, never substitute for a native UI pass."""
import json
from pathlib import Path
import runpy
import zipfile
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]


def test_generated_controls_contain_real_alt_write_and_preserve_image(tmp_path):
    build=runpy.run_path(str(ROOT/'scripts/build_native_checker_controls.py'))['build_controls']
    manifest=build(tmp_path)
    assert len(manifest['files'])==8
    with zipfile.ZipFile(tmp_path/'word-missing-alt.docx') as original, zipfile.ZipFile(tmp_path/'word-approved-alt-corrected.docx') as corrected:
        ox=etree.fromstring(original.read('word/document.xml')); cx=etree.fromstring(corrected.read('word/document.xml'))
        ns={'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}
        before=ox.find('.//wp:docPr',ns); after=cx.find('.//wp:docPr',ns)
        assert before.get('descr') is None and before.get('title') is None
        assert after.get('descr')=='Two blue bars with the second taller than the first'
        assert original.read('word/media/image1.png')==corrected.read('word/media/image1.png')
        after.attrib.pop('descr')
        assert etree.tostring(ox)==etree.tostring(cx)


def test_retained_native_evidence_distinguishes_repair_from_universal_pdfua():
    report=json.loads((ROOT/'docs/evidence/native-checkers-2026-09-12/verapdf-ua1-results.json').read_text())['report']
    rows={Path(job['itemDetails']['name']).name:job['validationResult'][0] for job in report['jobs']}
    assert rows['pdf-good-control.pdf']['compliant'] is True
    assert rows['pdf-bad-untagged-control.pdf']['compliant'] is False
    before=rows['pdf-tagged-original.pdf']; after=rows['pdf-tagged-corrected.pdf']
    assert before['compliant'] is False and after['compliant'] is False
    assert any(r['clause']=='7.5' for r in before['details']['ruleSummaries'])
    assert not any(r['clause']=='7.5' for r in after['details']['ruleSummaries'])
    word=json.loads((ROOT/'docs/evidence/native-checkers-2026-09-12/word-assistant-observation.json').read_text())
    results={r['file']:r for r in word['results']}
    assert results['word-missing-alt.docx']['missing_alt_text']==1
    assert results['word-approved-alt-corrected.docx']['missing_alt_text']==0
    assert word['scope'].startswith('Isolated synthetic')
