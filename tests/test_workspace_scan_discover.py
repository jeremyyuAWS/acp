"""api/handlers.py::_workspace_scan_discover (ADR 0044) — Discover over an uploaded workspace.

WHAT THIS ADDS TO #1116. That PR connected ONE stored version to the existing engine: a
per-version assess endpoint and a workspace_scan_file job. This is the enumeration half — upload
a folder, assess what was uploaded, as one run with one total and one completion. Together they
are the customer flow: upload → Discover → Assess.

WHY THE ENUMERATION LIVES IN THE WORKER AND NOT THE ROUTE, which is the design claim most worth
testing. The connector Discover path crashes inside its initial _list(...) walk — minutes of
paginated traffic before any checkpoint exists, which is exactly why ACP_PER_FOLDER_SCAN_JOBS
could not have protected it (the fan-out block sits below that walk). A workspace enumeration is
one indexed SELECT over rows durably written at upload time. There is no walk to interrupt and no
token to expire mid-listing, so the handler can simply re-run: it re-reads the population and
enqueues only what is missing. The resume test below is the one that pins that property.

THE COUNTS ARE THE OTHER HALF. `files` must equal what was actually enqueued or the run can never
finalize — count_files_done compares file_records against it, and a document that was never
enqueued writes no row. But a quarantined or duplicate upload silently vanishing from the total is
its own dishonesty: the customer uploaded it. "12 assessed, 3 excluded" is the answer; "12 of 12"
over an estate of 15 is not. Both directions are pinned.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"
WS = "ws1"


@pytest.fixture()
def st(isolated_store, monkeypatch):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.create_content_workspace(WS, owner_email=OWNER, name="Q3 policies")
    return isolated_store


def _doc(st, doc_id, *, path, state="ready", filename=None, versions=1, owner=OWNER):
    """One document plus its versions. `state` is the LATEST version's lifecycle_state, which is
    what eligibility reads; `versions=0` leaves a document with no version at all — the shape an
    upload session that was created and never completed leaves behind."""
    st.create_content_workspace_document(doc_id, workspace_id=WS, owner_email=owner,
                                         display_name=Path(path).name, relative_path=path)
    for seq in range(1, versions + 1):
        st.create_content_workspace_document_version(
            f"{doc_id}-v{seq}", document_id=doc_id, version_seq=seq,
            content_hash=f"hash-{doc_id}-{seq}",
            original_filename=filename or Path(path).name,
            lifecycle_state=("ready" if seq < versions else state))


def _run(st, scan_id="s-ws"):
    """Create the run the way the route does, then hand back (scan_id, payload, job).

    get_job decodes `payload` into a dict; list_scan_jobs_of_type returns the raw column. The
    two are handed out separately here so no test has to remember which is which.
    """
    scan_id, job_id = st.enqueue_scan(
        scan_id, "workspace", OWNER, "workspace_scan_discover",
        {"scan_id": scan_id, "workspace_id": WS, "user": OWNER})
    job = st.get_job(job_id)
    payload = job["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return scan_id, payload, job


def _fanned_out(st, scan_id):
    out = []
    for j in st.list_scan_jobs_of_type(scan_id, "workspace_scan_file"):
        pl = j["payload"]
        out.append(json.loads(pl) if isinstance(pl, str) else pl)
    return out


def _files_total(st, scan_id):
    """The run's `files` total — the denominator count_files_done compares against. Read off
    get_scan()["run"], not get_scan()["files"]: that key is the per-file ROWS, and reading it
    by name gives a list that compares unequal to every integer without ever looking wrong."""
    return ((st.get_scan(scan_id) or {}).get("run") or {}).get("files")


# ── the fan-out ───────────────────────────────────────────────────────────────────────────────

def test_every_ready_document_becomes_one_durable_job(st):
    _doc(st, "d1", path="policies/handbook.docx")
    _doc(st, "d2", path="policies/2026/rates.xlsx")
    _doc(st, "d3", path="report.pdf")
    import handlers
    scan_id, payload, job = _run(st)

    handlers._workspace_scan_discover(payload, job)

    out = _fanned_out(st, scan_id)
    assert len(out) == 3
    assert {p["version_id"] for p in out} == {"d1-v1", "d2-v1", "d3-v1"}
    assert all(p["workspace_id"] == WS and p["user"] == OWNER for p in out)
    assert _files_total(st, scan_id) == 3


def test_the_folder_structure_survives_into_the_scan(st):
    """relative_path is what makes two uploads with the same base name distinguishable, and
    preserving folder structure is the first thing the upload flow promises."""
    _doc(st, "d1", path="policies/2026/rates.xlsx", filename=None)
    _doc(st, "d2", path="archive/2025/rates.xlsx", filename=None)
    import handlers
    scan_id, payload, job = _run(st)
    handlers._workspace_scan_discover(payload, job)

    eligible, _ = handlers._workspace_scan_population(WS, OWNER)
    assert len(eligible) == 2
    assert len(_fanned_out(st, scan_id)) == 2


def test_the_latest_version_is_the_one_assessed(st):
    """A re-upload creates a new version. Assessing v1 after v2 exists would report on bytes the
    customer has already replaced."""
    _doc(st, "d1", path="handbook.docx", versions=3)
    import handlers
    scan_id, payload, job = _run(st)
    handlers._workspace_scan_discover(payload, job)
    assert [p["version_id"] for p in _fanned_out(st, scan_id)] == ["d1-v3"]


# ── honest counts ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", ["quarantined", "duplicate", "expired"])
def test_a_document_that_is_not_ready_is_excluded_with_a_reason(st, state):
    _doc(st, "ok", path="good.docx")
    _doc(st, "bad", path="suspect.docx", state=state)
    import handlers
    scan_id, payload, job = _run(st)
    handlers._workspace_scan_discover(payload, job)

    assert [p["version_id"] for p in _fanned_out(st, scan_id)] == ["ok-v1"]
    # `files` is the ENQUEUED population — anything else and count_files_done can never reach it.
    assert _files_total(st, scan_id) == 1
    # …and the excluded document is recorded, not dropped.
    reasons = [d for d in st.list_decisions(scan_id=scan_id)
               if d["action"] == "content_workspace.excluded_from_scan"]
    assert len(reasons) == 1
    assert reasons[0]["file"] == "suspect.docx"
    assert state in reasons[0]["detail"]


def test_a_document_whose_upload_never_completed_is_excluded(st):
    _doc(st, "ok", path="good.docx")
    _doc(st, "stub", path="never-finished.docx", versions=0)
    import handlers
    scan_id, payload, job = _run(st)
    handlers._workspace_scan_discover(payload, job)
    assert [p["version_id"] for p in _fanned_out(st, scan_id)] == ["ok-v1"]
    reasons = [d for d in st.list_decisions(scan_id=scan_id)
               if d["action"] == "content_workspace.excluded_from_scan"]
    assert len(reasons) == 1 and "never completed" in reasons[0]["detail"]


def test_another_owners_workspace_yields_nothing(st):
    """Owner scoping is the tenant boundary this whole app uses. The enumeration must not widen
    it just because it runs in a worker rather than behind a route."""
    _doc(st, "mine", path="mine.docx")
    import handlers
    eligible, excluded = handlers._workspace_scan_population(WS, "mallory@evil.com")
    assert eligible == [] and excluded == []


# ── the empty workspace, which is where a run gets stuck ──────────────────────────────────────

def test_a_workspace_with_nothing_ready_still_finalizes(st):
    """No per-file job means nothing will ever trigger scan_finalize — the run sits 'queued'
    forever. Mirrors _enqueue_analysis's own empty-items branch."""
    _doc(st, "bad", path="suspect.docx", state="quarantined")
    import handlers
    scan_id, payload, job = _run(st)
    handlers._workspace_scan_discover(payload, job)

    assert _fanned_out(st, scan_id) == []
    assert _files_total(st, scan_id) == 0
    assert len(st.list_scan_jobs_of_type(scan_id, "scan_finalize")) == 1


