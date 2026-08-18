"""Discover inventories the WHOLE estate, Assess still opens only the assessable subset.

PRD Phase A2 (§4.1 / §4.3 groundwork). Discovery used to persist per-file inventory rows for the
five scannable formats only; the whole-estate view was aggregate counts plus a capped sample. This
proves the un-gated behaviour, in the two directions that matter:

  (a) an unsupported / media / extensionless file becomes a `scan_inventory` row with its source
      metadata populated (owner, size, timestamps, parent, real MIME, a capability doc_class);
  (b) that same file is NEVER enqueued for assessment — the deferred-Assess fan-out filters back to
      the assessable rows, so media/executables/archives are inventoried but never downloaded;
  (c) the estate `discovered` count includes every type while `assessment_eligible` counts only the
      supported formats.

Drive/SharePoint listings are mocked exactly as the other scanner tests do (fake `files().list()`
/ stubbed Graph), so nothing here touches the network.
"""
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402
import estate_inventory  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PDF = "application/pdf"
FOLDER = estate_inventory.FOLDER_MIME


def _f(fid, name, mime, **extra):
    """A raw Drive file object carrying the full metadata field set (provenance.DRIVE_FIELDS)."""
    base = {"id": fid, "name": name, "mimeType": mime,
            "md5Checksum": f"md5-{fid}", "createdTime": "2026-01-01T00:00:00Z",
            "modifiedTime": "2026-02-02T00:00:00Z", "size": "4096",
            "owners": [{"displayName": "Alice Owner", "emailAddress": "alice@example.org"}],
            "parents": [f"parent-of-{fid}"]}
    base.update(extra)
    return base


# ── whole-Drive fake (single page for q="trashed=false") ────────────────────────

class _Resp:
    def __init__(self, files):
        self._files = files

    def execute(self, num_retries=0):
        return {"files": self._files}


class _Files:
    def __init__(self, files):
        self._files = files

    def list(self, **kw):
        return _Resp(self._files)


class FakeDrive:
    def __init__(self, files):
        self._files = files

    def files(self):
        return _Files(self._files)


_MIXED = [
    _f("d1", "deck.pptx", PPTX),                       # assessable
    _f("d2", "report.pdf", PDF),                       # assessable
    _f("m1", "logo.png", "image/png"),                 # media  → metadata_only
    _f("z1", "backup.zip", "application/zip"),         # archive → unsupported
    _f("x1", "README", "application/octet-stream"),    # extensionless → unsupported
    _f("F1", "a-subfolder", FOLDER),                   # a folder — never content
]


def test_search_drive_splits_estate_from_analysis_set():
    """(c) + the un-gate: the returned analysis set stays the scannable subset, while
    inventory_out captures every OTHER accessible file with metadata, and the estate summary
    counts them all."""
    scope: dict = {}
    inv: list = []
    result = scanner._search_drive(FakeDrive(_MIXED), max_files=500, scope_out=scope,
                                   inventory_out=inv)

    # The analysis set — unchanged: only the two scannable documents are ever downloaded.
    assert {it["name"] for it in result} == {"deck.pptx", "report.pdf"}

    # inventory_out — the rest of the estate (media / archive / extensionless), NO folder.
    assert {r["file"] for r in inv} == {"logo.png", "backup.zip", "README"}
    assert not any(r["file"] == "a-subfolder" for r in inv)

    # (c) discovered counts every non-folder file; assessment_eligible only the supported ones.
    est = scope["inventory"]
    assert est["discovered"] == 5
    assert est["assessment_eligible"] == 2


def test_non_scannable_inventory_row_has_full_metadata():
    """(a) at the source level: a media file's inventory row carries owner / size / timestamps /
    parent / real MIME and a capability doc_class — not a blank that reads as 'passed'."""
    inv: list = []
    scanner._search_drive(FakeDrive(_MIXED), max_files=500, inventory_out=inv)
    png = next(r for r in inv if r["file"] == "logo.png")
    assert png["mime"] == "image/png"
    assert png["owner"] == "Alice Owner"
    assert png["size_kb"] == 4                         # 4096 bytes → 4 KiB
    assert png["created_at"] == "2026-01-01T00:00:00Z"
    assert png["source_modified"] == "2026-02-02T00:00:00Z"
    assert png["parent_folder"] == "parent-of-m1"
    assert png["doc_class"] == "image"                 # honest about why it is not assessed
    zip_ = next(r for r in inv if r["file"] == "backup.zip")
    assert zip_["doc_class"] == "unsupported"


# ── SharePoint: inventory all types, search only the supported six ──────────────

def _graph(monkeypatch, value):
    import httpx

    class _R:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    pages = iter([{"value": value}])
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _R(next(pages)))


