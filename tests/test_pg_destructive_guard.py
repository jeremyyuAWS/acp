"""No test may destroy a PostgreSQL database it has not PROVEN is disposable.

THE GAP THIS WAS WRITTEN TO DEMONSTRATE. Two tests issue destructive statements against whatever
`DATABASE_URL` happens to name, gated on nothing but `skipif(not DATABASE_URL)`:

    tests/test_pg_job_queue.py      TRUNCATE TABLE <every base table in public> ... CASCADE
    tests/test_schema_boot_locks.py DROP TABLE IF EXISTS acp_schema_version

Run `pytest tests/` on a machine whose DATABASE_URL points at a real database and the first wipes
it and the second forces a full re-migration. Nothing asks whether that database is a throwaway.
Nothing asks the operator to say so. The CI job happens to point at a disposable container, so the
suite has always been green while the hazard sat one environment variable away.

This file is the guard. Its assertions run WITHOUT a Postgres server — they are about a URL, an
environment flag and the shape of the test suite — so the protection is not itself confined to the
one CI job that has a database, which is the trap the original hazard was hiding in.

conftest._forbid_opening_the_real_db already does exactly this for SQLite: it turns a Store opened
against the real acp.db into a hard failure. Postgres had no equivalent.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

TESTS = Path(__file__).resolve().parent

# The exact DSN the Postgres integration job uses — a service container created for the job and
# destroyed with it. It must keep qualifying, or this guard has broken CI rather than protected it.
CI_DSN = "postgresql://postgres:acp-ci-throwaway@localhost:5432/acp_ci"

# Statements that cannot be undone. Matched against the SQL a test hands to a live connection.
_DESTRUCTIVE = ("TRUNCATE", "DROP TABLE", "DROP DATABASE", "DROP SCHEMA")


def _guard():
    from conftest import require_disposable_postgres
    return require_disposable_postgres


# ── the structural half: every destructive site is guarded ────────────────────────────────────

def _sql_literal(node) -> str | None:
    """The SQL text of an execute() argument — a plain string, or the literal parts of an
    f-string (`f"TRUNCATE TABLE {names} CASCADE"` is a JoinedStr, and the dangerous word is in
    its literal half)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _destructive_sites() -> list[tuple[str, int, str]]:
    """Every destructive SQL statement tests/ actually HANDS TO a cursor, with the function
    issuing it.

    Only the first argument of an `.execute(...)` call counts. An earlier version of this matched
    any string constant containing "TRUNCATE" and reported 70 sites — because this repo's tests
    talk about truncated LISTINGS constantly ("a truncated estate is marked a floor"), and a test
    NAME is not a database operation. A guard that cries wolf 70 times is one somebody deletes.

    So the question asked here is the operational one: what SQL reaches a live connection?"""
    out = []
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", None))
                if name not in ("execute", "executemany"):
                    continue
                for arg in node.args:
                    sql = (_sql_literal(arg) or "").upper()
                    if any(d in sql for d in _DESTRUCTIVE):
                        out.append((path.name, node.lineno, fn.name))
    return out