# ── resume: the property that makes this a checkpoint rather than a restart ───────────────────

def test_a_reclaimed_discover_enqueues_only_what_is_missing(st):
    """The whole reason enumeration lives in the worker. A fan-out interrupted part-way is
    re-run from the top by reclaim_stuck_jobs; without this it would enqueue the entire
    population a second time — the first half twice, and `files` describing neither."""
    for i in range(5):
        _doc(st, f"d{i}", path=f"f{i}.docx")
    import handlers
    scan_id, payload, job = _run(st)

    # First attempt dies after enqueueing two of the five.
    real_enqueue = st.enqueue_job
    calls = {"n": 0}

    def flaky(job_type, payload_=None, **kw):
        if job_type == "workspace_scan_file":
            calls["n"] += 1
            if calls["n"] > 2:
                raise RuntimeError("worker died mid-fan-out")
        return real_enqueue(job_type, payload_, **kw)

    st.enqueue_job = flaky
    with pytest.raises(RuntimeError):
        handlers._workspace_scan_discover(payload, job)
    st.enqueue_job = real_enqueue
    assert len(_fanned_out(st, scan_id)) == 2

    # The reclaim re-runs the handler. It must finish the job, not redo it.
    handlers._workspace_scan_discover(payload, job)
    out = _fanned_out(st, scan_id)
    assert len(out) == 5, "the second attempt duplicated work instead of resuming"
    assert len({p["version_id"] for p in out}) == 5


def test_a_document_uploaded_after_the_request_is_still_picked_up(st):
    """The population is re-derived at claim time, not frozen into the route's payload. A file
    that lands between pressing Assess and a worker picking the job up belongs to the run."""
    _doc(st, "d1", path="first.docx")
    import handlers
    scan_id, payload, job = _run(st)
    _doc(st, "d2", path="arrived-later.docx")

    handlers._workspace_scan_discover(payload, job)
    assert {p["version_id"] for p in _fanned_out(st, scan_id)} == {"d1-v1", "d2-v1"}
    assert _files_total(st, scan_id) == 2


def test_a_job_that_already_ran_is_not_re_enqueued(st):
    """Status is deliberately not filtered when reading what is already enqueued: a done job's
    results are already counted, and a dead-lettered one was given up on deliberately."""
    _doc(st, "d1", path="a.docx")
    _doc(st, "d2", path="b.docx")
    import handlers
    scan_id, payload, job = _run(st)
    handlers._workspace_scan_discover(payload, job)
    for j in st.list_scan_jobs_of_type(scan_id, "workspace_scan_file"):
        with st._db.cursor() as cur:
            st._db.execute(cur, "UPDATE jobs SET status=%s WHERE id=%s", ("done", j["id"]))

    handlers._workspace_scan_discover(payload, job)
    assert len(_fanned_out(st, scan_id)) == 2
