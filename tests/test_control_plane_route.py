"""The control-plane route must take its tenant from the REQUEST, never from a parameter.

Source-level, and that is the right level for this one: what can go wrong is a query parameter
appearing where the tenant is read, and that is visible in the signature and invisible in any
single-tenant fixture. A test that round-tripped one tenant's data would pass whether or not the
isolation holds.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "api" / "routes" / "control.py").read_text()
INIT = (ROOT / "api" / "routes" / "__init__.py").read_text()


def _code() -> str:
    """The module without its docstrings — these explain the very rule the tests assert, so a
    naive search matches the prose. Same trap already hit twice in this repo."""
    out = re.sub(r'"""(?:.|\n)*?"""', "", SRC)
    return out


def test_the_router_is_registered():
    """A router nobody mounts is a 404 that reads as a missing feature."""
    assert "control" in INIT
    assert "control.router" in INIT


def test_the_tenant_comes_from_the_request():
    code = _code()
    assert "def _owner(request: Request)" in code
    assert 'getattr(request.state, "user_email", None)' in code


def test_no_endpoint_accepts_a_tenant_parameter():
    """`?owner_email=` would be a tenant selector any caller could set — not a filter, but the
    absence of isolation wearing a filter's clothes."""
    code = _code()
    for sig in re.findall(r"def \w+\(([^)]*)\)", code):
        assert "owner_email" not in sig, f"an endpoint takes a tenant parameter: {sig}"
        assert "tenant" not in sig, f"an endpoint takes a tenant parameter: {sig}"


def test_the_store_is_called_with_the_request_owner():
    """Both aggregates, scoped by the same value — one scoped and one not would leak through the
    unscoped half while looking correct in the UI."""
    code = _code()
    assert re.search(r"estate_by_department\(\s*who\b", code), "department query not scoped to `who`"
    assert re.search(r"estate_owners\(\s*who\b", code), "owner query not scoped to `who`"


def test_dept_and_owner_are_narrowing_filters_only():
    """They must reach the store as filters, not as the tenant."""
    code = _code()
    assert "department=dept or None" in code
    assert "owner=owner or None" in code


def test_the_response_states_what_it_counted():
    """Every surface in this product that shows a total is expected to say what the total counts
    (ScopeBanner, #164), and a JSON response is read by the same people. `filtered` separates
    "your estate is empty" from "your filter matched nothing" — two very different facts that
    look identical as a zero."""
    code = _code()
    assert '"tenant": who' in code
    assert '"filters"' in code
    assert '"filtered"' in code