def _calls_the_guard(path: Path, func_name: str) -> bool:
    """Whether the named function calls require_disposable_postgres before anything else."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == func_name:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    name = (node.func.attr if isinstance(node.func, ast.Attribute)
                            else getattr(node.func, "id", None))
                    if name == "require_disposable_postgres":
                        return True
    return False


def test_every_destructive_statement_is_guarded():
    """THE REGRESSION FIXTURE. Fails on the tree as it was before this change: two destructive
    statements, neither preceded by any proof that the target is disposable.

    Structural rather than behavioural on purpose. A behavioural test can only observe the sites
    that a given run happens to reach, and both of these are skipped without a DATABASE_URL — so
    the check that matters most would be the one that never runs on a developer's machine. This
    one runs everywhere, and a THIRD destructive site added later fails it on the commit that adds
    it, rather than the day someone points DATABASE_URL somewhere real."""
    sites = _destructive_sites()
    assert sites, "found no destructive SQL in tests/ — this guard has stopped guarding"
    unguarded = [(f, ln, fn) for f, ln, fn in sites
                 if not _calls_the_guard(TESTS / f, fn)]
    assert not unguarded, (
        "destructive SQL with no disposability check: "
        + "; ".join(f"{f}:{ln} in {fn}()" for f, ln, fn in unguarded)
        + ". Call conftest.require_disposable_postgres(DATABASE_URL) first — it refuses any "
          "target that is not provably a throwaway.")


# ── the behavioural half: what the guard accepts and refuses ──────────────────────────────────

def test_the_ci_dsn_with_the_flag_is_accepted(monkeypatch):
    """The one target that must keep working. If this fails the guard has broken the Postgres
    integration job, which is a worse outcome than the hazard it was written for."""
    monkeypatch.setenv("ACP_PG_TEST_DESTRUCTIVE", "1")
    _guard()(CI_DSN)                                   # must not raise


# Read from the workflow TEXT, not a parsed tree. PyYAML was in neither api/requirements.txt nor
# tests/requirements.txt when this was written, so `import yaml` passed on a dev machine that
# happened to have it and raised ModuleNotFoundError on CI — which is exactly how this test first
# went red. It is declared now, but the two `env:` blocks below are a flat mapping a regex states
# directly, so this stays text and keeps working under a partial install.
#
# What is NOT an option here is the pytest.importorskip("yaml") the alert-workflow guard reached
# for: in this job that is a test which silently never runs, and silent non-running is the failure
# mode this whole file exists to refuse.
_JOB_RE = re.compile(r"^  ([A-Za-z_][\w-]*):\s*$")
_ENV_RE = re.compile(r"^(\s*)env:\s*$")
_ENV_KV_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*):\s*(\S.*?)\s*$")


def _postgres_job_lines() -> list[str]:
    """The lines of `jobs.postgres`, bounded by the next job at the same indent."""
    lines = (TESTS.parent / ".github/workflows/ci.yml").read_text().splitlines()
    out, inside = [], False
    for line in lines:
        m = _JOB_RE.match(line)
        if m:
            inside = m.group(1) == "postgres"
            continue
        if inside:
            out.append(line)
    return out


def _ci_postgres_env() -> list[dict]:
    """The env blocks of the steps in the Postgres integration job, read from the workflow."""
    lines = _postgres_job_lines()
    envs = []
    for i, line in enumerate(lines):
        m = _ENV_RE.match(line)
        if not m:
            continue
        indent, block = len(m.group(1)), {}
        for nxt in lines[i + 1:]:
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                continue
            if len(nxt) - len(nxt.lstrip()) <= indent:      # dedent ends the mapping
                break
            kv = _ENV_KV_RE.match(nxt)
            if kv:
                block[kv.group(1)] = kv.group(2).strip("\'\"")
        if "DATABASE_URL" in block:
            envs.append(block)
    return envs


def test_the_ci_job_points_at_a_database_this_guard_would_accept(monkeypatch):
    """Ties the workflow to the rule, in the direction that actually protects someone.

    The guard refuses a target it cannot prove disposable — but only at RUN time, on whatever
    DATABASE_URL is set. Nothing stopped the workflow itself being repointed at a shared or
    long-lived server, which would either break the job (best case) or, if that server's name
    happened to end _test, quietly start truncating something people were using.

    So: every step in the Postgres job that sets DATABASE_URL must set the destructive opt-in too,
    and its DSN must independently satisfy the guard. Read from ci.yml rather than pinned here, so
    changing the workflow is what fails this — not a literal someone forgot to update."""
    envs = _ci_postgres_env()
    assert envs, "found no DATABASE_URL step in the postgres job — has the job been renamed?"
    monkeypatch.setenv("ACP_PG_TEST_DESTRUCTIVE", "1")
    for env in envs:
        assert env.get("ACP_PG_TEST_DESTRUCTIVE") == "1", (
            "a step in the Postgres job sets DATABASE_URL but not the destructive opt-in — the "
            "guarded fixtures will refuse and the job will fail")
        _guard()(env["DATABASE_URL"])                  # the DSN itself must qualify


@pytest.mark.parametrize("url,why", [
    ("postgresql://acp:pw@acp-prod.postgres.database.azure.com:5432/acp", "a remote production host"),
    ("postgresql://postgres:pw@10.0.0.7:5432/acp_ci", "a disposable NAME on a remote host"),
    ("postgresql://postgres:pw@localhost:5432/acp", "loopback, but the real database name"),
    ("postgresql://postgres:pw@localhost:5432/acp_prod", "loopback, but a production name"),
    ("postgresql://postgres:pw@localhost:5432/", "no database named at all"),
])
def test_the_guard_refuses_anything_not_provably_disposable(monkeypatch, url, why):
    monkeypatch.setenv("ACP_PG_TEST_DESTRUCTIVE", "1")
    with pytest.raises(RuntimeError) as e:
        _guard()(url)
    assert "disposable" in str(e.value).lower() or "destructive" in str(e.value).lower(), why


def test_the_opt_in_is_required_even_for_a_perfect_target(monkeypatch):
    """DATABASE_URL being set is not consent. The operator says so explicitly, or nothing is
    destroyed — that is the whole difference between this and what was there before."""
    monkeypatch.delenv("ACP_PG_TEST_DESTRUCTIVE", raising=False)
    with pytest.raises(RuntimeError) as e:
        _guard()(CI_DSN)
    assert "ACP_PG_TEST_DESTRUCTIVE" in str(e.value)


def test_the_refusal_names_what_to_set(monkeypatch):
    """A guard that refuses without saying why gets disabled by the next person who hits it."""
    monkeypatch.setenv("ACP_PG_TEST_DESTRUCTIVE", "1")
    with pytest.raises(RuntimeError) as e:
        _guard()("postgresql://postgres:pw@db.example.com:5432/acp")
    msg = str(e.value)
    assert "db.example.com" in msg and "acp" in msg          # names the target it refused
    assert "loopback" in msg.lower() or "local" in msg.lower()


def test_the_guard_refuses_rather_than_skipping(monkeypatch):
    """It must RAISE. A skip is how a dangerous configuration stays unnoticed — and the Postgres
    job's own anti-skip step would turn a skip into a red run there anyway, so a skip is both
    less safe and no more convenient."""
    monkeypatch.delenv("ACP_PG_TEST_DESTRUCTIVE", raising=False)
    with pytest.raises(RuntimeError):
        _guard()(CI_DSN)
