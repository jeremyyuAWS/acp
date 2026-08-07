"""Discovery must count a Drive file ONCE, however many times Drive lists it.

The live symptom: a Drive folder holding one .pptx and one unrelated .pdf reported the
pptx as "x2 copies". Drive had returned the same file id twice — a file can have several
parents (so a subtree BFS meets it twice), corpora="allDrives" can surface it from both My
Drive and a Shared Drive, and paged listings can overlap. `_normalize` then de-duplicated by
NAME, renaming the second sighting to "… (1).pptx" — a phantom document. The frontend's
`baseName` (frontend/src/dedupe.js) strips exactly that " (N)" suffix, so the phantom got
folded back into its original and rendered as "x2 copies".

A Drive file id IS the document's identity: two parents do not make two documents. Name
disambiguation must survive, though — Drive genuinely allows two DIFFERENT file ids to share
a name, and those are two real documents.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
FOLDER = "application/vnd.google-apps.folder"


def _pptx(fid, name):
    return {"id": fid, "name": name, "mimeType": PPTX, "md5Checksum": f"md5-{fid}"}


# ── _normalize: identity dedup ────────────────────────────────────────────────

def test_same_file_id_listed_twice_is_one_document():
    f = _pptx("FILE123", "Movate_AccessOps_Healthcare_v6.pptx")
    out = scanner._normalize([f, dict(f)])
    assert len(out) == 1
    assert out[0]["name"] == "Movate_AccessOps_Healthcare_v6.pptx"   # no phantom " (1)"
    assert out[0]["id"] == "FILE123"


def test_a_relisted_file_never_becomes_a_phantom_copy():
    """The exact reported shape: one pptx (listed twice) + one unrelated pdf."""
    pptx = _pptx("FILE123", "Movate_AccessOps_Healthcare_v6.pptx")
    pdf = {"id": "FILE999", "name": "Movate_AccessOps_Healthcare_v6 Page 6to8 .pdf",
           "mimeType": "application/pdf", "md5Checksum": "zzz"}
    names = [o["name"] for o in scanner._normalize([pptx, dict(pptx), pdf])]
    assert names == ["Movate_AccessOps_Healthcare_v6.pptx",
                     "Movate_AccessOps_Healthcare_v6 Page 6to8 .pdf"]
    # the two are distinct documents and neither is a "copy" of the other
    assert not any("(1)" in n for n in names)


def test_distinct_files_sharing_a_name_still_disambiguate():
    """Drive allows two different ids named the same — those ARE two documents."""
    out = scanner._normalize([_pptx("A", "Report.pptx"), _pptx("B", "Report.pptx")])
    assert [o["name"] for o in out] == ["Report.pptx", "Report (1).pptx"]
    assert [o["id"] for o in out] == ["A", "B"]


def test_identity_dedup_keeps_the_first_sighting_intact():
    a = _pptx("X", "Deck.pptx")
    b = {**_pptx("X", "Deck.pptx"), "md5Checksum": "changed-mid-listing"}
    out = scanner._normalize([a, b])
    assert len(out) == 1 and out[0]["checksum"] == "md5-X"


# ── _search_folder: a multi-parent file met twice by the BFS ──────────────────

class _Req:
    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _Files:
    def __init__(self, drive):
        self.d = drive

    def list(self, **kw):
        fid = kw.get("q", "").split("'")[1]
        return _Req({"files": self.d.children.get(fid, [])})


class FakeDrive:
    def __init__(self, children):
        self.children = children

    def files(self):
        return _Files(self)


@pytest.fixture(autouse=True)
def _stub_core(monkeypatch):
    core = types.ModuleType("core")
    core.store = types.SimpleNamespace(get_drive_mirror_folder=lambda: "Remediated")
    monkeypatch.setitem(sys.modules, "core", core)


def test_multi_parent_file_walked_twice_is_scanned_once():
    """`deck.pptx` lives in BOTH subfolders — Drive returns it from each listing. The BFS
    guards folders by id but not files, so identity dedup in _normalize is what saves us."""
    deck = _pptx("DECK", "deck.pptx")
    drive = FakeDrive({
        "root": [{"id": "sub1", "name": "A", "mimeType": FOLDER},
                 {"id": "sub2", "name": "B", "mimeType": FOLDER}],
        "sub1": [deck],
        "sub2": [dict(deck)],          # same file id, second parent
    })
    out = scanner._search_folder(drive, "root", max_files=100)
    assert [o["id"] for o in out] == ["DECK"]
    assert out[0]["name"] == "deck.pptx"


# ── _sp_list: OneDrive / MS Graph paged search returns an item twice ──────────

def _graph(monkeypatch, pages):
    """Stub httpx.get so _sp_list walks `pages` (each a Graph /search response)."""
    import httpx
    calls = iter(pages)

    class _Resp:
        # `status_code` is not optional decoration: _sp_get inspects it to tell a MISSING SCOPE
        # (401/403, which needs Sites.Read.All and admin consent) from a transport failure, and a
        # real httpx.Response always carries one. The stub simply predated that distinction.
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _Resp(next(calls)))


def _sp_item(iid, name):
    return {"id": iid, "name": name, "file": {}}


def test_sp_paged_search_returning_an_item_twice_yields_one_document(monkeypatch):
    """Graph's paged /search can repeat an item across pages. It is still one document."""
    _graph(monkeypatch, [
        {"value": [_sp_item("I1", "deck.pptx")],
         "@odata.nextLink": "https://graph.microsoft.com/next"},
        {"value": [_sp_item("I1", "deck.pptx"), _sp_item("I2", "budget.xlsx")]},
    ])
    out = scanner._sp_list("tok", max_files=50)
    assert [o["id"] for o in out] == ["I1", "I2"]
    assert [o["name"] for o in out] == ["deck.pptx", "budget.xlsx"]   # no phantom " (1)"


def test_sp_distinct_items_sharing_a_name_are_both_kept(monkeypatch):
    """Identity dedup must not swallow two DIFFERENT OneDrive items that share a name —
    _dedupe_names disambiguates those downstream."""
    _graph(monkeypatch, [{"value": [_sp_item("A", "Report.pptx"), _sp_item("B", "Report.pptx")]}])
    out = scanner._sp_list("tok", max_files=50)
    assert [o["id"] for o in out] == ["A", "B"]
    # names still collide here; _list's _dedupe_names is what separates them
    assert [o["name"] for o in scanner._dedupe_names(out)] == ["Report.pptx", "Report (1).pptx"]


def test_sp_skips_folders_and_unsupported_types(monkeypatch):
    _graph(monkeypatch, [{"value": [
        {"id": "F1", "name": "a-folder"},                 # no "file" facet → a folder
        _sp_item("I3", "photo.png"),                      # unsupported extension
        _sp_item("I4", "memo.docx"),
    ]}])
    assert [o["name"] for o in scanner._sp_list("tok", max_files=50)] == ["memo.docx"]
