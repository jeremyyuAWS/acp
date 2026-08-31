"""Shared test config.

Point run_scan("local") at the frozen oracle corpus (test-corpus/oracle/) instead
of test-corpus/files/ — the demo estate in files/ changes with the demo's needs
(it became the 100-file legal corpus in f442a08, silently breaking every filename
the scan regression suite asserts on), while oracle/ is the fixed set of synthetic
rule-trigger documents the assertions were written against. Regenerate them with
scripts/generate_test_corpus.py.
"""
import os
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
