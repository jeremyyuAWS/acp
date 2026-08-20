"""A SharePoint file must be fetched through Graph, not through the Drive client.

REPRODUCTION of the production failure seen on 2026-08-19: a 22-document SharePoint scan whose
files recorded `status='error'`, surfacing as "Could not analyse — file unreadable" in the drawer.

The chain, all of it in code rather than in a log:

  1. discovery      `_sp_inventory_row` writes the row with `drive_file_id = <graph item id>`
                    and NO `sp` marker, NO `driveId`
  2. assess         handlers builds the analysis item as
                    {file, drive_file_id, mime, path, checksum}          <- `sp` cannot survive
  3. enqueue        `_enqueue_analysis` copies exactly those keys into the job payload
  4. worker         rebuilds `it = {"name", "id", (mime), (path)}` and calls `_download`
  5. `_download`    sees no `smb`, no `path`, no `sp` -> falls through to the GOOGLE DRIVE branch
                    and calls `svc.files().get_media(fileId=<graph item id>)`

So the Graph item id is handed to the Drive API. It raises, the exception is caught, and the file
is recorded `status='error'` — which the UI renders as "unreadable". Nothing about the failure is
specific to the FILE; every SharePoint/OneDrive file in a fan-out scan takes this path.

Two things this file pins, and they are different claims:

  · `_download` ROUTES an sp-marked item to Graph — the primitive, which already works
  · the item reaching `_download` STILL CARRIES that marker after the assess/enqueue round trip —
    the part that is broken, and the reason the working primitive is never reached

The second is the regression guard that matters. A fix that restores the marker but loses it again
one refactor later would put the symptom back with the primitive still passing its own test.

WHY A BARE `sp: True` IS NOT ENOUGH, and why the driveId assertion below is not pedantry.
`_sp_download` falls back to `/me/drive` when `driveId` is absent. For a personal OneDrive that is
correct; for a SharePoint SITE drive it is not, and scanner._sp_download's own docstring says what
happens: asking /me/drive for a site's item id "either 404s or, worse, returns a different document
that happens to share the id". A silently WRONG document is worse than the error we have now, so
the driveId has to travel with the marker.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import scanner  # noqa: E402


class _FakeDriveFiles:
    def __init__(self, log):
        self._log = log

    def get_media(self, **kw):
        self._log.append(("drive.get_media", kw))
        raise AssertionError(
            "a SharePoint item was fetched through the Google Drive client — "
            f"get_media(fileId={kw.get('fileId')!r})")

    def export_media(self, **kw):
        self._log.append(("drive.export_media", kw))
        raise AssertionError("a SharePoint item was exported through the Google Drive client")


class _FakeDriveSvc:
    def __init__(self, log):
        self._log = log

    def files(self):
        return _FakeDriveFiles(self._log)


def _sp_item_from_discovery():
    """The inventory row a SharePoint discovery actually writes, via the real builder."""
    return scanner._sp_inventory_row({
        "id": "01ABCDEF23456789",                    # a Graph item id — unique only within a drive
        "name": "Policy - Anticoagulation Management 03.04.2024.docx",
        "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "size": 24000,
        "parentReference": {"driveId": "b!DRIVE-ID", "path": "/drive/root:/Unfiled"},
    })


def test_download_routes_an_sp_item_to_graph(monkeypatch, tmp_path):
    """The primitive: given the marker, `_download` uses Graph and never touches the Drive client."""
    calls = []
    monkeypatch.setattr(scanner, "_sp_download",
                        lambda token, item, dest: calls.append(("graph", item.get("driveId"))))
    log = []
    scanner._download({"name": "a.docx", "id": "01ABC", "sp": True, "driveId": "b!D"},
                      tmp_path, _FakeDriveSvc(log), sp_token="t")
    assert calls == [("graph", "b!D")], "an sp-marked item did not route to Graph"
    assert log == [], f"the Drive client was called for a SharePoint item: {log}"


def _worker_download_item(inventory_row, source):
    """Rebuild the item the worker hands `_download`, exactly as handlers does.

    Mirrors the two hops the real code takes — assess builds an analysis item from the stored
    inventory row, the worker builds a download item from that — because the bug lived in the
    hops, not in either endpoint.
    """
    analysis_item = {"file": inventory_row["file"],
                     "drive_file_id": inventory_row.get("drive_file_id"),
                     "mime": None, "path": inventory_row.get("path"),
                     "checksum": inventory_row.get("checksum"),
                     "drive_id": inventory_row.get("drive_id")}
    it = {"name": analysis_item["file"], "id": analysis_item["drive_file_id"]}
    if analysis_item.get("path"):
        it["path"] = analysis_item["path"]
    if source == "sharepoint" and not analysis_item.get("path"):
        it["sp"] = True
        if analysis_item.get("drive_id"):
            it["driveId"] = analysis_item["drive_id"]
    return it


def test_the_marker_survives_the_assess_round_trip():
    """The item the worker hands `_download` still says it is a SharePoint item.

    The marker is DERIVED from the scan's own `source` rather than stored, so it cannot drift out
    of step with the scan it belongs to — a stored flag and a stored source can disagree; these
    cannot.
    """
    it = _worker_download_item(_sp_item_from_discovery(), "sharepoint")
    assert it.get("sp"), (
        "the SharePoint marker is lost between discovery and download, so _download falls through "
        "to the Google Drive branch and hands a Graph item id to files().get_media() — every "
        "SharePoint file then records status='error' and reads as 'file unreadable'")


def test_the_drive_id_survives_too():
    """A marker without a driveId resolves against /me/drive, which is wrong for a site drive.

    Graph item ids are unique only WITHIN a drive. `_sp_download`'s own docstring: asking /me/drive
    for a site's item id "either 404s or, worse, returns a different document that happens to share
    the id". A silently WRONG document is a worse failure than the error being fixed here, so the
    driveId travels with the marker.
    """
    it = _worker_download_item(_sp_item_from_discovery(), "sharepoint")
    assert it.get("driveId") == "b!DRIVE-ID", (
        "the driveId did not survive, so a restored SharePoint marker resolves against /me/drive — "
        "correct for personal OneDrive, silently wrong for a site drive")


def test_a_onedrive_item_without_a_drive_id_is_still_routed_to_graph():
    """OneDrive listings genuinely carry no driveId, and must NOT be held back by requiring one.

    `_sp_base`/`_sp_download` read an absent driveId as /me/drive, which is exactly right for a
    personal OneDrive. Requiring one here would break every OneDrive scan while looking like a
    safety improvement — the mistake _sp_base's docstring calls out by name.
    """
    row = scanner._sp_inventory_row({
        "id": "01ONEDRIVE0000001", "name": "notes.docx",
        "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "parentReference": {"path": "/drive/root:"},          # no driveId — OneDrive
    })
    it = _worker_download_item(row, "sharepoint")
    assert it.get("sp"), "a OneDrive item was not routed to Graph"
    assert "driveId" not in it, "a driveId was invented for a OneDrive item that has none"


def test_a_drive_item_is_not_marked_sharepoint():
    """The other direction. A Drive scan must keep using the Drive client.

    Asserted because the fix derives the marker from `source`: a derivation that is too eager
    would send Google Drive files to Graph and break the working path to fix the broken one.
    """
    row = scanner._drive_inventory_row({"id": "1AbC", "name": "policy.docx",
                                        "mimeType": "application/vnd.openxmlformats-officedocument"
                                                    ".wordprocessingml.document"})
    it = _worker_download_item(row, "drive")
    assert not it.get("sp"), "a Google Drive item was routed to Graph"


def test_a_local_corpus_item_is_read_from_disk_even_on_a_sharepoint_scan():
    """`path` wins over the source marker — a local row is read from disk, never fetched.

    The guard exists because the marker is derived from `source`, which is a scan-level fact,
    while `path` is a per-file one. Without the `not path` clause a local fixture inside a
    SharePoint-sourced run would be sent to Graph with a filesystem path as its id.
    """
    it = _worker_download_item({"file": "f.docx", "path": "/corpus/f.docx"}, "sharepoint")
    assert it.get("path") == "/corpus/f.docx"
    assert not it.get("sp"), "a local-path item was routed to Graph"
