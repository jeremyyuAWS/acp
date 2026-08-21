"""Discovery WALKS a SharePoint/OneDrive estate; it no longer asks the search index.

THE BUG THIS CLOSES, measured on prod in #333: 178 files uploaded, 39 discovered, presented as a
complete inventory. The same query returned 157 five minutes later and 158 after fifteen.

`root/search(q='')` reads Microsoft's search index, which is eventually consistent. It answers with
what has been INDEXED, and when that is less than what exists it says so with no error, no warning
and no partial flag — a truncated estate is indistinguishable from a genuinely small one. Everything
downstream (assessment coverage, the reconciliation, the compliance assertion) is then a fraction of
a number that was wrong, and discovery's entire value is completeness.

`/children` is a directory traversal against live metadata. It returns what is actually there.

The folder-scoped path always walked, which is why "pick the folders instead of the whole source"
was the workaround for an estate the index was under-reporting. These pin that the workaround is now
simply the behaviour — for a whole OneDrive, and for every library of a whole site.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _file(fid, name, path="/drive/root:"):
    return {"id": fid, "name": name, "file": {"mimeType": DOCX}, "parentReference": {"path": path}}


def _folder(fid, name):
    return {"id": fid, "name": name, "folder": {"childCount": 1}}


def _tree(pages, seen=None):
    """A Graph stand-in over /children, keyed by the URL fragment identifying the container."""
    def sp_get(token, url):
        if seen is not None:
            seen.append(url)
        for key, payload in pages.items():
            if key in url:
                return payload
        return {"value": []}
    return sp_get


def test_a_whole_onedrive_is_walked_not_searched(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "me/drive/root/children": {"value": [_file("1", "top.docx")]},
    }, seen))
    files = scanner._sp_list("tok", max_files=50)
    assert [f["name"] for f in files] == ["top.docx"]
    # The claim, stated as a claim: no request went to the index.
    assert seen, "nothing was requested at all"
    assert all("/search(" not in u for u in seen), f"discovery still asked the search index: {seen}"
    assert any("/children" in u for u in seen)


def test_the_walk_descends_subfolders_the_index_would_have_missed(monkeypatch):
    """The whole point. A nested file is returned by the walk and would be absent from an index
    that had not caught up with the folder it lives in."""
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "me/drive/root/children": {"value": [_file("1", "top.docx"), _folder("F", "Clinical")]},
        "items/F/children": {"value": [_file("2", "nested.docx", "/drive/root:/Clinical")]},
    }))
    files = scanner._sp_list("tok", max_files=50)
    assert sorted(f["name"] for f in files) == ["nested.docx", "top.docx"]


def test_every_library_of_a_site_is_walked(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(scanner, "_sp_drives", lambda token, site: [{"id": "d1"}, {"id": "d2"}])
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "drives/d1/root/children": {"value": [_file("a", "one.docx")]},
        "drives/d2/root/children": {"value": [_file("b", "two.docx")]},
    }, seen))
    files = scanner._sp_list("tok", max_files=50, site="S")
    assert sorted(f["name"] for f in files) == ["one.docx", "two.docx"]
    assert all("/search(" not in u for u in seen), f"a library was listed from the index: {seen}"


def test_onedrive_keeps_the_me_drive_contract(monkeypatch):
    """`drive_id` stays None for a whole-OneDrive walk, and the base is /me/drive.

    Resolving the real drive id would cost a round trip AND change what is stored on every item.
    `_sp_download` reads an absent `driveId` as /me/drive — correct there and ONLY there — and that
    absence is the shape every item listed before site support already has.
    """
    seen: list[str] = []
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "me/drive/root/children": {"value": [_file("1", "mine.docx")]},
    }, seen))
    files = scanner._sp_list("tok", max_files=50)
    assert "driveId" not in files[0]
    assert all("me/drive" in u for u in seen)
    assert all("/drives/None" not in u for u in seen), "None leaked into the drive base"


def test_acp_own_archive_is_pruned_at_enqueue_not_after(monkeypatch):
    """ACP's archive holds byte-for-byte copies of displaced originals and grows without bound.

    The caller already filters it out by path, so pruning changes no RESULT — it changes the COST.
    Walking it spends the cap on items that are then discarded, which can push real documents past
    the cap and out of the estate entirely.
    """
    seen: list[str] = []
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "me/drive/root/children": {
            "value": [_file("1", "live.docx"), _folder("ARCH", scanner.SP_ARCHIVE_FOLDER)]},
        "items/ARCH/children": {"value": [_file("2", "old.docx")]},
    }, seen))
    files = scanner._sp_list("tok", max_files=50)
    assert [f["name"] for f in files] == ["live.docx"]
    assert not any("items/ARCH" in u for u in seen), "the archive subtree was walked anyway"


def test_the_index_path_is_still_reachable_and_says_so(monkeypatch, capsys):
    """ACP_SP_ENUMERATE=search restores the old behaviour without a code change.

    An escape hatch for an operator who hits a wall on a very large estate and knowingly accepts an
    index-backed listing. It must never be SILENT: a count is only interpretable alongside the
    method that produced it, and this is the method that can be quietly wrong.
    """
    monkeypatch.setenv("ACP_SP_ENUMERATE", "search")
    seen: list[str] = []
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "me/drive/root/search": {"value": [_file("1", "indexed.docx")]},
    }, seen))
    files = scanner._sp_list("tok", max_files=50)
    assert [f["name"] for f in files] == ["indexed.docx"]
    assert any("/search(" in u for u in seen)
    assert "SEARCH INDEX" in capsys.readouterr().out


def test_the_default_is_the_walk_even_for_a_junk_value(monkeypatch):
    """Anything that is not exactly "search" walks. A typo'd env var must not silently select the
    mode that under-reports — the safe default has to be the one that cannot be quietly wrong."""
    seen: list[str] = []
    monkeypatch.setenv("ACP_SP_ENUMERATE", "SEARCHY")
    monkeypatch.setattr(scanner, "_sp_get", _tree({
        "me/drive/root/children": {"value": [_file("1", "x.docx")]},
    }, seen))
    scanner._sp_list("tok", max_files=50)
    assert all("/search(" not in u for u in seen)
