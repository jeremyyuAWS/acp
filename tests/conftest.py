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
