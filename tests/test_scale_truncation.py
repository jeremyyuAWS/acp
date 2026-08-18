"""Discovery truncation at scale: an estate larger than the cap is reported as a FLOOR, never complete.

#292 added the honest-truncation flag; this drives the REAL paging path (scanner._search_drive ->
_list_drive_page_all) with a mocked Drive that pages past the raw cap, and asserts scope['truncated']
and scope['inventory']['truncated'] both fire — and that a small estate is not falsely flagged.
Silent truncation on a 30k estate (counts that read as complete when they are not) is the exact
failure the whole-estate inventory exists to prevent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scanner  # noqa: E402
import scale_corpus  # noqa: E402


class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self, **kw):
        return self._payload


class _PagedFiles:
    """A Drive files() double that serves `records` in fixed-size pages, keeping a nextPageToken
    until the last page — so a listing that stops at the raw cap still sees a token (hit_cap)."""

    def __init__(self, records, page=500):
        self.pages = [records[i:i + page] for i in range(0, len(records), page)] or [[]]

    def list(self, **kw):
        if "trashed=false" not in kw.get("q", ""):
            return _Exec({"files": []})
        token = kw.get("pageToken")
        idx = 0 if token is None else int(token)
        payload = {"files": self.pages[idx] if idx < len(self.pages) else []}
        if idx + 1 < len(self.pages):
            payload["nextPageToken"] = str(idx + 1)
        return _Exec(payload)


class _Svc:
    def __init__(self, records):
        self._f = _PagedFiles(records)

    def files(self):
        return self._f


def _records(n, seed=2):
    files, _folders, _man = scale_corpus.generate(n, seed=seed)
    return files


def test_an_estate_larger_than_the_cap_is_flagged_truncated():
    # raw_cap floors at 2500; 3000 files means the listing stops with a page token still pending.
    svc = _Svc(_records(3000))
    scope: dict = {}
    scanner._list("drive", svc, folder=None, scope_out=scope)
    assert scope["truncated"] is True
    inv = scope["inventory"]
    assert inv["truncated"] is True                 # the inventory says its counts are a FLOOR
    assert 0 < inv["discovered"] <= 3000            # only what was listed before the cap
    # sanity: the buckets still partition what WAS listed
    assert sum(inv["by_status"].values()) == inv["discovered"]


def test_a_small_estate_is_not_falsely_flagged():
    svc = _Svc(_records(120))
    scope: dict = {}
    scanner._list("drive", svc, folder=None, scope_out=scope)
    assert scope["truncated"] is False
    assert scope["inventory"]["truncated"] is False
    assert scope["inventory"]["discovered"] == 120
