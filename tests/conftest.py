"""Shared test config.

Point run_scan("local") at the frozen oracle corpus (test-corpus/oracle/) instead
of test-corpus/files/ — the demo estate in files/ changes with the demo's needs
(it became the 100-file legal corpus in f442a08, silently breaking every filename
the scan regression suite asserts on), while oracle/ is the fixed set of synthetic
rule-trigger documents the assertions were written against. Regenerate them with
scripts/generate_test_corpus.py.
"""
import os
import time
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
os.environ.setdefault("ACP_LOCAL_CORPUS", str(ACP / "test-corpus/oracle"))
sys.path.insert(0, str(ACP / "api"))

# store._SQLITE_PATH defaults to <repo>/acp.db and there is no env var for it, so anything
# that constructs Store() outside a fixture opens the developer's real database. Two do:
# api/core.py builds `store = Store()` at import, and test modules that `import core` at
# module level trigger that during collection, before any fixture can run. Repoint the module
# default once, here, because conftest is imported before every test module — a per-test
# monkeypatch.setattr then restores to THIS temp path rather than to the real acp.db.
# Session-scoped and deliberately never restored.
import store as _store_mod  # noqa: E402 — must follow the sys.path.insert above

# ── every mkdtemp in the suite lands somewhere that gets cleaned up ───────────
#
# THE LEAK. 139 call sites across ~60 test modules build fixtures with a bare
# `tempfile.mkdtemp()`, which has no cleanup at all — the directory and the .docx/.pptx/
# .xlsx/.pdf inside it survive the process. Two proof modules alone leak 57 directories per
# run. Across eight full-suite runs on 2026-08-31 this reached 30 GB and exhausted the
# session's disk, at which point writes fail while deletes still succeed, so the suite starts
# reporting errors that look like code faults and are not.
#
# WHY THIS AND NOT `tmp_path`. `tmp_path` is the right tool and would need 139 signature
# changes across modules owned by other work in flight — a large diff whose merge conflicts
# would cost more than the leak. Redirecting `tempfile.tempdir` fixes every call site at once,
# including any added later, and needs no test to know about it. The trade is that cleanup is
# per-RUN rather than per-test, which is the granularity that actually matters: within a run
# the suite peaks a few hundred MB, and it was accumulation ACROSS runs that filled the disk.
#
# This runs at conftest import — before any test module is imported — because the fixtures are
# built at module scope in several files, so a fixture-scoped hook would be too late for them.
#
# CONCURRENCY IS THE WHOLE DIFFICULTY, and getting it wrong is worse than the leak. CI runs
# `pytest -n auto --dist loadfile`, so one shard is several worker PROCESSES. The first attempt
# here gave each process its own `run-<pid>` directory and kept "the 3 most recent", which meant
# the fourth worker to start deleted the first worker's directory while it was still using it:
#
#     FileNotFoundError: '/tmp/acp-pytest/run-2923-kdzgs4b2/tmp0ufceig1'
#
# 418 errors across all four shards. It passed locally because pytest-xdist is not installed
# there, so the local run was single-process and could not express the bug at all.
#
# Two rules keep it safe:
#   * ONE directory per pytest SESSION, not per process. The first process to arrive publishes
#     it in the environment and xdist workers inherit that, so siblings share rather than
#     compete for a retention slot.
#   * Prune only a directory whose OWNING PROCESS IS DEAD — the pid is in the name and
#     `os.kill(pid, 0)` asks the kernel. A live sibling, or a whole other session on the same
#     machine, is never a deletion candidate however many there are. Age is only a backstop
#     against pid reuse, never the primary test.
#
# Never a blanket wipe of the system temp directory: other processes keep real state there, and
# deleting it is what destroyed this environment's commit-signing helper.
_TMP_KEEP_DEAD = 2          # finished runs kept so a failure can still be inspected
_TMP_MAX_AGE_S = 24 * 3600  # backstop for a dead run whose pid has since been reused
_TMP_ROOT = Path(tempfile.gettempdir()) / "acp-pytest"


