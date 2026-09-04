"""The workspace RBAC route gate does not exist yet, and this test says so out loud.

WHY THIS EXISTS. `frontend/src/access.js` carries a header explaining that hiding a tab is
presentation only, because the route gate that would enforce a capability is slice 4 and has not
been built. That header used to claim the opposite — "every route enforces its own capability
server-side" — which described the intended design and not the tree it was committed to. A
comment is exactly the wrong place to keep a fact like that: it reads as current forever, and the
direction it is wrong in is the reassuring one.

So the fact is asserted here instead. WHEN SLICE 4 LANDS, THIS TEST FAILS, and that failure is
the reminder to rewrite the access.js header and delete this file — not a regression. The same
shape as the unmounted-component guards (`discoverUploadRemoved.test.jsx`, `scopeStep.test.js`):
record a deliberate absence so it cannot be mistaken for the presence of a control.

This asserts NOTHING about whether deferring the gate to slice 4 is the right plan. It asserts
only that the code and the comment agree about where the plan currently stands.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "api"
ROUTES = API / "routes"
ACCESS_JS = ROOT / "frontend" / "src" / "access.js"

SLICE_4_LANDED = (
    "\n\nThis is how slice 4 arriving looks. Rewrite the header in frontend/src/access.js — it "
    "still tells the reader the route gate does not exist — and delete this test."
)


def test_workspace_forbidden_is_declared_and_never_raised():
    """`WorkspaceForbidden` is the gate's refusal. Nothing raises it today."""
    raisers = []
    for path in sorted(API.rglob("*.py")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\braise\s+\w*WorkspaceForbidden", line):
                raisers.append(f"{path.relative_to(ROOT)}:{i}")
    assert not raisers, f"WorkspaceForbidden is now raised at {raisers}." + SLICE_4_LANDED


def test_the_refusal_class_still_exists_to_be_looked_for():
    """The bite check for the test above.

    If `WorkspaceForbidden` were renamed or deleted, the assertion that nothing raises it would
    pass for the wrong reason and keep passing after a differently-named gate shipped.
    """
    source = (API / "workspace_rbac.py").read_text()
    assert "class WorkspaceForbidden" in source, (
        "WorkspaceForbidden is gone from api/workspace_rbac.py, so the 'never raised' assertion "
        "above no longer means anything. Point both at whatever replaced it." + SLICE_4_LANDED)


def test_no_route_module_calls_a_capability_check():
    """The gate would live in the route modules. None of them consults a capability.

    `routes/__init__.py` (the router import list), the roles admin API, and the two modules that
    REPORT access in a payload are expected to name these modules; a data route doing so means
    enforcement has started.
    """
    expected = {"__init__.py", "workspace_roles_admin.py", "system.py", "workspace.py"}
    referencing = {
        path.name for path in sorted(ROUTES.glob("*.py"))
        if re.search(r"workspace_rbac|workspace_roles", path.read_text())
    }
    assert referencing == expected, (
        f"route modules naming workspace RBAC changed: "
        f"added {sorted(referencing - expected)}, removed {sorted(expected - referencing)}."
        + SLICE_4_LANDED)


def test_the_app_installs_no_rbac_middleware():
    """A global dependency or middleware would enforce without touching any route module."""
    source = (API / "app.py").read_text()
    assert not re.search(r"workspace_rbac|workspace_roles", source), (
        "api/app.py now references workspace RBAC, which is where a global gate would go."
        + SLICE_4_LANDED)


def test_the_access_js_header_says_slice_4():
    """The comment and the code above must not drift apart in either direction.

    The second assertion is a TRIPWIRE ON ONE PHRASING, not a proof: it catches the exact
    sentence that was wrong before, and a reworded version of the same false claim would slip
    past it. The real guard is the four tests above, which read the code. This one exists because
    the header is what a reader trusts instead of reading the code, and it deliberately does not
    quote the old sentence verbatim — a check a comment can satisfy by quoting it is no check.
    """
    header = ACCESS_JS.read_text()[:4000]
    lowered = header.lower()
    assert "slice 4" in lowered, (
        "frontend/src/access.js no longer tells the reader the route gate is slice 4 and unbuilt. "
        "If the gate shipped, delete this test; if the comment was merely reworded, restore the "
        "claim — it is the only warning a reader gets.")
    # Case-folded: a re-introduction that merely starts a sentence ("Every route enforces...")
    # is the same false claim, and a case-sensitive check would wave it through. Found by the
    # bite check for this assertion, which is the only reason it was noticed.
    assert "route enforces its own capability server-side" not in lowered, (
        "the old, false claim is back in the access.js header. No route enforces a capability "
        "today — see the other tests in this file.")
