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


def test_the_marker_survives_the_assess_round_trip():
    """THE BUG. The item the worker hands to `_download` must still say it is a SharePoint item.

    Built the way handlers does it at the assess call site — from the stored inventory row — so
    this fails for the real reason rather than a re-typed approximation of it.
    """
    row = _sp_item_from_discovery()

    # handlers._scan_assess builds the analysis item from the inventory row with exactly these keys.
    analysis_item = {"file": row["file"], "drive_file_id": row.get("drive_file_id"),
                     "mime": None, "path": row.get("path"), "checksum": row.get("checksum")}
    # ...and the worker rebuilds the download item from that.
    download_item = {"name": analysis_item["file"], "id": analysis_item["drive_file_id"]}
    if analysis_item.get("path"):
        download_item["path"] = analysis_item["path"]

    assert download_item.get("sp"), (
        "the SharePoint marker is lost between discovery and download, so _download falls through "
        "to the Google Drive branch and hands a Graph item id to files().get_media() — every "
        "SharePoint file then records status='error' and reads as 'file unreadable'")


def test_the_drive_id_survives_too():
    """A marker without a driveId resolves against /me/drive, which is wrong for a site drive.

    Graph item ids are unique only WITHIN a drive. `_sp_download`'s own docstring: asking /me/drive
    for a site's item id "either 404s or, worse, returns a different document that happens to share
    the id". Analysing the wrong document is a worse failure than the error being fixed here, so
    the fix has to carry the driveId — and the inventory row does not currently record one.
    """
    row = _sp_item_from_discovery()
    assert row.get("driveId"), (
        "the inventory row records no driveId, so a restored SharePoint marker would resolve "
        "against /me/drive — correct for personal OneDrive, silently wrong for a site drive")
