from io import BytesIO
from PIL import Image, ImageDraw
from caption_validation import validate_caption


def png(image):
    data = BytesIO(); image.save(data, format='PNG'); return data.getvalue()


def objects():
    image = Image.new('RGB', (400, 300), 'white'); draw = ImageDraw.Draw(image)
    draw.ellipse((45, 95, 145, 195), fill='#dc2626')
    draw.rectangle((245, 95, 345, 195), fill='#2563eb')
    return png(image)


def test_real_observed_two_square_caption_is_rejected_against_pixels():
    caption = 'The image displays two squares, one red and one blue, against a gray background. The red square is positioned to the left of the blue square.'
    outcome = validate_caption(caption, objects())
    assert outcome['status'] == 'rejected' and not outcome['approved']
    assert outcome['reason_codes'] == ['pixel_shape_or_color_contradiction']


def test_correct_flat_shape_caption_can_be_automated():
    caption = 'A red circle on the left and a blue square on the right on a white background.'
    outcome = validate_caption(caption, objects())
    assert outcome['approved'] and outcome['status'] == 'validated'
    assert outcome['evidence']['method'] == 'exact_flat_raster'
    assert outcome['canonical_caption'] == caption


def test_solid_color_caption_matches_exact_raster():
    data = png(Image.new('RGB', (32, 32), 'blue'))
    assert validate_caption('The image is a solid blue color.', data)['approved']
    assert validate_caption('The image is a solid red color.', data)['status'] == 'rejected'


def test_observed_chart_number_denial_is_rejected_but_ocr_never_approves_semantics():
    image = Image.new('RGB', (400, 300), 'white'); draw = ImageDraw.Draw(image)
    draw.text((10, 10), 'Monthly totals', fill='black')
    for x, height, color in [(80, 60, 'blue'), (180, 180, 'red'), (280, 120, 'green')]:
        draw.rectangle((x, 250-height, x+40, 250), fill=color)
    data = png(image)
    bad = validate_caption('The chart does not provide any numerical values.', data, ocr_tokens=['10', '30', '20'])
    assert bad['status'] == 'rejected' and bad['reason_codes'] == ['visible_numbers_denied']
    legitimate = validate_caption('Three bars: A 10, B 30, C 20.', data, ocr_tokens=['A', '10', 'B', '30', 'C', '20'])
    assert legitimate['status'] == 'needs_manual' and not legitimate['approved']


def test_invented_numbers_and_unsupported_claims_do_not_pass():
    data = objects()
    assert validate_caption('A red circle numbered 99.', data, ocr_tokens=['10'])['status'] == 'rejected'
    assert validate_caption('A medical logo showing successful treatment.', data)['status'] == 'needs_manual'
    assert validate_caption('A red circle on the right and a blue square on the left.', data)['status'] == 'needs_manual'


def test_structural_success_cannot_validate_unsupported_pixels_or_transparency():
    image = Image.new('RGBA', (64, 64), (255, 0, 0, 0))
    assert validate_caption('The image is a solid red color.', png(image))['status'] == 'needs_manual'
    assert validate_caption('A blue square.', b'invalid image')['status'] == 'needs_manual'
    assert validate_caption('', objects())['status'] == 'needs_manual'


def test_correct_pixel_facts_plus_extra_assertions_never_approve():
    caption = 'A red circle on the left and a blue square on the right on a white background. This represents successful medical treatment.'
    result = validate_caption(caption, objects())
    assert not result['approved'] and result['status'] == 'needs_manual'


def test_unknown_chart_colors_or_model_agreement_are_not_evidence():
    image = Image.new('RGB', (400, 300), 'white'); draw = ImageDraw.Draw(image)
    draw.rectangle((40, 80, 80, 200), fill='red')
    draw.rectangle((100, 60, 140, 200), fill='blue')
    draw.text((10, 10), 'Monthly totals', fill='black')
    result = validate_caption('A blue bar represents A and a red bar represents B.', png(image))
    assert result['status'] == 'needs_manual' and not result['approved']
