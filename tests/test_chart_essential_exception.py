"""WCAG 1.4.5 Essential exception for charts/graphs (demo-precision fix).

The W3C's Understanding doc for 1.4.5 names graphs and diagrams as text presentations that ARE
essential — a chart cannot be re-authored as selectable text; its information reaches AT users via
the text alternative (1.1.1, checked separately). So an embedded image whose OCR reads like chart
data must NOT fail 1.4.5. 1.4.9 (AAA, literally "No Exception") still flags it — that is exactly
the AA-vs-AAA distinction the two criteria encode, and the tests pin both sides.

The four "REAL:" strings below are verbatim tesseract output from the demo corpus charts
(benefits-policy.docx) — the detector is tuned on evidence, not invented examples.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ocr  # noqa: E402

REAL_CHARTS = [
    # bar chart, numeric-dense (ratio .60)
    "Enrolled employees 3000 4 2500 4 2000 4 1500 4 1000 + 500 4 Medical Plan Enrollment — 2025 vs "
    "2026 2025 2,430 mmm 2026 2,610 2,150 1,840 1,120 980 HDHP PPO Select PPO Plus",
    # horizontal bar with $ values (money signal)
    "Dental Claims Paid by Category — 2024 Emergency $0.3M Orthodontia Major Restorative Basic "
    "Restorative Preventive $3.8M 0.0 0.5 1.0 15 2.0 2.5 3.0 3.5 Claims paid ($M)",
    # line chart with % (ratio .63)
    "Participation rate (%) 905 854 55 403(b) Participation Rate — 2020-2026 81% 2020 2021 2022 2023 2024 2025 2026",
    # label-heavy stacked bar: density only .22 — caught by the 6-token AXIS-TICK RUN "100 4 804 604 404 204"
    "% of elected balance 100 4 804 604 404 204 Average FSA Utilisation by Account Type mam Utilised "
    "Remaining Healthcare FSA Dependent Care FSA Limited Purpose FSA",
]


def test_all_real_demo_charts_qualify_for_the_essential_exception():
    for t in REAL_CHARTS:
        assert ocr._looks_like_chart(t), f"real chart OCR not recognised: {t[:60]}"


def test_prose_screenshots_do_not_qualify():
    prose = ("This is a screenshot of a paragraph of policy text explaining that employees must "
             "enroll before January 15 or wait until the next open enrollment period begins.")
    assert not ocr._looks_like_chart(prose)
    # a couple of scattered numbers/dates in prose is still prose — no 4-token run, low density
    dated = "Invoice 1042 was issued on March 3 2026 and is payable within 30 days of receipt by the finance team"
    assert not ocr._looks_like_chart(dated)


def test_1_4_5_skips_charts_but_1_4_9_still_flags_them():
    # Behaviour on the real demo document: after the exception, 1.4.5 finds nothing (all four
    # text-bearing images are charts), while AAA 1.4.9 still reports all four.
    sample = Path(__file__).resolve().parent.parent / "frontend" / "public" / "samples" / "benefits-policy.docx"
    import pytest
    if not sample.exists() or not ocr.is_available():
        pytest.skip("sample doc or OCR engine unavailable")
    assert ocr.images_of_text(sample, ".docx") == []
    assert len(ocr.images_of_text_no_exception(sample, ".docx")) == 4
