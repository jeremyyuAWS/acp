"""The limitations notice reaches the PDF a person actually downloads.

WHY THIS FILE EXISTS. `tests/test_acr_export_pdf_limitations.py` (#1416) proved
`acr_export_pdf.render()` inserts the notice, and it does. It reached nobody. The route that
serves `/acr/{id}/preview?format=pdf` had already built its projection and called
`render_html(to_html(projection))` directly, so `render()` had exactly one caller in the
repository — that test. Measured on `origin/main` before this change, over the same fixture:

    render_html(to_html(projection))   → "PAC 2024" present: False
    render()                           → "PAC 2024" present: True

Nothing failed. The PDF stayed PDF/UA-1 conformant, the structural suite stayed green, the PR
merged, and the export went on making the claim the notice exists to qualify. A disclosure that
only a unit test can see is the same defect as no disclosure, and it is invisible in review.

So the two tests here are deliberately at levels the original was not:

  · over HTTP, through the real route, because that is the artifact the customer holds;
  · over the import graph, because "someone reintroduces the direct call" is how it comes back.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pytest.importorskip("weasyprint")

import acr_export_pdf  # noqa: E402

OWNER = "owner@example.com"
ANALYST = "analyst@example.com"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ANALYST))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def report_id(client):
    return client(OWNER).post("/acr", json={"product_version": "2026.9.1",
                                            "build_id": "0f096be0"}).json()["report_id"]


def _flat(pdf_bytes: bytes, tmp_path) -> str:
    """Extracted text with whitespace collapsed — pdfminer breaks lines mid-phrase, so a wrapped
    phrase is absent from the raw extraction while perfectly visible to a reader."""
    path = tmp_path / "download.pdf"
    path.write_bytes(pdf_bytes)
    from pdfminer.high_level import extract_text
    return re.sub(r"\s+", " ", extract_text(str(path)))


def test_the_downloaded_pdf_carries_the_limitations_notice(client, report_id, tmp_path):
    """The claim #1416 was supposed to make, asserted where it is actually consumed: the bytes
    that come back over HTTP from the endpoint the download button calls."""
    r = client(ANALYST).get(f"/acr/{report_id}/preview", params={"format": "pdf"})
    assert r.status_code == 200, r.text[:300]
    assert r.content.startswith(b"%PDF-"), r.content[:20]

    text = _flat(r.content, tmp_path)
    assert "Limitations of this document" in text, text[:400]
    assert "PAC 2024" in text, text[:400]
    assert "screen-reader pass" in text, text[:400]
    assert "necessary and not sufficient" in text, text[:400]


def _api_modules() -> list[Path]:
    return sorted(p for p in (ACP / "api").rglob("*.py")
                  if p.name != "acr_export_pdf.py" and "__pycache__" not in p.parts)


def test_no_production_module_renders_a_pdf_without_the_notice():
    """The structural guard, and the check that would have caught the original seam.

    `render_html` is the raw renderer: it takes whatever HTML it is given and tags it. That is
    what makes it useful to `test_acr_export_pdf.py`, which feeds it deliberately untagged pages
    to prove the assertions are non-vacuous — and exactly what makes it wrong for production,
    where the HTML must have been through `with_limitations` first.

    So the rule is: inside `api/`, a projection becomes a PDF through `render_projection` or not
    at all. Asserted over the AST rather than by grep because an import-and-call
    (`from acr_export_pdf import render_html`) reads nothing like an attribute call and is the
    form a reader is least likely to notice.
    """
    offenders: list[str] = []
    for path in _api_modules():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                                  # pragma: no cover - not our concern
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "render_html":
                offenders.append(f"{path.relative_to(ACP)}:{node.lineno} attribute access")
            elif isinstance(node, ast.ImportFrom) and node.module == "acr_export_pdf":
                for alias in node.names:
                    if alias.name == "render_html":
                        offenders.append(f"{path.relative_to(ACP)}:{node.lineno} imported by name")

    assert not offenders, (
        "these call the raw renderer, which does NOT insert the limitations notice; use "
        "acr_export_pdf.render_projection(projection) instead:\n  " + "\n  ".join(offenders))


def test_the_guard_can_actually_see_a_violation(tmp_path):
    """A guard that has never been shown to fire is a claim, not a check.

    The scan above passes on a clean tree, which is indistinguishable from a scan that matches
    nothing at all — so this hands it both offending forms and asserts it finds them. It exercises
    the same walk against a fixture module rather than trusting that the real one is well-formed.
    """
    src = ("import acr_export_pdf\n"
           "from acr_export_pdf import render_html\n"
           "def f(html):\n"
           "    return acr_export_pdf.render_html(html)\n")
    tree = ast.parse(src)

    attrs = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and n.attr == "render_html"]
    imports = [n for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) and n.module == "acr_export_pdf"
               and any(a.name == "render_html" for a in n.names)]

    assert len(attrs) == 1, "the attribute-access form is not being detected"
    assert len(imports) == 1, "the import-by-name form is not being detected"


def test_render_projection_is_the_composed_path():
    """`render()` and the route must reach the renderer the same way. Two compositions of the
    same three steps is how they drift, and the drift is one export quietly losing a paragraph."""
    html = acr_export_pdf.acr_export_preview.to_html(
        acr_export_pdf.acr_export_preview.project(
            {"report_title": "t"},
            [{"criterion_num": "1.1.1", "criterion_name": "Non-text Content", "level": "A",
              "principle": "Perceivable", "final_status": "Supports", "remarks": ""}]))
    assert "PAC 2024" not in html, "the projection HTML should not carry the notice on its own"
    assert "PAC 2024" in acr_export_pdf.with_limitations(html)
