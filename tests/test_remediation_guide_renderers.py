"""Offline audit guides must survive both production report renderers truthfully."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))

RUN = {'id': 'guide-run', 'completed_at': '2026-09-11T00:00:00', 'avg_score': 50}
META = {'target': 'WCAG 2.1 AA', 'version': '3', 'hash': 'abc'}
FILES = [{'file': 'Patient.pdf', 'score': 50, 'compliant': False, 'status': 'done',
          'issues': [{'wcag': 'SC_1_1_1', 'severity': 'CRITICAL', 'location': 'Page 3, Figure 2'}]}]


def _documents():
    return [{'file': 'Patient.pdf', 'format': 'PDF',
             'artifact': {'display': 'saved copy SHA-256 abc123'},
             'remaining': [{'priority': 'High', 'criterion': '1.1.1', 'title': 'Image description',
                            'location': 'Page 3, Figure 2', 'status': 'Suggested — not applied',
                            'recommendation': 'Describe the parking symbol in its context.',
                            'proposed_value': 'Parking <P> & entrance',
                            'reason': 'The symbol helps the reader locate the entrance.',
                            'editor_steps': ['Open the Tags panel.', 'Set the figure alternate text.'],
                            'technical_status': 'Not checked on a saved copy',
                            'human_status': 'Not recorded'}],
             'applied': [{'criterion': '3.1.1', 'title': 'Document language', 'location': 'Document properties',
                          'status': 'Saved', 'original_value': 'Missing', 'saved_value': 'en-US',
                          'technical_status': 'Passed on saved copy', 'human_status': 'Not recorded'}]}]


def test_tagged_guide_uses_evidence_and_escapes_suggestions(monkeypatch):
    import remediation_audit_guide
    from report_tagged import _render_html
    seen = []
    def guide(*args):
        seen.append(args)
        return _documents()
    monkeypatch.setattr(remediation_audit_guide, 'build_remediation_audit_guide', guide)
    evidence, decisions, facts = [{'file': 'Patient.pdf'}], {'x': 'y'}, {'ai_calls_total': 2}
    rendered = _render_html(RUN, FILES, META, facts, decisions, evidence)
    assert seen == [(FILES, decisions, evidence, facts)]
    assert 'Page 3, Figure 2' in rendered
    assert 'Parking &lt;P&gt; &amp; entrance' in rendered
    assert 'Suggested value — not saved' in rendered
    assert 'Technical check: Passed on saved copy' in rendered
    assert 'Meaning confirmation: Not recorded' in rendered
    assert 'saved copy SHA-256 abc123' in rendered
    assert '<li>Set the figure alternate text.</li>' in rendered
    assert 'proposals were reviewed by a human' not in rendered
    assert rendered.index('What to address next') < rendered.index('Recorded changes')


def test_fallback_pdf_contains_the_offline_guide(monkeypatch):
    import remediation_audit_guide
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate
    import pikepdf
    monkeypatch.setattr(remediation_audit_guide, 'build_remediation_audit_guide', lambda *args: _documents())
    styles = getSampleStyleSheet()
    elements = report._remediation_guide_section(FILES, {}, [], {}, styles['Heading2'], styles['Normal'], styles['Normal'], styles['Normal'])
    buf = io.BytesIO()
    SimpleDocTemplate(buf).build(elements)
    with pikepdf.open(io.BytesIO(buf.getvalue())) as pdf:
        assert len(pdf.pages) > 0
    from pdfminer.high_level import extract_text
    text = extract_text(io.BytesIO(buf.getvalue()))
    for value in ['Your remediation guide', 'Page 3, Figure 2', 'Parking <P> & entrance', 'Set the figure alternate text.', 'en-US', 'Not recorded', 'abc123']:
        assert value in text


def test_fallback_approval_does_not_claim_human_confirmation():
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    evidence = [{'file': 'Patient.pdf', 'applied': [{'criterion': 'SC_1_1_1', 'value': 'Parking',
                  'before': 'Missing', 'after': 'Parking', 'decision': 'approved', 'reviewer': 'system'}], 'proposed': []}]
    elements = report._evidence_section(evidence, ss['Heading2'], ss['Normal'], ss['Normal'], ss['Normal'])
    from reportlab.platypus import Table
    def texts(items):
        for item in items:
            if isinstance(item, list):
                yield from texts(item)
            elif isinstance(item, Table):
                yield from texts(item._cellvalues)
            elif hasattr(item, 'getPlainText'):
                yield item.getPlainText()
    text = ' '.join(texts(elements))
    assert 'approved by system' in text
    assert 'human-confirmed' not in text
    assert 'approval does not confirm meaning' in text


def test_tagged_thumbnail_rejects_remote_or_active_content():
    from report_tagged import _safe_guide_thumb
    assert _safe_guide_thumb('https://example.test/image.png') == ''
    assert _safe_guide_thumb('data:image/svg+xml;base64,PHN2Zz4=') == ''
    assert _safe_guide_thumb('data:image/png;base64,not a picture') == ''
    from PIL import Image
    import base64
    buf = io.BytesIO()
    Image.new('RGB', (10, 10)).save(buf, format='PNG')
    value = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    assert _safe_guide_thumb(value) == value
