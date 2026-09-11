"""Per-assessment execution scope. Context-local: concurrent files cannot share choices.

None retains legacy unrestricted callers. An empty set deliberately runs no WCAG checks.
Shared parsing/metadata work is permitted; criterion detectors are gated before invocation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps, lru_cache
import json
from pathlib import Path
import re

_codes = ContextVar("assessment_criteria", default=None)

def enabled(sc):
    codes = _codes.get()
    return codes is None or sc in codes

def selected():
    return _codes.get()

def selected_for_file(scope, filename):
    if not scope:
        return None
    from assessment_policy import _file_format
    fmt = _file_format(filename)
    # HTML has no format-axis checkbox; it still respects the chosen criteria.
    return frozenset(sc for sc, fmts in scope.items()
                     if fmts and (fmt in (None, "html") or fmt in fmts))

@contextmanager
def selection(codes):
    token = _codes.set(None if codes is None else frozenset(codes))
    try:
        yield
    finally:
        _codes.reset(token)

def criteria(*scs):
    """Skip a detector entirely when none of its declared criteria were selected."""
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            if not any(enabled(sc) for sc in scs):
                return []
            return fn(*args, **kwargs)
        return run
    return decorate

@lru_cache(maxsize=1)
def catalog():
    data = json.loads((Path(__file__).resolve().parents[1] / "config/rule-catalog.json").read_text())
    return {r["id"]: r["wcag_sc"] for rows in data.values() if isinstance(rows, list) for r in rows}

def allowed_rules():
    if selected() is None:
        return None
    return [rid for rid, sc in catalog().items() if enabled(sc)]

def filter_findings(issues):
    if selected() is None:
        return list(issues)
    def sc(issue):
        match = re.search(r"(?:SC_)?(\d+)[._](\d+)[._](\d+)", str(issue.get("wcag", "")))
        return ".".join(match.groups()) if match else catalog().get(issue.get("ruleId"))
    return [i for i in issues if enabled(sc(i))]
