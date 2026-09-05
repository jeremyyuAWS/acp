"""Remediation progress counts the batch in front of you, not the scan's whole history.

THE NUMBER THIS MAKES IMPOSSIBLE (live 2026-09-04, scan 8b83e9e1ca5c). A 147-document SharePoint
batch failed outright, was submitted again, and failed again. `remediation_status` counted every
dead `remediate_file` row the scan had ever produced, so it answered `failed: 294` for a batch of
147 documents; the UI computed `147 completed - 294 failed` and rendered **-147 documents
remediated**. The root cause was elsewhere (a SharePoint job routed to the Drive downloader — see
test_remediate_sharepoint_source.py), but a retry is a normal thing to do about a failed run, and
no correct root cause stops the second submission from being counted against the first one's
total.

Two independent guards, because they cover different rows:

  * `batch_id`, stamped per submission, scopes the counts to the run being watched.
  * one terminal outcome per DOCUMENT, which keeps the number sane for jobs enqueued before
    batch_id existed (batch_id NULL — there is no batch to scope to).

The invariant both serve: `failed` can never exceed the number of documents in the batch.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from conftest import held

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "rem-batch.db")
    return store_mod.Store()


def _submit(store, sid, files, *, batch_id):
    """One remediation submission: a remediate_file job per document, sharing a batch id."""
    return [store.enqueue_job("remediate_file",
                              {"scan_id": sid, "file": f, "source": "sharepoint"},
                              scan_id=sid, batch_id=batch_id)
            for f in files]


def _kill(store, job_ids, reason="no cached SharePoint source bytes for this scan"):
    for jid in job_ids:
        store.claim_job("w1")
        store.fail_job(jid, reason, force_dead=True, **held(store, jid))


DOCS = [f"doc-{i}.docx" for i in range(3)]


def test_a_second_submission_is_not_counted_against_the_first(store):
    first = _submit(store, "sp-1", DOCS, batch_id="batch-a")
    _kill(store, first)
    assert store.remediation_status("sp-1")["failed"] == len(DOCS)

    # The operator does exactly what the failure message asked for and runs it again.
    second = _submit(store, "sp-1", DOCS, batch_id="batch-b")
    _kill(store, second)

    status = store.remediation_status("sp-1")
    assert status["failed"] == len(DOCS), (
        f"the second batch of {len(DOCS)} reported {status['failed']} failures — this is the "
        f"294-of-147 shape that produced -147 remediated")
    assert status["batch_documents"] == len(DOCS)
    assert status["failed"] <= status["batch_documents"]


def test_the_live_counts_follow_the_newest_batch(store):
    _kill(store, _submit(store, "sp-2", DOCS, batch_id="batch-a"))
    _submit(store, "sp-2", DOCS, batch_id="batch-b")

    status = store.remediation_status("sp-2")
    assert status["batch_id"] == "batch-b"
    assert (status["queued"], status["failed"]) == (len(DOCS), 0), (
        "the batch on screen is queued and has failed nothing; the previous run's dead jobs "
        "belong to the previous run")
    assert status["in_flight"] == len(DOCS)


def test_a_retried_document_counts_once_when_there_is_no_batch_id(store):
    """The fallback guard, for rows enqueued before batch_id was stamped.

    Both jobs are the same document, so the honest answer is one failed document — not two.
    With no batch to scope to this is the only thing standing between a re-run and a failure
    count larger than the batch itself.
    """
    a = store.enqueue_job("remediate_file", {"scan_id": "sp-3", "file": "same.docx"},
                          scan_id="sp-3")
    b = store.enqueue_job("remediate_file", {"scan_id": "sp-3", "file": "same.docx"},
                          scan_id="sp-3")
    _kill(store, [a, b])

    status = store.remediation_status("sp-3")
    assert status["batch_id"] is None, "this test is only meaningful for unbatched rows"
    assert status["failed"] == 1, "two dead jobs for one document are one failed document"


def test_a_scan_that_has_never_been_remediated_reports_nothing(store):
    status = store.remediation_status("sp-4")
    assert (status["failed"], status["in_flight"], status["batch_documents"]) == (0, 0, 0)
    assert status["batch_id"] is None
