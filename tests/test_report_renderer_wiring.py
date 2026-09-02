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
import tempfile
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

sys.path.insert(0, str(ROOT / "tests"))
from test_report_weasy_structure import _FILES, _META, _RUN  # noqa: E402

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


def test_the_review_packet_asks_which_renderer_is_live_rather_than_assuming():
    """The sign-off document must not tell a reviewer the wrong thing about what ships.

    scripts/build_report_review_packet.py was written when WeasyPrint was a proposal, and named
    its outputs candidate.pdf and shipped.pdf. #1201 made WeasyPrint the default, at which point
    "shipped.pdf" named the renderer that had just STOPPED shipping and REVIEW.md opened by
    telling the reviewer that nothing had been switched over — while the endpoint was already
    serving it to customers. A sign-off packet that misstates whether the thing under review is
    live inverts the urgency of the sign-off, and PAC 2024 and the screen-reader pass were
    outstanding either way.

    So the packet reads routes.scans._REPORT_RENDERER. Asserted on that read rather than on the
    output filenames, because the failure being guarded against is a hardcoded assumption, not a
    naming choice: someone could rename the files back and still be correct, or keep these names
    and quietly hardcode WeasyPrint as "live" again.
    """
    src = (ROOT / "scripts" / "build_report_review_packet.py").read_text()
    assert "_scans._REPORT_RENDERER" in src, (
        "the review packet no longer asks the route which renderer is live; it will mislabel "
        "the document a reviewer signs off the moment ACP_REPORT_RENDERER is flipped")


def test_the_review_packet_ships_a_reading_order_traversal():
    """The packet answers the document half of the NVDA gate, since NVDA cannot run here.

    PAC 2024 and a screen-reader pass are the two gates ADR 0034 asks for and this environment
    cannot provide — PAC is a .NET Framework 4.8 WinForms app with no CLI (attempted under Wine
    9.0 with Wine Mono 9.0.0: the Mono runtime raises TypeInitializationException in mscorlib
    before any UI loads), and NVDA needs Windows UIA and a speech synthesiser. Walking the
    structure tree in reading order is the part that CAN be checked from the document, and it is
    what caught that 0 of 57 header cells carry an explicit /Scope.

    Asserted on the counts the traversal returns rather than on the file it writes: those counts
    are what REVIEW.md interpolates, so a traversal that stopped reporting them would leave the
    sign-off document making claims with no measurement behind them.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_packet", ROOT / "scripts" / "build_report_review_packet.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_packet"] = mod
    spec.loader.exec_module(mod)

    assert hasattr(mod, "reading_order"), "the packet no longer walks the structure tree"

    # Run it against a report this suite builds, rather than asserting the function exists.
    pytest.importorskip("weasyprint")
    sys.path.insert(0, str(ROOT / "api"))
    import report_weasy

    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "r.pdf"
        pdf.write_bytes(report_weasy.build_weasy_report(_RUN, _FILES, _META))
        counts = mod.reading_order(pdf, Path(td) / "reading-order.txt")
        text = (Path(td) / "reading-order.txt").read_text()

    assert counts["tagged"] is True, "the built report has no structure tree"
    assert counts["elements"] > 20, f"only {counts['elements']} elements — the walk truncated"
    assert counts["figures"] >= 2, (
        f"{counts['figures']} figures; the report has a logo and at least one chart")
    assert counts["figures_without_alt"] == 0, (
        f"{counts['figures_without_alt']} figure(s) carry no alternative — that is the defect "
        f"the NVDA gate exists to catch, and it is catchable here")
    assert counts["th"] > 0, "no header cells found; the tables lost their TH tags"
    assert "heading level 1" in text and "graphic" in text, (
        "the traversal names no roles; a reviewer cannot read reading order out of it")


def test_the_traversal_does_not_truncate():
    """An elided traversal reads as a finding rather than as a cut-off.

    The first version of this printed 120 elements and stopped. On this report that hid one of
    three figure alternatives and the only link — both of which read as real defects, and both of
    which were the limit. A reviewer cannot tell the difference from the file.
    """
    src = (ROOT / "scripts" / "build_report_review_packet.py").read_text()
    body = src[src.index("def reading_order("):src.index("@contextlib.contextmanager")]
    for stop in ("break", "[:120]", "islice"):
        assert stop not in body, (
            f"reading_order contains {stop!r}; a truncated traversal silently omits elements a "
            f"reviewer would read as missing")
