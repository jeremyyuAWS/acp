"""`/scans/{sid}/report.pdf` serves the PDF/UA renderer, and the image that serves it can run it.

THE ROUTE CHANGE IS ONE IMPORT AND ONE CALL. What makes the cutover hold is everything around it:
WeasyPrint needs shared libraries pip cannot install, and a missing one raises OSError rather than
ImportError. So an image without them does not fail loudly — `_render_report` falls back and
serves a NON-CONFORMANT report, quietly, forever. That is the failure this file exists to catch,
and it catches it statically: these assertions read the requirements file and the Dockerfile as
text, so they hold on a machine that cannot render a PDF at all, which is the machine that most
needs telling.

SCOPE, deliberately. Only `deploy/public/Dockerfile.base-api` is asserted — the image that
actually serves this endpoint. The CI images and pipelines install their own WeasyPrint stack and
veraPDF, and that arrangement is owned by the PDF/UA gate work (#1198, #1199); duplicating its
assertions here would mean two files disagreeing about one deployment the first time either
changes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

#: What weasyprint.text.ffi dlopens, as Debian package names. Read off the installed package's own
#: dlopen calls rather than from documentation — spike/weasyprint-report/requirements.txt says
#: "Pango, cairo, GDK-PixBuf, HarfBuzz", the pre-53 cairo-era list, which names two libraries
#: WeasyPrint 69 never loads. libglib2.0-0 (gobject) is not asserted: it arrives as a dependency
#: of libpango and demanding it explicitly would assert a packaging detail, not a requirement.
_NATIVE = ("libpango-1.0-0", "libpangoft2-1.0-0", "libharfbuzz0b", "libfontconfig1")

_REQS = ROOT / "api" / "requirements.txt"
_BASE_API = ROOT / "deploy" / "public" / "Dockerfile.base-api"


def test_the_report_route_calls_the_weasyprint_renderer_first():
    """The cutover itself, asserted on the route's own resolution order rather than a mock."""
    import routes.scans as scans

    assert scans._REPORT_RENDERER == "weasy", (
        f"default renderer is {scans._REPORT_RENDERER!r}; the cutover makes weasy the default")
    src = (ROOT / "api" / "routes" / "scans.py").read_text()
    assert "build_weasy_report, build_tagged_report, build_report" in src, (
        "the fallback order no longer puts the PDF/UA renderer first")


def test_the_previous_renderer_is_reachable_without_a_redeploy():
    """Two of ADR 0034's gates had not run at cutover, so there must be a way back.

    PAC 2024 and an NVDA/VoiceOver pass are still outstanding. A revert that needs a build is not
    one anybody reaches for at the moment they need it.
    """
    src = (ROOT / "api" / "routes" / "scans.py").read_text()
    assert 'os.environ.get("ACP_REPORT_RENDERER"' in src, "no runtime switch"
    assert '== "tagged"' in src, 'ACP_REPORT_RENDERER=tagged must restore the Chromium renderer'


def test_weasyprint_is_declared_where_pip_can_see_it():
    """Undeclared, it is installed nowhere, the route silently falls back, and every test that
    needs it skips without saying anything a reader would notice."""
    assert re.search(r"^weasyprint==", _REQS.read_text(), re.M), (
        "weasyprint is not in api/requirements.txt — the route imports it, so the report would "
        "fall back to the non-conformant renderer on every request")


@pytest.mark.parametrize("lib", _NATIVE)
def test_every_native_library_weasyprint_dlopens_is_installed_in_the_serving_image(lib):
    """pip installs the wheel; apt installs what the wheel calls into.

    Losing one of these does not break the endpoint — it downgrades the document, which is worse,
    because the endpoint keeps answering 200 with a report that no longer passes PDF/UA.
    """
    assert _BASE_API.exists(), f"{_BASE_API} moved; this guard needs its new path"
    assert lib in _BASE_API.read_text(), (
        f"{_BASE_API.relative_to(ROOT)} does not install {lib}, which weasyprint dlopens")


def test_the_tick_and_cross_have_a_font_that_carries_them():
    """The File Inventory prints U+2713 and U+2717 and Liberation Sans has neither.

    Measured with fontTools against the font file, not assumed. Without DejaVu they render as
    .notdef boxes — in the certification column of a document about accessibility.
    """
    assert "fonts-dejavu-core" in _BASE_API.read_text(), (
        f"{_BASE_API.relative_to(ROOT)} installs no DejaVu; the tick and cross become boxes")


def test_the_renderer_no_longer_claims_to_be_unwired():
    """Its docstring said "NOT WIRED IN" — false the moment it became the default.

    This repo has been bitten repeatedly by a stale comment read where a command should have been
    run: a header saying the PDF engine "lives outside this repo entirely" was false for months,
    and ci.yml's own header records the same shape. A module's account of whether it is live is
    exactly the claim that goes stale without anything failing.
    """
    doc = (ROOT / "api" / "report_weasy.py").read_text()[:4000]
    assert "NOT WIRED IN" not in doc, (
        "report_weasy.py still says it is not wired in, but it is the default renderer")
