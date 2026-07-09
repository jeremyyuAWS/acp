"""Contract: every Drive write of DOCUMENT BYTES stamps ACP provenance.

A unit test can only cover the write paths someone remembered to fake. This walks the
source instead, so a NEW upload path — or an edit that drops `body` from an existing one —
fails here rather than silently shipping an unstamped copy that discovery then re-ingests
as a source document.

The tell for "this call writes document bytes" is `media_body`. Folder creates and metadata
-only updates (an archive move, a rename) carry no media_body and must NOT be stamped:
stamping a user's original would make discovery skip the very file it exists to find.
"""
import ast
from pathlib import Path

import pytest

API = Path(__file__).resolve().parent.parent / "api"

# Every module that uploads document bytes to Drive.
WRITE_MODULES = ["handlers.py", "publish.py", "routes/drive.py"]


def _content_writes(path: Path):
    """Yield (lineno, source) for each files().create/update call carrying media_body."""
    tree = ast.parse(path.read_text())
    src = path.read_text()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("create", "update"):
            continue
        kwargs = {k.arg for k in node.keywords}
        if "media_body" not in kwargs:
            continue                      # folder create / metadata-only update
        yield node.lineno, ast.get_source_segment(src, node) or ""


def test_there_are_content_writes_to_check():
    # Guard the guard: if a refactor moves these, this suite must not silently pass empty.
    total = sum(len(list(_content_writes(API / m))) for m in WRITE_MODULES)
    assert total >= 5, f"expected the known Drive content-writes, found {total}"


@pytest.mark.parametrize("module", WRITE_MODULES)
def test_every_drive_content_write_stamps_provenance(module):
    path = API / module
    unstamped = [ln for ln, src in _content_writes(path) if "properties" not in src]
    assert not unstamped, (
        f"{module}: Drive upload(s) at line(s) {unstamped} write document bytes without a "
        f"provenance stamp. Pass properties=provenance.stamp(filename) in `body` — an "
        f"unstamped copy is re-discovered as a source document (see api/provenance.py)."
    )


@pytest.mark.parametrize("module", WRITE_MODULES)
def test_write_modules_import_provenance(module):
    assert "import provenance" in (API / module).read_text(), (
        f"{module} writes to Drive but does not import provenance")