def _acp_pid_alive(pid: int) -> bool:
    """Is this process still running? Anything ambiguous answers True — the cost of keeping a
    stale directory is disk, and the cost of deleting a live one is a suite-wide failure."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _acp_claim_tmpdir() -> None:
    inherited = os.environ.get("ACP_PYTEST_TMP")
    if inherited and os.path.isdir(inherited):
        tempfile.tempdir = inherited      # an xdist worker: share the session's directory
        return
    _TMP_ROOT.mkdir(exist_ok=True)
    now, finished = time.time(), []
    for d in _TMP_ROOT.iterdir():
        m = re.match(r"run-(\d+)-", d.name)
        if not (m and d.is_dir()):
            continue
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        if _acp_pid_alive(int(m.group(1))) and (now - mtime) < _TMP_MAX_AGE_S:
            continue                      # a live run — never a candidate
        finished.append((mtime, d))
    for _, d in sorted(finished, reverse=True)[_TMP_KEEP_DEAD:]:
        shutil.rmtree(d, ignore_errors=True)
    claimed = tempfile.mkdtemp(prefix=f"run-{os.getpid()}-", dir=_TMP_ROOT)
    os.environ["ACP_PYTEST_TMP"] = claimed   # xdist workers inherit this
    tempfile.tempdir = claimed


try:
    _acp_claim_tmpdir()
except OSError:
    # A read-only or full temp dir must not stop the suite from running; the leak is a
    # housekeeping problem, not a correctness one.
    pass



_store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "acp-session.db"

_REAL_DB = (ACP / "acp.db").resolve()


def _forbid_opening_the_real_db(store_mod):
    """Turn any Store() opened against <repo>/acp.db into an immediate hard failure.

    The default above already keeps every Store on a temp file, but it is one assignment away
    from regressing: the old unrestored `store_mod._SQLITE_PATH = ...` in each fixture was what
    accidentally protected the real database, and restoring that attribute properly re-armed
    the module default. Checksumming acp.db does NOT catch this — Store.__init__ runs
    init_schema(), which opens the file for write and emits DDL without changing a byte, so a
    regression stays invisible until something finally writes. Assert on the open itself.

    _SQLiteAdapter is the single seam: store.py builds exactly one, from _SQLITE_PATH.
    """
    original = store_mod._SQLiteAdapter.__init__

    def __init__(self, path, *args, **kwargs):
        if Path(path).resolve() == _REAL_DB:
            raise RuntimeError(
                f"a test opened the real database at {_REAL_DB}. Point store._SQLITE_PATH at a "
                f"temp file (monkeypatch.setattr, as the isolated_store fixture does) — never "
                f"let a Store() fall through to the module default."
            )
        return original(self, path, *args, **kwargs)

    store_mod._SQLiteAdapter.__init__ = __init__


_forbid_opening_the_real_db(_store_mod)


@pytest.fixture(autouse=True)
def _fresh_shadow_log_dedupe(monkeypatch):
    """Give every test its own store._shadow_logged.

    It is a process-global set that get_scan() writes to, to log "hiding N shadowing file(s)"
    once per scan rather than once per dashboard poll. Nothing resets it, so a test that trips
    the shadow filter leaves its scan id behind and a later test reusing that id — 's1' is the
    house style — silently never sees the line it asserts on. Resetting it in the one test that
    noticed is not enough: the write happens in the code under test, not in the test.
    """
    monkeypatch.setattr(_store_mod, "_shadow_logged", set())


@pytest.fixture()
def isolated_store(monkeypatch):
    """A Store backed by its own temp SQLite file, isolated from the other tests' stores.

    Never reload the store module to achieve this: reload swaps the module object out from
    under anything that did `from store import ...`.
    """
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    return store_mod.Store()


def held(store, job_id: str) -> dict:
    """The claim currently on the row, as the ownership kwargs the outcome writers require:
    `store.fail_job(jid, "boom", force_dead=True, **held(store, jid))`.

    complete_job / mark_job_cancelled / fail_job require (worker_id, attempt) so a stale claim
    cannot publish an outcome over the replacement that took its job over — see
    store.complete_job and tests/test_outcome_claim_ownership.py. Most tests that call those
    methods are not about that guard at all (they are about error_class persistence, dead-file
    accounting, retry policy), and spelling the claim out in each would be noise.

    DELIBERATELY ALWAYS SATISFIES THE GUARD, because it reads the row rather than remembering
    what a caller claimed earlier. That is what makes it right for "as whoever holds this now"
    and WRONG for anything testing the guard itself: a zombie-writer test built on this would
    pass no matter what the predicate said. Those tests pass the identity literally — see
    test_outcome_claim_ownership.py and test_job_completion_race.py, neither of which uses this.
    """
    job = store.get_job(job_id)
    # A job nobody holds cannot have an outcome published for it, so the writers would refuse the
    # call and return 'stale'. Silently: the row simply does not move, and a test asserting on
    # something else entirely goes green having exercised nothing. Caught exactly that way — the
    # ownership kwargs were added to test_job_phase's fail_job mechanically, the job there was
    # never claimed, and the test passed on claim_job clearing the phase instead of on the retry
    # it names. Assert rather than return None, so the next one is loud.
    assert job is not None, f"held(): no such job {job_id}"
    assert job["status"] == "running" and job["locked_by"], (
        f"held(): job {job_id} is {job['status']!r} and held by {job['locked_by']!r} — nothing "
        "can publish an outcome for it, so this call would be refused and the test would pass "
        "without exercising the path it names. Claim the job first.")
    return {"worker_id": job["locked_by"], "attempt": job["attempts"]}


def pdf_engine_available() -> bool:
    """Is the partner PDF engine importable?

    api/remediate_pdf.py hard-imports `remediation.fixers.pdf.*` from the vendored
    worker-python tree, which scanner.WP locates via $ACP_PDF_ENGINE (defaulting to a path
    under the developer's home directory). That tree is a SEPARATE repository: it is present
    on a developer box and in the deployed image, but never on a clean CI agent — where
    remediate_pdf() raises ModuleNotFoundError and every test that drives it hard-fails.

    Tests that call remediate_pdf() therefore gate on this, exactly as ocr.is_available() and
    textchecks._langdetect_available() gate their optional dependencies. Point
    $ACP_PDF_ENGINE at a worker-python checkout to actually run them.
    """
    try:
        from scanner import WP
    except Exception:
        return False
    return (Path(WP) / "remediation" / "fixers" / "pdf" / "language_fixer.py").is_file()


# Skip (never fail) when the partner engine isn't there. A skip says "not exercised here";
# a red suite on every clean checkout says nothing at all, and trains people to ignore CI.
requires_pdf_engine = pytest.mark.skipif(
    not pdf_engine_available(),
    reason="partner PDF engine not available — set ACP_PDF_ENGINE to a worker-python checkout",
)


# ── the Office analyser, for the remediation-verified lane proofs ─────────────
#
# WHY THIS EXISTS. Since verification fails closed (api/proposals.py `verify_residual`), a
# scan grades `analysed` — and may therefore grant credit — only when every engine actually
# ran. Office analysis shells out to the .NET CLI, so on a host without it EVERY Office scan
# grades `error`, and every Office remediation lane correctly withholds credit.
#
# That is the intended production behaviour (tests/test_verification_engine_missing.py asserts
# it deliberately). But it makes the 17 lane proofs untestable on a developer box: they exist
# to prove that an approved value is WRITTEN, RE-SCANNED and CREDITED, and without an analyser
# they can only ever prove the withholding. Before the fail-closed change they passed here by
# accident — the residual was read off `issues` while the failed status was discarded, which
# is the very defect being fixed.
#
# So: when the real analyser is present (CI, and any box with the SDK) this does NOTHING and
# the proofs run against the real engine. Only when it is absent does it stand in, with a run
# that SUCCEEDED and found nothing of its own — the first-party detectors still supply every
# finding the proofs assert on, so the only thing this changes is whether the scan is graded
# trustworthy. It is scoped to the proof modules by name; nothing else in the suite sees it,
# and in particular the engine-missing tests keep observing the real (absent) engine.
@pytest.fixture(autouse=True)
def _office_analyser_for_lane_proofs(request, monkeypatch):
    module = getattr(request.node, "module", None)
    name = getattr(module, "__name__", "") or ""
    if not name.startswith("test_remediation_verified_"):
        return
    import engines
    if engines.OFFICE_OK:
        return                      # the real CLI is here — use it, stand in for nothing
    import scanner

    def _stand_in(dest):
        return {p.name: {"succeeded": True, "errors": [], "issues": []}
                for p in Path(dest).iterdir()}

    monkeypatch.setattr(scanner, "_analyse_office", _stand_in)