def test_sharepoint_inventories_all_types_but_returns_only_supported(monkeypatch):
    """(a)/(c) for SharePoint: the RETURN value stays the supported set, inventory_out gains the
    media/unsupported items with their Graph metadata."""
    _graph(monkeypatch, [
        {"id": "s1", "name": "brief.docx", "file": {"mimeType":
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
         "size": 8192, "createdDateTime": "2026-03-01T00:00:00Z",
         "lastModifiedDateTime": "2026-03-02T00:00:00Z",
         "createdBy": {"user": {"displayName": "Sam SP"}},
         "parentReference": {"path": "/drive/root:/Docs"}},
        {"id": "s2", "name": "clip.mp4", "file": {"mimeType": "video/mp4"},
         "size": 1048576, "createdBy": {"user": {"displayName": "Sam SP"}},
         "parentReference": {"path": "/drive/root:/Media"}},
        {"id": "s3", "name": "notes", "file": {"mimeType": "application/octet-stream"}},
    ])
    inv: list = []
    files = scanner._sp_list("tok", max_files=50, inventory_out=inv)
    assert [f["name"] for f in files] == ["brief.docx"]           # search/analysis: supported only
    assert {r["file"] for r in inv} == {"clip.mp4", "notes"}      # inventory: everything else
    mp4 = next(r for r in inv if r["file"] == "clip.mp4")
    assert mp4["doc_class"] == "audio-video" and mp4["size_kb"] == 1024
    assert mp4["owner"] == "Sam SP" and mp4["mime"] == "video/mp4"


# ── handlers: persist all, assess only the assessable ───────────────────────────

def _discover_list_stub(**payload_meta):
    """A `_list` replacement: returns one assessable Drive item and pushes one media row into
    inventory_out, exactly as the real listing would after un-gating."""
    def _stub(*a, **k):
        inv = k.get("inventory_out")
        if inv is not None:
            inv.append(scanner._inv_row(
                file="promo.mov", drive_file_id="mov1", mime="video/quicktime",
                size=5_242_880, created_at="2026-04-01T00:00:00Z",
                source_modified="2026-04-02T00:00:00Z", owner="Vic Video",
                parent_folder="folder-media"))
        return [{"name": "deck.pptx", "id": "d1", "source_mime": PPTX,
                 "checksum": "md5-d1", "created_at": "2026-05-01T00:00:00Z",
                 "source_modified": "2026-05-02T00:00:00Z", "owner": "Dana Deck",
                 "parent_folder": "folder-docs", "size_kb": 12}]
    return _stub


def test_discover_persists_all_types_assess_skips_non_assessable(isolated_store, monkeypatch):
    """(a) + (b): the deferred Discover inventories BOTH files with metadata; the follow-up Assess
    enqueues analysis for the deck only — the .mov is never downloaded."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", _discover_list_stub())

    handlers._scan_discover({"scan_id": "sA", "source": "local", "user": None}, {"scan_id": "sA"})

    # (a) both types are inventoried, and the media row's metadata survived the round trip.
    inv = {r["file"]: r for r in isolated_store.list_inventory("sA")}
    assert set(inv) == {"deck.pptx", "promo.mov"}
    mov = inv["promo.mov"]
    assert mov["mime"] == "video/quicktime" and mov["doc_class"] == "audio-video"
    assert mov["owner"] == "Vic Video" and mov["size_kb"] == 5120
    assert mov["created_at"] == "2026-04-01T00:00:00Z"
    assert mov["parent_folder"] == "folder-media"
    # the assessable row kept its document class + its own metadata
    assert inv["deck.pptx"]["doc_class"] == "slide-deck"
    assert inv["deck.pptx"]["owner"] == "Dana Deck" and inv["deck.pptx"]["size_kb"] == 12

    # discover opened nothing.
    assert not any(j["type"] in ("scan_file", "scan_batch") for j in isolated_store.list_jobs())

    # (b) Assess rebuilds the fan-out from the inventory — filtered to the assessable subset.
    handlers._scan_assess({"scan_id": "sA", "user": None}, {"scan_id": "sA"})
    scan_files = [j for j in isolated_store.list_jobs() if j["type"] == "scan_file"]
    enqueued = {json.loads(j["payload"])["file"] for j in scan_files}
    assert enqueued == {"deck.pptx"}                    # the .mov was NOT enqueued
    assert "promo.mov" not in enqueued


def test_assess_never_feeds_a_real_mime_into_the_export_selector(isolated_store, monkeypatch):
    """Regression: the inventory `mime` column now holds the REAL source MIME. Assess must NOT
    pass a plain 'application/pdf' as the analysis item's `mime` (the Google-native EXPORT
    selector) — that would KeyError in _download's EXPORT_MAP. Only Google-native MIMEs may pass
    through; everything else resolves to None."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    def _stub(*a, **k):
        return [{"name": "report.pdf", "id": "p1", "source_mime": PDF,
                 "checksum": "md5-p1"}]
    monkeypatch.setattr(scanner, "_list", _stub)

    handlers._scan_discover({"scan_id": "sB", "source": "local", "user": None}, {"scan_id": "sB"})
    # the stored inventory carries the real MIME…
    assert isolated_store.list_inventory("sB")[0]["mime"] == PDF
    handlers._scan_assess({"scan_id": "sB", "user": None}, {"scan_id": "sB"})
    payload = json.loads(next(j["payload"] for j in isolated_store.list_jobs()
                              if j["type"] == "scan_file"))
    # …but the enqueued analysis item's `mime` selector is None (a real PDF is get_media'd, not
    # export_media'd), so _download never indexes EXPORT_MAP with it.
    assert payload["mime"] is None
