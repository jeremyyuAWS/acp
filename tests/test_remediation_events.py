"""Remediation writes the durable lifecycle log — Phase 2 of the real-time operations panel.

The panel needs a resumable narrative of one run. ADR 0042 already built exactly that for scans:
`scan_events`, with a monotonic per-scan `seq` behind a UNIQUE index and `list_scan_events(
after_seq=...)` as the resume read. Remediation simply never wrote to it.

So these tests are about ONE LOG. A second remediation_events table beside this one would fork the
ordering guarantee — two logs anchored on the same scan with no defined interleaving is worse than
either alone — and the tests that matter most here pin the properties that make a single log
usable: the sequence is gap-free under the parallel writers remediation actually has, an event is
never emitted for a durable write that did not happen, and the vocabulary cannot drift.
"""
from __future__ import annotations
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
REMEDIATION_KINDS = {
    "remediate.accepted", "remediate.fix_applied", "remediate.verified",
    "remediate.verification_failed", "remediate.delivered", "remediate.delivery_failed",
    "remediate.review_requested", "remediate.document_completed",
}


def test_the_remediation_vocabulary_is_declared():
    """Every kind the emit sites use, declared in one place. `scan_event` swallows the ValueError
    for an unknown kind at runtime (deliberately — a typo must not fail a real remediation), so
    this and the static walk in test_scan_events_emitted.py are the only things that catch one."""
    import store as store_mod
    assert REMEDIATION_KINDS <= store_mod.Store.SCAN_EVENT_KINDS


def test_remediation_events_share_the_scan_sequence_rather_than_starting_their_own():
    """One log. A remediation event and a scan event on the same run take positions in the SAME
    monotonic sequence, which is what lets a single `after_seq` cursor resume both."""
    import store as store_mod
    store = store_mod.Store()
    sid = "s-seq-shared"
    a = store.append_scan_event(sid, "scan.discovered", owner_email=OWNER)
    b = store.append_scan_event(sid, "remediate.accepted", owner_email=OWNER,
                                detail={"documents": 3})
    c = store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                detail={"file": "a.docx", "fixes": 2})
    assert [a, b, c] == [1, 2, 3]
    kinds = [e["kind"] for e in store.list_scan_events(sid, owner=OWNER)]
    assert kinds == ["scan.discovered", "remediate.accepted", "remediate.fix_applied"]


def test_the_resume_read_returns_only_what_a_client_missed():
    """PRD §8: "the browser reconnects with the last event ID". `after_seq` IS that read, and it
    already existed — this pins that remediation events flow through it unchanged."""
    import store as store_mod
    store = store_mod.Store()
    sid = "s-seq-resume"
    for i in range(5):
        store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                detail={"file": f"{i}.docx"})
    missed = store.list_scan_events(sid, after_seq=2, owner=OWNER)
    assert [e["seq"] for e in missed] == [3, 4, 5]
    assert store.list_scan_events(sid, after_seq=5, owner=OWNER) == []


def test_the_sequence_survives_the_parallel_writers_remediation_actually_has():
    """Remediation FANS OUT, which the scan.* kinds never did — append_scan_event's own docstring
    says the path is "barely contended (run-level transitions come one at a time per job)", and
    that assumption does not carry here.

    The DESIGN does carry, and this is the check that establishes it rather than assuming it from
    the docstring: eight concurrent writers, every event landed, no gaps, no duplicates. A gap
    would break resume (a client would wait forever for a seq nobody wrote); a duplicate would
    break ordering.
    """
    import store as store_mod
    store = store_mod.Store()
    sid = "s-seq-race"
    got, errors = [], []
    lock = threading.Lock()

    def _append(i):
        try:
            seq = store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                          detail={"file": f"{i}.docx"})
            with lock:
                got.append(seq)
        except Exception as e:                      # noqa: BLE001 — recorded, then asserted on
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=_append, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert sorted(got) == list(range(1, 9)), f"gaps or duplicates in {sorted(got)}"
    assert [e["seq"] for e in store.list_scan_events(sid, owner=OWNER)] == list(range(1, 9))


def test_an_event_carries_the_filename_but_never_document_content():
    """PRD §13: activity events contain no extracted document content. The filename is in the
    detail payload (scan_events has no file column, and adding one would migrate a table five
    other kinds share); the read path is owner-scoped, which is what makes that safe."""
    import store as store_mod
    store = store_mod.Store()
    sid = "s-detail"
    store.append_scan_event(sid, "remediate.verified", owner_email=OWNER,
                            detail={"file": "Board Pack.pdf", "fixes": 4})
    event = store.list_scan_events(sid, owner=OWNER)[0]
    detail = event["detail"]
    assert detail["file"] == "Board Pack.pdf"
    assert set(detail) == {"file", "fixes"}     # nothing else rode along


