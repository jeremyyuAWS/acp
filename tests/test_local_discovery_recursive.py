"""The local source walks the whole nested tree and carries filesystem metadata.

Before this, `_list(source="local")` used `glob("*")` — a single level — and returned scannable
files as `{"name", "path"}` only. A realistic estate is a nested tree, and a discovery inventory is
supposed to carry source metadata (size / modified / created / owner / parent) the way the Drive and
SharePoint listers do. These pin both: recursion, and per-file stat metadata for the scannable rows
AND the non-scannable inventory rows.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402


@pytest.fixture
def nested_corpus(tmp_path, monkeypatch):
    """A small nested estate: scannable files at several depths, plus a non-scannable one."""
    (tmp_path / "top.docx").write_bytes(b"x" * 2048)
    deep = tmp_path / "Dept" / "2024" / "Q1"
    deep.mkdir(parents=True)
    (deep / "report.pdf").write_bytes(b"y" * 4096)
    (tmp_path / "Dept" / "data.xlsx").write_bytes(b"z" * 1024)
    (tmp_path / "Dept" / "notes.txt").write_bytes(b"n" * 3072)   # non-scannable, 3 KiB
    monkeypatch.setenv("ACP_LOCAL_CORPUS", str(tmp_path))
    return tmp_path


def test_local_walk_is_recursive(nested_corpus):
    inv: list = []
    scope: dict = {}
    items = scanner._list("local", None, inventory_out=inv, scope_out=scope)

    # recursion: files at depth 1, 2 and 3 are all found — a single-level glob would miss the deep two.
    assert {it["name"] for it in items} == {"top.docx", "report.pdf", "data.xlsx"}
    assert scope["kept"] == 3
    # the non-scannable file is inventoried, not analysed
    assert {r["file"] for r in inv} == {"notes.txt"}


def test_scannable_rows_carry_stat_metadata(nested_corpus):
    items = scanner._list("local", None)
    report = next(it for it in items if it["name"] == "report.pdf")

    assert report["size_kb"] == 4                      # 4096 bytes → 4 KiB
    assert report["source_modified"] and report["source_modified"].endswith("+00:00")
    assert report["created_at"]                        # birthtime/ctime populated
    assert report["parent_folder"] == "Dept/2024/Q1"   # directory relative to the scan root
    assert "source_mime" in report                     # guessed from extension (may be None on some OSes)


def test_nonscannable_inventory_carries_size_and_mtime(nested_corpus):
    inv: list = []
    scanner._list("local", None, inventory_out=inv)
    notes = next(r for r in inv if r["file"] == "notes.txt")

    assert notes["size_kb"] == 3                        # 3072 bytes → 3 KiB
    assert notes["source_modified"]
    assert notes["parent_folder"] == "Dept"
    assert notes["doc_class"] == "unsupported"
