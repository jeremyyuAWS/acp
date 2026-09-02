"""Slice 5: the media a reviewer is captioning must be PLAYABLE in the browser.

THE GAP, measured on `origin/main` at 0b71505f. `GET /scans/{id}/files/{name}/content` already
serves a scanned file's original bytes — the HTML remediation path uses it — but its MIME map
knows five document types and nothing else:

    mime_map = {"html": "text/html", "htm": "text/html", "pdf": "application/pdf",
                "docx": …, "xlsx": …, "pptx": …}
    return Response(data, media_type=mime_map.get(ext, "application/octet-stream"))

So a `.mp4` came back as `application/octet-stream`. That is not a shortcoming of taste: a
`<video>` element handed `application/octet-stream` refuses to play it — the browser will not
sniff a media container out of a generic type — so a caption reviewer could not watch the video
they were captioning. Slices 1-4 gave them a transcript to correct with no way to check it
against the audio, which is the one thing the correction actually requires.

WHAT THIS DOES NOT CLAIM. There is no HTTP Range support here, and adding it is a separate piece
of work. Without it a browser must download the whole file before it can seek, so this is honest
for the short clips the transcription cap (ACP_CAPTION_MAX_SECONDS, 600) already limits drafting
to, and poor for anything long. `test_the_response_does_not_claim_range_support` pins that we do
not ADVERTISE what we cannot do — a server that sends `Accept-Ranges: bytes` and then ignores the
header gives the browser a seek bar that silently does nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """The content route with Drive stubbed out. What is under test is the RESPONSE SHAPE, not
    the fetch — so the fetch is replaced and everything the browser sees stays real."""
    import core as core_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import scans as scans_routes

    class _Media:
        def execute(self):
            return MP4

    class _Files:
        def get_media(self, fileId=None):
            return _Media()

    class _Svc:
        def files(self):
            return _Files()

    monkeypatch.setattr(core_mod, "drive_service", lambda request: _Svc())
    monkeypatch.setattr(core_mod, "store", type("S", (), {
        "get_file_drive_id": staticmethod(lambda scan_id, filename: "drive-1"),
    })())
    app = FastAPI()
    app.include_router(scans_routes.router)
    return TestClient(app)


def test_a_video_is_served_as_video(client):
    """THE GAP. `application/octet-stream` is not a media type a <video> element will play, so
    the reviewer had no way to watch what they were captioning."""
    r = client.get("/scans/s1/files/townhall.mp4/content")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("video/mp4"), (
        f"a .mp4 came back as {r.headers['content-type']!r}; a <video> element will not play that")


@pytest.mark.parametrize("name,expected", [
    ("talk.mp4", "video/mp4"),
    ("talk.mov", "video/quicktime"),
    ("talk.webm", "video/webm"),
    ("talk.mkv", "video/x-matroska"),
    ("interview.mp3", "audio/mpeg"),
    ("interview.m4a", "audio/mp4"),
    ("interview.wav", "audio/wav"),
])
def test_every_extension_the_remediation_lane_admits_is_playable(client, name, expected):
    """The set has to match `handlers._AV_REMEDIABLE`, or a file ACP will happily draft captions
    for comes back as a type the reviewer's browser refuses to open — a card that asks for a
    correction nobody can check."""
    r = client.get(f"/scans/s1/files/{name}/content")
    assert r.headers["content-type"].startswith(expected), (
        f"{name} → {r.headers['content-type']!r}, expected {expected}")


def test_the_documents_are_unchanged(client):
    """The control. This map is on the path the HTML remediation preview uses, so widening it
    must not disturb what was already there."""
    for name, expected in (("page.html", "text/html"), ("report.pdf", "application/pdf"),
                           ("doc.docx", "application/vnd.openxmlformats-officedocument"
                                        ".wordprocessingml.document")):
        r = client.get(f"/scans/s1/files/{name}/content")
        assert r.headers["content-type"].startswith(expected), name


def test_an_unknown_extension_still_falls_back_to_octet_stream(client):
    """Widening the map must not turn it into a guess. An unrecognised type is honestly
    unrecognised — inventing a media type for it is how a browser gets told to render something
    as video that is not video."""
    r = client.get("/scans/s1/files/archive.zip/content")
    assert r.headers["content-type"].startswith("application/octet-stream")


def test_the_response_does_not_claim_range_support(client):
    """A seek bar that does nothing is worse than one that is obviously absent.

    This route reads the whole object from Drive and returns it in one Response; it does not
    honour a Range request. Sending `Accept-Ranges: bytes` would tell the browser otherwise, and
    the browser would then offer seeking that silently returns the same full body — the reviewer
    drags the scrubber and the video jumps back. Advertising the capability is the bug; not
    having it yet is a limitation.
    """
    r = client.get("/scans/s1/files/townhall.mp4/content")
    assert "accept-ranges" not in {k.lower() for k in r.headers}, (
        "the response advertises byte ranges it does not serve")


def test_the_bytes_are_returned_unaltered(client):
    """A media file is bytes, not text. Anything that re-encoded it would corrupt the container
    in a way that shows up only in a player."""
    assert client.get("/scans/s1/files/townhall.mp4/content").content == MP4


def test_every_remediable_media_extension_has_a_playable_type():
    """The binding that keeps the map honest, in BOTH directions.

    `handlers._AV_REMEDIABLE` is what the remediation lane admits — the files ACP will draft
    captions for. Every one of them must have a browser MIME type, or the reviewer is handed a
    correction task and a file their browser will not open. And a type declared for an extension
    the lane never sees is dead weight that reads as support.

    TWO SETS, AND THE FIRST DRAFT COMPARED AGAINST THE WRONG ONE. It asserted that every declared
    MIME type appears in the scan scope or the remediation lane, and .wmv/.mpg/.mpeg/.oga/.opus
    /.wma failed it. They are not dead weight: `media.VIDEO_EXTS` and `AUDIO_EXTS` are the
    module's own "is this a media filename" vocabulary and are DELIBERATELY broader than what the
    lane admits — `media_kind` answers for any of them, and constraining the MIME map to the lane
    would leave the same module recognising a file it could not name a type for.

    So the map is bound to `media.py`'s own extension sets, and the LANE is checked separately for
    the property that actually matters to a reviewer: everything ACP will draft captions for has a
    type the browser can open.
    """
    import handlers
    import media

    known = set(media.VIDEO_EXTS) | set(media.AUDIO_EXTS)
    assert set(media.MEDIA_MIME_TYPES) == known, (
        f"only in the MIME map: {sorted(set(media.MEDIA_MIME_TYPES) - known)}; "
        f"recognised as media with no type: {sorted(known - set(media.MEDIA_MIME_TYPES))}")

    missing = [e for e in handlers._AV_REMEDIABLE if media.media_mime(f"x{e}") is None]
    assert not missing, (
        f"{missing} can reach the caption lane and have no playable MIME type — the reviewer "
        f"gets a draft to correct and a file the browser refuses to open")
