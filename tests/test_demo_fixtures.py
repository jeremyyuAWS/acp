"""Guard the Word + Excel accessibility demo fixtures against detector drift.

scripts/gen_demo_fixtures.py seeds each file with one instance of every in-scope WCAG
failure ACP can action on that format. If a detector's trigger changes and a fixture
stops exhibiting a finding, the live demo would silently under-count — this test scans
the freshly-generated fixtures with the real pipeline and asserts every expected
criterion still fires.

Detection splits across engines:
  * Python-side (office_structure / textchecks / ocr) needs no external binary and is
    asserted unconditionally — gated only on the optional OCR / langdetect deps.
  * The .NET OpenXML analysers (title, language, table headers, hidden content, image
    alt) need the built CLI; those are asserted only when the engine actually ran.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import gen_demo_fixtures as gen  # noqa: E402
import ocr  # noqa: E402
import scanner  # noqa: E402

# Every parametrisation scans through the shared pipeline, and scanner._analyse_pdf
# imports worker-python's `analysers` OUTSIDE its try/except — so without the (un-vendored)
# PDF engine even the docx/xlsx/pptx cases error rather than skipping honestly.
from engines import NO_PDF, PDF_OK  # noqa: E402

pytestmark = pytest.mark.skipif(not PDF_OK, reason=NO_PDF)


def _sc(wcag: str) -> str:
    """Normalize a finding's wcag label to a bare SC number: 'SC_1_1_1' and
    '2.4.6 Headings and Labels' both → '1.1.1' / '2.4.6'."""
    w = (wcag or "").strip()
    if w.startswith("SC_"):
        return w[3:].replace("_", ".")
    return w.split(" ", 1)[0] if w else ""


def _has_langdetect() -> bool:
    try:
        import langdetect  # noqa: F401
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo-fixtures")
    gen.build_docx(d / "word-accessibility-demo.docx")
    gen.build_xlsx(d / "excel-accessibility-demo.xlsx")
    gen.build_pdf(d / "pdf-accessibility-demo.pdf")
    gen.build_pptx(d / "powerpoint-accessibility-demo.pptx")
    out = {}
    for name in ("word-accessibility-demo.docx", "excel-accessibility-demo.xlsx",
                 "pdf-accessibility-demo.pdf", "powerpoint-accessibility-demo.pptx"):
        fdict, _ = scanner.analyse_and_assess(d, name, detect_pii=False)
        issues = fdict.get("issues", [])
        out[name] = {
            "scs": {_sc(i.get("wcag", "")) for i in issues},
            "engine_ran": any(str(i.get("wcag", "")).startswith("SC_") for i in issues),
        }
    return out


# Findings the Python detectors produce (no .NET needed). Some gate on optional deps.
def _expected_python(fmt: str) -> set[str]:
    base = {
        "docx": {"2.4.6", "1.3.1", "2.4.9", "3.3.2", "1.4.8", "1.3.3", "3.1.5"},
        "xlsx": {"1.4.3", "1.4.6", "1.3.3", "3.1.5"},
        # pdf: office_structure contrast + bypass-blocks + textchecks sensory (3.1.5 needs more
        # prose than fits an untagged PDF page; 1.1.1 is human on an untagged PDF).
        "pdf": {"1.3.3", "1.4.3", "1.4.6", "2.4.1"},
        # pptx: office_structure title + link-purpose + textchecks sensory + reading level.
        "pptx": {"1.3.3", "2.4.6", "2.4.9", "3.1.5"},
    }[fmt]
    if ocr.is_available():
        base |= {"1.4.5", "1.4.9"}
    if _has_langdetect():
        base |= {"3.1.2"}
    return base


# Every in-scope, actionable criterion for the format (2.4.10 is mutually exclusive
# with the 2.4.6 heading-skip a realistic multi-section doc exhibits, so it is out).
_INSCOPE = {
    "docx": {"1.1.1", "1.3.1", "1.3.3", "1.4.3", "1.4.5", "1.4.8", "2.4.2",
             "2.4.6", "2.4.9", "3.1.1", "3.1.2", "3.1.5", "3.3.2"},
    "xlsx": {"1.1.1", "1.3.1", "1.3.2", "1.3.3", "1.4.3", "1.4.5", "1.4.6",
             "2.4.2", "3.1.1", "3.1.2", "3.1.5"},
}


@pytest.mark.parametrize("fmt,name", [
    ("docx", "word-accessibility-demo.docx"),
    ("xlsx", "excel-accessibility-demo.xlsx"),
    ("pdf", "pdf-accessibility-demo.pdf"),
    ("pptx", "powerpoint-accessibility-demo.pptx"),
])
def test_python_detected_criteria_all_fire(scanned, fmt, name):
    got = scanned[name]["scs"]
    missing = _expected_python(fmt) - got
    assert not missing, f"{name}: python detectors did not fire for {sorted(missing)}"


@pytest.mark.parametrize("fmt,name", [
    ("docx", "word-accessibility-demo.docx"),
    ("xlsx", "excel-accessibility-demo.xlsx"),
])
def test_every_inscope_criterion_fires_when_engine_present(scanned, fmt, name):
    if not scanned[name]["engine_ran"]:
        pytest.skip("the .NET office analysers did not run (CLI not built)")
    got = scanned[name]["scs"]
    caps_gated = set()
    if not ocr.is_available():
        caps_gated |= {"1.4.5"}
    if not _has_langdetect():
        caps_gated |= {"3.1.2"}
    expected = _INSCOPE[fmt] - caps_gated
    missing = expected - got
    assert not missing, f"{name}: in-scope criteria not detected: {sorted(missing)}"
