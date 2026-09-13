import io
import pikepdf
from proposals import Verification
from verification_event_detail import verification_event_detail


def pdf_bytes(tagged=False):
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    if tagged:
        pdf.Root.StructTreeRoot = pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot)
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


def test_untagged_structure_is_manual_work_not_failed_title_fix():
    detail = verification_event_detail(Verification(True, {'1.3.1', '2.4.2'}),
                                       [{'rule_id': '2.4.2'}], pdf_bytes(), 'a.pdf')
    assert detail['failed_criteria'] == [{'criterion': '2.4.2', 'reason_code': 'criterion_still_failing'}]
    assert detail['manual_criteria'] == [{'criterion': '1.3.1', 'reason_code': 'pdf_structure_tagging_required'}]


def test_unavailable_verification_does_not_claim_observed_criterion_failure():
    detail = verification_event_detail(Verification(False, reason='private error'),
                                       [{'rule_id': '2.4.2'}], pdf_bytes(), 'a.pdf')
    assert detail['failed_criteria'][0]['reason_code'] == 'verification_unavailable'
    assert detail['manual_criteria'] == []
    assert 'private error' not in str(detail)


def test_tagged_pdf_and_corrupt_bytes_are_not_declared_unsupported_tagging():
    for data in (pdf_bytes(True), b'invalid'):
        assert verification_event_detail(Verification(True, {'1.3.1'}),
            [{'rule_id': '1.3.1'}], data, 'a.pdf')['manual_criteria'] == []
