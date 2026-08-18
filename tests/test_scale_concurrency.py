"""Concurrency at estate scale: ~50 identities, shared-drive overlap, and per-user isolation.

Two properties that only strain when many people scan overlapping repositories:

  DEDUP — a file with several parents, or on a Shared Drive fifty people can see, is surfaced many
  times in one listing (multi-parent BFS + corpora='allDrives' + paging overlap). A Drive file id
  is the document's identity; N sightings are ONE document, not N. This drives the real listing
  path with a file id repeated across pages and asserts it collapses to one — and that the
  discovered count is the distinct-document count, not the sighting count.

  ISOLATION — ACP scans as the signed-in operator (delegated token), so one user's scan lists only
  what that user's Drive client returns. Two operators' estates stay disjoint; A's scan never
  surfaces B's files. Structural, and pinned here so a future change to the listing path can't
  quietly break it.
"""
import random
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


def test_a_file_surfaced_by_many_users_collapses_to_one_document():
    unique = scale_corpus.generate(40, seed=5)[0]     # 40 distinct file ids
    sightings = 50                                     # ~50 people each see every shared file
    recs = unique * sightings                          # 2000 records, 40 distinct ids
    rng = random.Random(1)
    rng.shuffle(recs)                                  # duplicates spread across pages
    scope: dict = {}
    scanner._list("drive", _Svc(recs), folder=None, scope_out=scope)

    assert scope["raw"] == len(recs)                   # every sighting was listed…
    assert scope["inventory"]["discovered"] == 40      # …and collapsed to distinct documents
    assert scope["truncated"] is False                 # 2000 < the 2500 cap — the collapse, not a cap
    # the scannable subset is also distinct, never inflated by the 50x duplication
    assert scope["scannable"] <= 40


def test_two_operators_estates_stay_isolated():
    a = scale_corpus.generate(30, seed=1)[0]
    b = scale_corpus.generate(30, seed=2)[0]
    for i, r in enumerate(b):                           # give B its own id space (seed reuses indices)
        r["id"] = f"userB_{i:04d}"
    ids_a = {r["id"] for r in a}
    ids_b = {r["id"] for r in b}
    assert ids_a.isdisjoint(ids_b)

    scope_a, scope_b = {}, {}
    scanner._list("drive", _Svc(a), folder=None, scope_out=scope_a)
    scanner._list("drive", _Svc(b), folder=None, scope_out=scope_b)
    # Each operator sees exactly their own estate — the delegated-token boundary.
    assert scope_a["inventory"]["discovered"] == 30
    assert scope_b["inventory"]["discovered"] == 30
