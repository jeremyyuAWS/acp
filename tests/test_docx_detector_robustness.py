"""A docx detector must never fail a scan — it returns [] on garbage, it does not raise.

The three detectors migrated into the capability registry (ADR 0031: 1.1.1, 2.4.4, 3.1.2) are
called from `rule_registry.assess` as `reg.detector(path) or []` — with NO try/except around that
call. So the "self-gating" each detector's docstring promises is load-bearing: if one raises on a
malformed upload, it does not degrade that one criterion, it takes down the whole assessment of
the file. A corrupt or hand-forged .docx is exactly the kind of thing a real user uploads.

This feeds each detector a battery of broken packages — not a zip at all, an empty zip, a zip
whose document.xml is truncated mid-tag, a hyperlink pointing at an rId no rels file defines, an
image relationship pointing at a part that isn't in the package — and asserts every one yields a
list and raises nothing. It is deliberately implementation-blind: it pins the CONTRACT (never
raise), not the current guard shape, so a later refactor that narrows an `except` and reintroduces
the hazard fails here.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from formats.docx.detectors import language_parts, link_purpose, non_text_content  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

DETECTORS = pytest.mark.parametrize(
    "detect",
    [link_purpose.detect, language_parts.detect, non_text_content.detect],
    ids=["2.4.4_link_purpose", "3.1.2_language_parts", "1.1.1_non_text_content"],
)


# ── the battery of malformed packages, each written to a real file on disk ────────────────────

def _write(tmp_path: Path, name: str, members: dict[str, str | bytes]) -> Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    return p


@pytest.fixture
def not_a_zip(tmp_path: Path) -> Path:
    """A file whose bytes are not a zip archive at all — the BadZipFile case."""
    p = tmp_path / "not_a_zip.docx"
    p.write_bytes(b"PK\x03\x04 this looks like it starts a zip and then does not \x00\xff")
    return p


@pytest.fixture
def empty_zip(tmp_path: Path) -> Path:
    """A valid zip with no members — no document.xml, no rels, no media."""
    return _write(tmp_path, "empty.docx", {})


@pytest.fixture
def truncated_document(tmp_path: Path) -> Path:
    """document.xml present but truncated mid-tag — malformed XML in a valid zip."""
    return _write(tmp_path, "truncated.docx", {
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>hang',
    })


@pytest.fixture
def dangling_hyperlink(tmp_path: Path) -> Path:
    """A hyperlink referencing rId99, which no rels file defines. The rId must resolve to
    nothing, not to a KeyError — the 2.4.4 walk's stated 'degrade to nothing, never a wrong
    href' promise, exercised with the rels file entirely absent."""
    doc = (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body><w:p>'
           f'<w:hyperlink r:id="rId99"><w:r><w:t>click here</w:t></w:r></w:hyperlink>'
           f'</w:p></w:body></w:document>')
    return _write(tmp_path, "dangling_link.docx", {"word/document.xml": doc})


@pytest.fixture
def image_rel_to_missing_part(tmp_path: Path) -> Path:
    """An image relationship whose Target names a media part that is NOT in the package. The
    1.1.1 image walk must not assume every declared relationship resolves to real bytes."""
    doc = f'<w:document xmlns:w="{W}"><w:body><w:p/></w:body></w:document>'
    rels = (f'<Relationships xmlns="{R}/relationships">'
            f'<Relationship Id="rId5" '
            f'Type="{R}/relationships/image" Target="media/gone.png"/></Relationships>')
    return _write(tmp_path, "img_missing.docx", {
        "word/document.xml": doc,
        "word/_rels/document.xml.rels": rels,
    })


BROKEN_PACKAGES = [
    "not_a_zip",
    "empty_zip",
    "truncated_document",
    "dangling_hyperlink",
    "image_rel_to_missing_part",
]


@DETECTORS
@pytest.mark.parametrize("package", BROKEN_PACKAGES)
def test_detector_returns_list_never_raises_on_broken_package(detect, package, request):
    """Every (detector × broken package) pair: a list comes back, nothing is raised."""
    path = request.getfixturevalue(package)
    try:
        out = detect(path)
    except Exception as e:  # noqa: BLE001 — the whole point is that this must not happen
        pytest.fail(f"{detect.__module__}.detect raised {type(e).__name__} on {package}: {e}")
    assert isinstance(out, list), f"{detect.__module__}.detect returned {type(out)}, not a list"


@DETECTORS
def test_detector_returns_list_on_absent_file(detect, tmp_path):
    """A path that does not exist at all — FileNotFoundError must be swallowed to []."""
    missing = tmp_path / "does_not_exist.docx"
    assert detect(missing) == []
