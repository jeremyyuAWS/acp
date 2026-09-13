"""Bounded crop refusal details reach the approved row without claiming a write."""
from apply_outcome import NOTHING_WRITTEN, apply_outcome_for, parse_unverified

CROP = ("wrote no image-of-text replacement value(s) for ['1.4.5']: "
        "The image is cropped in Word. Review a transcription of the visible crop "
        "and confirm no useful diagram content would be lost before replacing it. "
        "The original image is kept unchanged. Credit withheld; the approved value is kept for retry")


def test_crop_reason_is_preserved_for_approved_row():
    parsed = parse_unverified(CROP)
    assert parsed['outcome'] == NOTHING_WRITTEN
    assert parsed['criteria'] == ['1.4.5']
    assert parsed['reason'].startswith('The image is cropped in Word.')
    assert 'visible crop' in parsed['reason']
    assert 'Credit withheld' not in parsed['reason']
    row = {'status': 'approved', 'applied': 0, 'rule_id': '1.4.5',
           'scan_id': 'crop-scan', 'file': 'crop.docx', 'reviewed_at': '2026-09-13T10:00:00Z'}
    decision = {'action': 'apply.unverified', 'detail': CROP, 'scan_id': 'crop-scan',
                'file': 'crop.docx', 'ts': '2026-09-13T10:01:00Z'}
    assert apply_outcome_for(row, [decision]) == {**parsed, 'ts': decision['ts']}
    assert apply_outcome_for({**row, 'rule_id': '1.1.1'}, [decision]) is None
    assert apply_outcome_for({**row, 'reviewed_at': '2026-09-13T10:02:00Z'}, [decision]) is None


def test_new_generic_write_refusal_and_old_detail_both_remain_readable():
    generic = CROP.replace(CROP.split(': ', 1)[1].split(' Credit withheld')[0],
                           'All 1 approved locator(s) reach no writable image in this document.')
    assert parse_unverified(generic)['outcome'] == NOTHING_WRITTEN
    old = "wrote no alt text value(s) for ['1.1.1']: all 1 approved locator(s) reach no image in this document. Credit withheld; the approved value is kept for retry"
    assert parse_unverified(old)['outcome'] == NOTHING_WRITTEN


def test_unrecognised_or_incomplete_crop_words_cannot_invent_outcome():
    assert parse_unverified('The image is cropped in Word.') == {}
    assert parse_unverified(CROP.replace("['1.4.5']", '[]')) == {}
    assert parse_unverified(CROP.replace('wrote no', 'wrote 1')) == {}
    assert parse_unverified(CROP.split(' Credit withheld')[0]) == {}
