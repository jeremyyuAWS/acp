"""End-to-end deferred Discover->Assess over REAL local sample files (ADR 0020).

Unlike test_deferred_assess.py (which mocks _list and checks the enqueue), this drives the WHOLE
pipeline against real documents: discover writes inventory only, Assess fans out, the worker jobs
run the real analysers, and the scan finalizes with scored file_records + assessed_at. This is the
regression guard for the "Assess 0 files" class of bug — if discover ever scores files, or assess
ever fails to finalize, this fails. Office/HTML samples only (no external PDF engine dependency),
but it does need the built .NET Office CLI, so it self-skips when that is absent.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

from conftest import held

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

# Two of the three samples are Office formats, and the assertion below is that ALL of them
# score. Without the built .NET CLI the docx/xlsx come back scored None and this fails with
# "only 1/3 scored" — a real-looking regression whose actual cause is an unbuilt engine. The
# rest of the Office-dependent suite already self-skips on this gate; this module hard-failed
# instead, so a fresh clone read as one broken test rather than as an unbuilt engine.
# Office only, not PDF: the sample set is deliberately docx/html/xlsx (see the module
# docstring), so PDF_OK is not required here.
from engines import NO_OFFICE, OFFICE_OK  # noqa: E402

pytestmark = pytest.mark.skipif(not OFFICE_OK, reason=NO_OFFICE)

_SAMPLES = Path(__file__).resolve().parent.parent / "frontend" / "public" / "samples"
# What lands in the corpus. The .html sample is copied in DELIBERATELY and is expected never to
# be scanned: since the 2026-08-31 scope decision (PDF/DOCX/XLSX/PPTX — api/scan_formats) it is
# out of scope, and a corpus containing one proves the boundary holds end to end rather than
# assuming it. Removing it would make this test pass for the wrong reason.
_CORPUS = ["benefits-policy.docx", "careers-landing.html", "finance-metrics.xlsx"]
# What discovery may list, and therefore what Assess must score.
_WANT = ["benefits-policy.docx", "finance-metrics.xlsx"]
_OUT_OF_SCOPE = ["careers-landing.html"]


def _run_queue(core):
    from worker import HANDLERS
    for _ in range(500):
        j = core.store.claim_job("w-test")
        if not j:
            return
        pl = j.get("payload") or {}
        if isinstance(pl, str):
            pl = json.loads(pl or "{}")
        try:
            HANDLERS[j["type"]](pl, j)
        finally:
            try:
                core.store.complete_job(j["id"], **held(core.store, j["id"]))
            except Exception:
                pass


def test_deferred_discover_then_assess_scores_real_files(isolated_store, monkeypatch, tmp_path):
    missing = [s for s in _CORPUS if not (_SAMPLES / s).exists()]
    if missing:
        pytest.skip(f"sample docs not present: {missing}")

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for s in _CORPUS:
        shutil.copy(_SAMPLES / s, corpus / s)

    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setenv("ACP_LOCAL_CORPUS", str(corpus))
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    import handlers

    sid = "e2e-local"
    # 1. DISCOVER — inventory only, no scores, no analysis jobs.
    handlers._scan_discover({"scan_id": sid, "source": "local", "user": None}, {"scan_id": sid})
    run = isolated_store.get_scan(sid)["run"]
    files0 = isolated_store.get_scan(sid)["files"]
    assert run["status"] == "discovered"
    assert len(files0) == len(_WANT) and all(f["status"] == "discovered" and f["score"] is None for f in files0)
    # The out-of-scope sample is in the corpus but must never reach the scan. Asserted at
    # DISCOVER, not only at the end: a format that is listed here and dropped later is the
    # failure mode CI caught on #1120 — the file is queued, never analysed, and its record sits
    # scoreless forever, which reads as a broken analyser rather than as a scope decision.
    assert not any(f["file"] in _OUT_OF_SCOPE for f in files0), (
        f"an out-of-scope format was listed for scanning: {[f['file'] for f in files0]}")
    assert not any(j["type"] in ("scan_file", "scan_batch") for j in isolated_store.list_jobs(status="queued"))

    # 2. ASSESS — kick off the fan-out and drain the queue.
    handlers._scan_assess({"scan_id": sid, "user": None}, {"scan_id": sid})
    assert isolated_store.get_scan(sid)["run"]["status"] == "running"
    _run_queue(core)

    # 3. RESULT — every file scored, scan finalized + marked assessed (the deferred contract).
    res = isolated_store.get_scan(sid)
    run = res["run"]
    assert run["status"] == "done"
    assert run.get("finalized_at") and run.get("assessed_at")
    scored = [f for f in res["files"] if f["score"] is not None]
    assert len(scored) == len(_WANT), f"only {len(scored)}/{len(_WANT)} scored: {[(f['file'], f['score']) for f in res['files']]}"
    # real analysis produced real findings (these sample docs are deliberately non-conformant)
    assert sum(len(f.get("issues") or []) for f in res["files"]) > 0
