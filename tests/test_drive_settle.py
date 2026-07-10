"""Whole-Drive discovery and Google's eventually-consistent search index.

A file uploaded seconds before a scan may not be in files.list yet — the "scanning isn't
picking up my files in real-time" report. The settle-retry re-lists a few times, unioning by
id, so a file that indexes mid-scan is caught. It is opt-in (ACP_DRIVE_SETTLE_SECS): with it
off, discovery is exactly one listing pass, unchanged.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _f(fid, name):
    return {"id": fid, "name": name, "mimeType": PPTX, "md5Checksum": f"md5-{fid}"}


class _FakeFiles:
    """files().list(...).execute() returns the next queued page-set each call. Each queued
    item is a full list of files for that pass (single page — no nextPageToken)."""
    def __init__(self, passes):
        self._passes = list(passes)
        self.calls = 0

    def list(self, **kw):
        self._kw = kw
        return self

    def execute(self, num_retries=0):
        i = min(self.calls, len(self._passes) - 1)
        self.calls += 1
        return {"files": list(self._passes[i]), "nextPageToken": None}


class _FakeSvc:
    def __init__(self, passes):
        self._files = _FakeFiles(passes)

    def files(self):
        return self._files


FOLDER = "application/vnd.google-apps.folder"
IMAGE = "image/png"
DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _typed(fid, name, mime):
    return {"id": fid, "name": name, "mimeType": mime, "md5Checksum": f"md5-{fid}"}


def test_type_filtering_is_client_side_not_a_drive_query(monkeypatch):
    """The core fix: we query only trashed=false (fresh from Drive's live store) and keep the
    scannable types OURSELVES. A mimeType='…' query is served by Drive's search index, which
    lagged so badly that an unfiltered listing saw 60 files while the filtered one saw 2 in the
    same second. So the plain listing returns everything and we drop the non-scannable here."""
    monkeypatch.delenv("ACP_DRIVE_SETTLE_SECS", raising=False)
    svc = _FakeSvc([[
        _typed("A", "brief.docx", DOC),          # scannable
        _typed("B", "deck.pptx", PPTX),          # scannable
        _typed("F", "Legal", FOLDER),            # a folder — not a document
        _typed("I", "logo.png", IMAGE),          # an image — out of scope
    ]])
    out = scanner._search_drive(svc, max_files=100)
    assert {o["id"] for o in out} == {"A", "B"}   # only the two scannable documents

    # and the Drive query carried NO mimeType clause — that is the whole point
    assert "mimeType" not in (svc._files._kw.get("q") or "")
    assert svc._files._kw.get("q") == "trashed=false"


def test_non_scannable_files_do_not_crowd_out_documents_under_the_cap(monkeypatch):
    """Why the type filter runs BEFORE the max_files slice, not only in _normalize afterward:
    if junk (images, folders) filled the first max_files raw items, the slice would be all junk
    and the real documents behind it would be lost. Pre-filtering keeps the slice all-documents."""
    monkeypatch.delenv("ACP_DRIVE_SETTLE_SECS", raising=False)
    batch = ([_typed(f"I{i}", f"pic{i}.png", IMAGE) for i in range(10)] +   # 10 images first…
             [_typed("A", "brief.docx", DOC), _typed("B", "deck.pptx", PPTX)])  # …docs behind them
    svc = _FakeSvc([batch])
    out = scanner._search_drive(svc, max_files=2)                 # cap smaller than the junk run
    assert {o["id"] for o in out} == {"A", "B"}                   # documents survive the slice


def test_a_freshly_bulk_uploaded_corpus_is_all_picked_up(monkeypatch):
    """The reported live case: dozens of docx/pptx/pdf just uploaded. The plain listing sees
    them immediately; every scannable one must be kept, none dropped for lack of an index."""
    monkeypatch.delenv("ACP_DRIVE_SETTLE_SECS", raising=False)
    corpus = [_typed(f"L{i}", f"Legal-{i}.docx", DOC) for i in range(40)]
    corpus.append(_typed("P", "Tax-Motion.pptx", PPTX))
    corpus.append(_typed("D", "Estates.pdf", "application/pdf"))
    svc = _FakeSvc([corpus])
    out = scanner._search_drive(svc, max_files=500)
    assert len(out) == 42


def test_settle_off_is_a_single_listing_pass(monkeypatch):
    """Default behavior is unchanged: one pass, whatever Drive returned that once."""
    monkeypatch.delenv("ACP_DRIVE_SETTLE_SECS", raising=False)
    svc = _FakeSvc([[_f("A", "a.pptx"), _f("B", "b.pptx")]])
    out = scanner._search_drive(svc, max_files=100)
    assert {o["id"] for o in out} == {"A", "B"}
    assert svc._files.calls == 1                     # exactly one listing, no retry


def test_settle_catches_a_file_that_indexes_on_a_later_pass(monkeypatch):
    """The real symptom: pass 1 sees 2 files, the just-uploaded 3rd appears on pass 2. The
    union must include it — that is the whole point of the settle."""
    monkeypatch.setenv("ACP_DRIVE_SETTLE_SECS", "0.01")
    monkeypatch.setenv("ACP_DRIVE_SETTLE_PASSES", "3")
    monkeypatch.setattr(scanner.time, "sleep", lambda s: None)   # no real waiting in tests
    passes = [
        [_f("A", "a.pptx"), _f("B", "b.pptx")],                  # pass 1: the stale 2
        [_f("A", "a.pptx"), _f("B", "b.pptx"), _f("C", "c.pptx")],  # pass 2: C now indexed
    ]
    svc = _FakeSvc(passes)
    out = scanner._search_drive(svc, max_files=100)
    assert {o["id"] for o in out} == {"A", "B", "C"}             # the new file is picked up


def test_settle_stops_early_once_nothing_new_appears(monkeypatch):
    """Convergence: when a follow-up pass adds nothing, we stop rather than burn the whole
    budget — so a steady-state Drive costs one settle pass, not ACP_DRIVE_SETTLE_PASSES of them."""
    monkeypatch.setenv("ACP_DRIVE_SETTLE_SECS", "0.01")
    monkeypatch.setenv("ACP_DRIVE_SETTLE_PASSES", "5")
    monkeypatch.setattr(scanner.time, "sleep", lambda s: None)
    steady = [_f("A", "a.pptx"), _f("B", "b.pptx")]
    svc = _FakeSvc([steady, steady, steady, steady, steady])
    out = scanner._search_drive(svc, max_files=100)
    assert {o["id"] for o in out} == {"A", "B"}
    assert svc._files.calls == 2      # pass 1 + one confirming pass that added nothing → stop


def test_settle_never_double_counts_a_relisted_file(monkeypatch):
    """Union is by id: a file returned on every pass is one document, not three."""
    monkeypatch.setenv("ACP_DRIVE_SETTLE_SECS", "0.01")
    monkeypatch.setenv("ACP_DRIVE_SETTLE_PASSES", "2")
    monkeypatch.setattr(scanner.time, "sleep", lambda s: None)
    a = _f("A", "a.pptx")
    svc = _FakeSvc([[a], [a], [a]])
    out = scanner._search_drive(svc, max_files=100)
    assert len(out) == 1 and out[0]["id"] == "A"
