"""A test double that cannot be called the way production calls the real thing.

WHAT THIS CAUGHT, and why it is not hypothetical. `store.touch_job` gained a required claim
(`worker_id`, `attempt`) in #1075 (fb26d66a) so a superseded worker could no longer renew a
lease it had lost. Every production caller was updated. `_FakeStore.touch_job(self, job_id)` in
tests/test_drive_token_expiry.py was not, and stayed that way until #1080 (db1dacd6) — and
NOTHING went red in between, because the worker wraps its heartbeat in try/except
(api/worker.py:345):

    try:
        self.store.touch_job(job["id"], worker_id=self.worker_id, attempt=job.get("attempts"))
    except Exception:
        pass

so the TypeError was raised and swallowed on every single heartbeat of every test using that
double. The tests passed. They were exercising a worker whose heartbeat had silently stopped
working, which is the precise condition #1075 existed to make impossible.

That is the shape this guards: a double drifting out of step with the real object, in a code
path defensive enough that the drift never surfaces. A blanket `except Exception` around a store
call is not rare here — `handlers._enqueue_proposals` has one too — and each one is a place where
this class of mistake is invisible by construction.

THE RULE, and why it is exactly this one. Only the REQUIRED parameters of the real method are
checked:

  - Required positional  -> the double must accept at least that many positionally (or *args).
  - Required keyword-only -> the double must have that exact name (or **kwargs), since a caller
                             has no other way to pass it.

Optional parameters are deliberately NOT checked, and the earlier draft that did check them was
wrong in a way worth recording. It flagged `live_queue.for_scan`'s double for defining
`get_scan(self, sid)` against a real `get_scan(self, sid, owner=None)` — but `for_scan` calls
`store.get_scan(scan_id)` with one argument, so the double is correct and the guard was not.
Whether a given caller passes an optional argument is a fact about the CALL SITE, which no
signature comparison can see. Checking only the required set is the largest rule that cannot be
wrong: a double missing one of those can never be called correctly by anybody.

It follows that a green run here is not proof every double is faithful — only that none is
impossible to call. That is the claim, and it is the one that was false.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import store as store_mod  # noqa: E402

REAL = store_mod.Store


def _double_shape(fn: ast.FunctionDef) -> dict:
    """What the double can accept: positional slots, every parameter name, *args, **kwargs."""
    a = fn.args
    positional = [p.arg for p in a.posonlyargs + a.args]
    if positional and positional[0] == "self":
        positional = positional[1:]
    return {
        "positional": positional,
        "names": set(positional) | {p.arg for p in a.kwonlyargs},
        "star": a.vararg is not None,
        "kwargs": a.kwarg is not None,
    }


def _real_requirements(sig: inspect.Signature) -> tuple[list[str], list[str]]:
    """(required positional, required keyword-only) of a real Store method."""
    pos, kw = [], []
    for name, p in sig.parameters.items():
        if name == "self" or p.default is not p.empty:
            continue
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            pos.append(name)
        elif p.kind is p.KEYWORD_ONLY:
            kw.append(name)
    return pos, kw


def _store_doubles():
    """Every class in tests/ whose name ends in 'Store' (allowing a trailing digit: _FakeStore2).

    Named by convention rather than by registration on purpose — a new double gets covered by
    calling it what everyone already calls it, with nothing to remember."""
    for path in sorted((ROOT / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:                              # not this guard's job to report
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.rstrip("0123456789").endswith("Store"):
                yield path, node


def _mismatches(cls: ast.ClassDef) -> list[str]:
    out = []
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name.startswith("__"):                     # a double's own constructor is its own
            continue
        real = getattr(REAL, fn.name, None)
        if real is None or not callable(real):           # a helper the real Store does not have
            continue
        try:
            sig = inspect.signature(real)
        except (ValueError, TypeError):                  # pragma: no cover — builtins/slots
            continue
        need_pos, need_kw = _real_requirements(sig)
        d = _double_shape(fn)

        if not d["star"] and len(d["positional"]) < len(need_pos):
            out.append(f"{fn.name}: takes {len(d['positional'])} positional argument(s), but "
                       f"Store.{fn.name}{sig} REQUIRES {len(need_pos)} — {need_pos}")
        if not d["kwargs"]:
            missing = [k for k in need_kw if k not in d["names"]]
            if missing:
                out.append(f"{fn.name}: cannot accept required keyword-only argument(s) "
                           f"{missing} — Store.{fn.name}{sig}")
    return out


DOUBLES = list(_store_doubles())


def test_there_are_doubles_to_check():
    """Without this, a change to the discovery convention turns the guard below into a loop over
    an empty list — which reports as a pass. The count is a floor, not a fixture: it is here to
    catch zero, not to be updated whenever somebody adds a double."""
    assert len(DOUBLES) >= 15, (
        f"only {len(DOUBLES)} store doubles found — the naming convention this guard discovers "
        "them by has probably changed, and it is now checking almost nothing")


@pytest.mark.parametrize("path,cls", DOUBLES, ids=lambda x: getattr(x, "name", None) or x)
def test_a_store_double_can_be_called_the_way_the_real_store_is(path, cls):
    problems = _mismatches(cls)
    assert not problems, (
        f"{path.name}::{cls.name} has drifted from the real Store:\n  "
        + "\n  ".join(problems)
        + "\n\nProduction cannot call these the way it calls Store. If the caller wraps the call "
          "in try/except (worker.py's heartbeat and handlers._enqueue_proposals both do), the "
          "TypeError is swallowed and the test passes while exercising nothing.")
