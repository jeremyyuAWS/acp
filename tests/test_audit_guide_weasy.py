"""The default audit renderer carries the same actionable evidence as fallbacks."""
from io import BytesIO

from report_weasy import render_html, build_weasy_report
from pypdf import PdfReader


RUN = {'id': 'offline-guide', 'completed_at': '2026-09-11T00:00:00', 'avg_score': 50}
META = {'target': 'WCAG 2.1 AA', 'version': '1', 'hash': 'abc'}
FILES = [{'file': 'patient.pdf', 'score': 50, 'compliant': False, 'status': 'done',
          'issues': [{'wcag': 'SC_1_1_1', 'severity': 'CRITICAL', 'locator': 'page:2:figure:3',
                      'detail': 'Missing description for the parking symbol'}]}]
EVIDENCE = [{'file': 'patient.pdf', 'applied': [{'sc': '4.1.2', 'before': 'Text1',
             'after': 'Patient name', 'validated': True, 'decision': 'approved', 'reviewer': 'system'}]}]


def test_default_html_preserves_change_values_and_does_not_invent_human_review():
    html = render_html(RUN, FILES, META, {'ai_calls_total': 2}, evidence=EVIDENCE)
    assert 'Your remediation guide' in html
    assert 'page:2:figure:3' in html
    assert 'Acrobat' in html
    assert 'Patient name' in html
    assert 'Text1' in html
    assert 'Human confirmation of meaning not recorded' in html
    assert 'AI-generated proposals were reviewed by a human' not in html
    assert 'version/hash not recorded' in html


def test_actual_default_pdf_includes_actionable_text():
    pdf = build_weasy_report(RUN, FILES, META, evidence=EVIDENCE)
    reader = PdfReader(BytesIO(pdf))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Your remediation guide' in text
    assert 'Patient name' in text
    assert 'page:2:figure:3' in text
    assert 'How to make the change:' in text
    assert reader.trailer['/Root']['/MarkInfo']['/Marked']
    assert reader.trailer['/Root']['/StructTreeRoot']['/K']