def test_a_foreign_reader_gets_nothing(monkeypatch):
    """Owner-scoped, because these rows now carry filenames and SharePoint paths."""
    import store as store_mod
    store = store_mod.Store()
    sid = "s-owner"
    store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                            detail={"file": "secret.docx"})
    assert store.list_scan_events(sid, owner=OWNER) != []
    assert store.list_scan_events(sid, owner="stranger@example.com") == []


# ── the emit sites, checked by their placement rather than their end state ────

def test_delivery_is_reported_against_the_destination_not_the_correction():
    """PRD §11's delivery-failure class, at the emit site.

    `record_remediation` is called with `drive_write_url=None` whenever the provider write did not
    happen — mirror disabled, a 403, a non-Drive source. The corrected copy still exists in blob.
    Calling that `delivered` would make a lost corrected copy invisible, which is the whole reason
    stored and delivered are counted apart (§17.8). So the emit site branches on `web_url`, and
    this reads the source to prove it still does.
    """
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    marker = 'core.store.record_remediation(scan_id, filename, drive_write_url=web_url'
    assert marker in src
    after = src[src.index(marker):src.index(marker) + 1200]
    assert '"remediate.delivered" if web_url else "remediate.delivery_failed"' in after, (
        "the delivery event no longer branches on whether a destination was actually written")


def test_every_remediation_event_is_emitted_after_its_durable_write():
    """ADR 0042's ordering rule — an event is appended AFTER the write it describes, never before.

    Checked by source position, because the end state cannot tell the two apart: both orderings
    leave the same rows behind, and only a reader that arrives between them sees the difference.
    A "fix applied" event that leads its `applied_fixes` INSERT is a panel claiming work the
    database cannot yet show.
    """
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    for write, event in (
        ("_record_applied_fixes(scan_id, filename, _applied_fixes)", '"remediate.fix_applied"'),
        ("core.store.record_remediation_diffs(scan_id, filename, verified_diffs)", '"remediate.verified"'),
        ("core.store.record_remediation(scan_id, filename, drive_write_url=web_url", '"remediate.delivered"'),
    ):
        assert write in src, f"anchor moved: {write}"
        assert event in src, f"emit missing: {event}"
        assert src.index(write) < src.index(event), (
            f"{event} is emitted BEFORE its durable write ({write})")


def test_a_merged_review_deferral_does_not_re_announce_the_same_request():
    """`queue_hitl_deferral` is idempotent per (scan, file, criterion) and returns None when it
    merged rather than created. Emitting on the merge would narrate the same review request once
    per retry, which is how a bounded activity feed fills with one event."""
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert "_queued_item = core.store.queue_hitl_deferral(" in src
    guard = src[src.index("_queued_item = core.store.queue_hitl_deferral("):][:700]
    assert "if _queued_item:" in guard
    assert guard.index("if _queued_item:") < guard.index('"remediate.review_requested"')


def test_acceptance_is_not_re_announced_for_a_reused_execution():
    """PRD §7's Accepted is a RUN-level transition: durable work exists and nothing has claimed it.

    `enqueue_stage_batch` is idempotent on the request fingerprint — re-submitting the same file
    set returns the EXISTING batch rather than creating one. That is the same run, already
    accepted. A second acceptance event for work that was never re-enqueued would make a client
    replaying the log see one run start twice, and would put an acceptance in the history with no
    enqueue behind it.
    """
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "scans.py").read_text()
    assert '"remediate.accepted"' in src
    before = src[:src.index('"remediate.accepted"')]
    guard = before[-400:]
    assert 'execution["job_ids"] and not execution.get("reused")' in guard, (
        "acceptance is no longer guarded on a NEW execution having enqueued work")

def test_the_remediation_handler_is_still_the_one_the_queue_calls():
    """The registry maps `remediate_file` to `_remediate_file`, and nothing else.

    THIS TEST EXISTS BECAUSE THE REST OF THIS FILE COULD NOT CATCH WHAT BROKE IT. Adding the
    `_rem_event` helper immediately above `_remediate_file` put it between that function and its
    `@handler("remediate_file")` decorator, so the DECORATOR REGISTERED THE HELPER: every
    remediation job called a four-argument narration function with (payload, job), raised
    TypeError, and retried until dead. Remediation was completely broken.

    Every test in this file still passed. They read source text — that an emit follows its write,
    that a branch is still a branch — and source text was exactly right; only what the decorator
    bound to had changed. A source-reading test cannot see a decorator binding, and the full suite
    is what found it (tests/test_jobs.py, which actually runs a job).

    So this asserts the binding itself, which is cheap, and it is the one check here that executes
    rather than reads.
    """
    import handlers                                    # noqa: F401 — importing registers them
    import worker
    assert worker.HANDLERS["remediate_file"].__name__ == "_remediate_file"
    # The helper must not be registered as a handler under ANY key.
    assert "_rem_event" not in {fn.__name__ for fn in worker.HANDLERS.values()}
