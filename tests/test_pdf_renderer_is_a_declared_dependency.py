"""A declared dependency that does not import is a failure, not a skip.

THIS FILE EXISTS BECAUSE OF HOW THE OTHER ONE COULD LIE. `tests/test_acr_export_pdf.py` opens
with `pytest.importorskip("weasyprint")` so a bare checkout can still run the rest of the suite.
That is the right call for a developer and the wrong one for CI: if the image ever lacks the
Pango libraries WeasyPrint binds to, every structural and PDF/UA assertion in that file would
SKIP, the job would stay green, and the ACR export would be broken in production with no red
anywhere.

That is not hypothetical. It is exactly the state #1159 shipped in: `api/report_weasy.py` and 15
structural tests, with `weasyprint` in no requirements file anywhere in the repo — so its whole
suite skipped in CI while its PR body reported "21 passed, veraPDF running (0 skips)", which was
true only on the author's hand-provisioned machine.

So the rule this file enforces is a conditional one, and the condition is the repo's own
declaration: **if `api/requirements.txt` pins it, it must import.** No pin, no obligation — which
keeps this honest if the dependency is ever deliberately dropped, rather than turning into a
second place to remember to edit.
"""
from __future__ import annotations

import re
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
REQUIREMENTS = ACP / "api/requirements.txt"


def _is_pinned(package: str) -> bool:
    """True when api/requirements.txt installs this package into the running image."""
    pattern = re.compile(rf"^\s*{re.escape(package)}\s*(==|>=|~=|<|>|$)", re.I | re.M)
    body = "\n".join(
        line for line in REQUIREMENTS.read_text().splitlines() if not line.lstrip().startswith("#"))
    return bool(pattern.search(body))


def test_the_requirements_file_is_where_this_test_thinks_it_is():
    """The premise. If the path were wrong `_is_pinned` would answer False for everything and
    this whole file would pass by finding nothing — the failure mode it exists to prevent."""
    assert REQUIREMENTS.is_file(), REQUIREMENTS
    assert _is_pinned("pikepdf"), "the pin parser found nothing it should have found"
    assert not _is_pinned("definitely-not-a-real-package"), "the pin parser matches anything"


def test_weasyprint_imports_wherever_it_is_declared():
    """The ACR's accessible export (api/acr_export_pdf.py) is unavailable without it, and the
    route answers 503. A green CI must not be compatible with that."""
    if not _is_pinned("weasyprint"):
        import pytest
        pytest.skip("weasyprint is not pinned in api/requirements.txt — nothing is claimed")

    try:
        import weasyprint  # noqa: F401
    except Exception as exc:                      # pragma: no cover - only on a broken image
        raise AssertionError(
            f"weasyprint is pinned in api/requirements.txt but will not import here: {exc!r}. "
            f"It binds to Pango/HarfBuzz/fontconfig, which deploy/public/Dockerfile.base-api "
            f"installs explicitly — a pip install alone is not enough. Until this imports, every "
            f"PDF/UA assertion in tests/test_acr_export_pdf.py SKIPS and the ACR export is broken "
            f"with nothing red to say so."
        ) from exc


def test_the_acr_pdf_lane_reports_itself_available():
    """One layer up from the import: the module's own answer, which is what the route and any
    future UI gating will consult. These two disagreeing is how a button that always fails ships.
    """
    if not _is_pinned("weasyprint"):
        import pytest
        pytest.skip("weasyprint is not pinned in api/requirements.txt — nothing is claimed")

    import sys
    sys.path.insert(0, str(ACP / "api"))
    import acr_export_pdf

    assert acr_export_pdf.is_available() is True, (
        "acr_export_pdf.is_available() is False on an image that declares the dependency")
