"""Conservative review gate for Quality-first raster charts, without another AI call.

OCR is a bag of labels, not a mapping between series and values. In particular a
caption swapping two years can contain every correct token. Never call that
verified. Native Office chart data uses the separate deterministic chart path.
"""
import re

_CHART = re.compile(r'\b(?:charts?|graphs?|histograms?|scatterplots?|plots?)\b', re.I)
_UNCERTAIN = re.compile(r'\b(?:unclear|illegible|unreadable|uncertain|cannot (?:read|determine)|not legible)\b', re.I)
CHECKS = ('series', 'year', 'sign', 'value', 'units')


def quality_first_review(alt, *, ocr_text='', context=''):
    from llm_waterfall_provider import managed_context
    run = managed_context()
    if not run or not getattr(run, 'policy', {}).get('quality_first'):
        return {}
    chart = bool(_CHART.search(' '.join((alt or '', ocr_text or '', context or ''))))
    uncertain = bool(_UNCERTAIN.search(alt or ''))
    if not (chart or uncertain):
        return {}
    reason = 'chart_relationships_unverified' if chart else 'image_description_uncertain'
    evidence = ('Needs review: compare each series and year with the image, including value, sign and units. '
                'OCR labels do not verify which value belongs to which series or year.' if chart else
                'Needs review: the draft reports unreadable or uncertain image content; confirm it against the source.')
    out = dict(grounded=False, automatic_write_blocked=True, approval_required=True,
               review_status='needs_review', reason_code=reason, evidence=evidence)
    if chart:
        out['chart_review'] = dict(status='needs_review', checks=list(CHECKS),
            evidence_basis='image_ocr' if ocr_text.strip() else 'image_only',
            limitations='OCR text does not verify associations between series, years and values.')
    return out
