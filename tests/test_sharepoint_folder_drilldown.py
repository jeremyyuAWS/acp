"""The folder picker's drill-down: the ids this endpoint hands out must be valid inputs to it.

`GET /sharepoint/folders` MINTS its folder ids as `<driveId>/<itemId>` pairs, deliberately — a
Graph item id is unique only within its drive, so a bare id does not identify a folder (the same
reasoning that made `_sp_download` fetch the wrong file when the drive was dropped). The picker
then sends the id of the folder you clicked straight back as `?parent=`.

Nothing split it again. So the FIRST click into any folder built

    /drives/<driveId>/items/<driveId>/<itemId>/children

and Graph answered `400 Bad Request` — with the drive id visibly twice in the URL. Observed in
production on 2026-08-20 against a OneDrive "Home Drives" folder.

The root listing worked, because "root" contains no "/". That is precisely why this shipped: the
picker opened correctly every time and only failed on the first drill-down, so the endpoint looked
healthy in exactly the state anyone would check it in.

The endpoint had NO tests at all before this file. Guarded here:

  · a composite `<driveId>/<itemId>` parent reaches Graph as the BARE item id
  · the drive in the composite wins over a stale `drive_id` query param
  · a bare item id still works (the form an older caller may send)
  · "root" still resolves the default drive and asks for /root/children
  · the ids handed back are still composites — the round trip is closed, not broken open
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import scanner  # noqa: E402
from app import app  # noqa: E402

DRIVE = "b!C4KL1AKEIU2Bh5cDUao2FK3nO4gYqkJJu_gC8I0_iMGlvE5bq1X9RbBtVHxKCWcp"
ITEM = "01UABCDEFGHIJKLMNOPQRSTUVWXYZ"


@pytest.fixture
def graph(monkeypatch):
    """Capture the (drive_id, item_id) the route hands to the Graph layer."""
    calls: list[tuple[str, str]] = []

    def fake_folders(token, drive_id, item_id="root"):
        calls.append((drive_id, item_id))
        return [{"id": "01CHILD", "name": "Clinical Guidelines", "drive_id": drive_id,
                 "child_count": 3}]

    monkeypatch.setattr(scanner, "_sp_folders", fake_folders)
    monkeypatch.setattr(scanner, "_sp_default_drive", lambda token, site=None: "b!DEFAULTDRIVE")
    monkeypatch.setattr("routes.sharepoint._token", lambda request: "tok")
    return calls


def _get(params):
    return TestClient(app).get("/sharepoint/folders", params=params)


def test_a_composite_parent_reaches_graph_as_a_bare_item_id(graph):
    """THE bug. `items/<driveId>/<itemId>` is not a Graph path and never was."""
    r = _get({"parent": f"{DRIVE}/{ITEM}"})
    assert r.status_code == 200, r.text
    assert graph == [(DRIVE, ITEM)], (
        "the composite id was passed through whole — this rebuilds the 400 Bad Request")


def test_the_drive_in_the_parent_wins_over_a_stale_query_param(graph):
    """The composite names the drive the item actually lives in; a `drive_id` param may be stale.

    Preferring the param would look up a real item id in the WRONG library — which either 404s or,
    worse, finds a different file of that id. That is the failure `_sp_folders`' own docstring
    exists to prevent, one layer up.
    """
    _get({"parent": f"{DRIVE}/{ITEM}", "drive_id": "b!SOMEOTHERDRIVE"})
    assert graph == [(DRIVE, ITEM)]


def test_a_bare_item_id_still_works(graph):
    """An older caller may hold a bare id. Accepting both is why this splits rather than requires."""
    _get({"parent": ITEM, "drive_id": DRIVE})
    assert graph == [(DRIVE, ITEM)]


def test_root_resolves_the_default_drive(graph):
    """The path that always worked, pinned so the fix cannot regress it."""
    r = _get({"parent": "root"})
    assert r.status_code == 200
    assert graph == [("b!DEFAULTDRIVE", "root")]


def test_the_ids_handed_back_are_still_composites(graph):
    """The round trip must stay closed: what this returns is what it accepts.

    Returning bare ids would 'fix' the 400 by breaking the property the pairs exist for — the
    caller would have to re-attach the drive, which is the bug `_sp_folders` documents.
    """
    r = _get({"parent": f"{DRIVE}/{ITEM}"})
    body = r.json()
    assert body["folders"][0]["id"] == f"{DRIVE}/01CHILD"
    assert body["folders"][0]["item_id"] == "01CHILD"
    # And that returned id, fed straight back, must reach Graph split.
    graph.clear()
    _get({"parent": body["folders"][0]["id"]})
    assert graph == [(DRIVE, "01CHILD")]
