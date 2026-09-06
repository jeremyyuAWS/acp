"""PRD §21.18 — no existing ACP workflow regresses because the ACR workspace exists.

The ACR feature is additive by construction: new tables, new modules, one new router. This file
pins the four ways "additive" could quietly stop being true, each of which would surface far from
its cause.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import core  # noqa: E402
import store as store_mod  # noqa: E402

ACR_TABLES = {"acr_report", "acr_criterion", "acr_evidence", "acr_manual_test",
              "acr_decision_log", "acr_snapshot", "acr_role"}


# The ACR routes Phase 1 established. Later phases ADD to this; none of them may disappear,
# because a route that silently stops being dispatched takes a workflow with it.
PHASE1_ACR_PATHS = {
    "/acr",
    "/acr/{report_id}",
    "/acr/{report_id}/audit",
    "/acr/{report_id}/criteria",
    "/acr/{report_id}/criteria/{criterion_num}",
    "/acr/{report_id}/criteria/{criterion_num}/approve",
    "/acr/{report_id}/criteria/{criterion_num}/decision",
    "/acr/{report_id}/criteria/{criterion_num}/evidence",
    "/acr/{report_id}/preview",
    "/acr/{report_id}/roles",
    "/acr/{report_id}/validation",
}


def test_the_acr_router_did_not_displace_any_existing_route():
    """Route count only goes up, and no earlier route disappears.

    This asserted an EXACT count (== 11) when Phase 1 wrote it, which contradicted its own
    docstring and broke the moment Phase 2 added three endpoints — an exact count tests "nothing
    changed", not "nothing was lost". A named floor tests the property the docstring claims: the
    Phase 1 surface is still there, whatever later phases add. The collision half of the concern
    is its own test below.
    """
    from app import app
    paths = {r.path for r in core.enumerate_api_routes(app)}
    acr = {p for p in paths if p == "/acr" or p.startswith("/acr/")}

    missing = PHASE1_ACR_PATHS - acr
    assert not missing, f"ACR routes disappeared: {sorted(missing)}"
    assert len(acr) >= len(PHASE1_ACR_PATHS), sorted(acr)

    # Every pre-existing route group is still dispatchable.
    for expected in ("/healthz", "/config", "/scans", "/rubric", "/hitl/queue",
                     "/content-workspaces"):
        assert any(p == expected or p.startswith(expected) for p in paths), expected


def test_no_acr_path_shadows_another_router():
    """`/acr` is a new top-level prefix. If any other router already owned a path under it, one of
    the two would become unreachable depending on include order."""
    from app import app
    import routes

    acr_paths = {r.path for r in routes.acr.router.routes}
    for router in routes.ROUTERS:
        if router is routes.acr.router:
            continue
        for route in router.routes:
            assert getattr(route, "path", "") not in acr_paths, route.path


def test_every_acr_route_is_behind_the_auth_gate():
    """The gate is fail-closed against the real route table, so this should hold automatically —
    which is exactly why it is worth asserting: an accidental ALWAYS_PUBLIC entry is the one way
    it would not."""
    from app import app
    for route in core.enumerate_api_routes(app):
        if route.path == "/acr" or route.path.startswith("/acr/"):
            assert not core.is_public(route.path), route.path


def test_the_acr_schema_is_purely_additive():
    """Only statements ADR 0045 calls Class A — the ones safe to run in an automatic deploy.

    This test used to reject every ALTER, on the reasoning that "a migration that modified an
    existing table would break a replica still running the previous image". That is true of a
    DROP, a rename, or a retype, and NOT true of an added column: an older replica selecting *
    receives a key it ignores, and its INSERTs name their columns explicitly, so the new one takes
    its default. ADR 0045 says so in as many words — its Class A table reads "`ADD COLUMN`
    nullable (PG11+ with a non-volatile default too)", and its expand/contract rule licenses
    exactly this shape: "add the new column/table/index, nullable and unused".

    So the ban narrows to what the ADR actually forbids in an unattended deploy, and the rest of
    the file's guards are unchanged. What stays banned is the whole of Class C (retypes, SET NOT
    NULL on a populated column, DROP COLUMN) and any DROP at all — a contract is a later,
    deliberate deploy, never this one.

    Phase 6 is why this came up: `requirement_set` and `chapter` on acr_criterion, both nullable,
    one with a constant default, added so a 508 requirement row cannot be mistaken for a WCAG one.
    """
    schema = [s for s in store_mod._SCHEMA if isinstance(s, str)]
    acr_statements = [s for s in schema if "acr_" in s]
    assert acr_statements, "the ACR schema is missing entirely"
    for stmt in acr_statements:
        assert _is_class_a(stmt), stmt[:90]


def _is_class_a(stmt: str) -> bool:
    """ADR 0045's Class A: safe to run unattended, brief lock or none, no rewrite."""
    head = f" {stmt.strip().upper()} "
    additive = (head.lstrip().startswith("CREATE TABLE IF NOT EXISTS")
                or head.lstrip().startswith("CREATE INDEX IF NOT EXISTS")
                or (head.lstrip().startswith("ALTER TABLE")
                    and "ADD COLUMN IF NOT EXISTS" in head))
    if not additive or "DROP " in head:
        return False
    # Class C: a rewrite behind an innocuous-looking ALTER.
    return not any(b in head for b in (" ALTER COLUMN ", " RENAME ", " SET NOT NULL", " TYPE "))


@pytest.mark.parametrize("stmt,allowed", [
    ("CREATE TABLE IF NOT EXISTS acr_report (id TEXT)", True),
    ("CREATE INDEX IF NOT EXISTS idx_acr ON acr_report(id)", True),
    ("ALTER TABLE acr_criterion ADD COLUMN IF NOT EXISTS requirement_set TEXT "
     "DEFAULT 'wcag-2.2-aa'", True),
    ("ALTER TABLE acr_criterion DROP COLUMN requirement_set", False),
    ("ALTER TABLE acr_criterion RENAME COLUMN chapter TO section", False),
    ("ALTER TABLE acr_criterion ALTER COLUMN chapter TYPE INT", False),
    ("ALTER TABLE acr_criterion ALTER COLUMN chapter SET NOT NULL", False),
    ("DROP TABLE acr_criterion", False),
    ("ALTER TABLE acr_criterion ADD COLUMN chapter TEXT", False),  # no IF NOT EXISTS: replay dies
    # The one shape the Class C ban exists for, and the only one that reaches it: Postgres allows
    # several actions in one ALTER, so a rewrite can ride along behind a legitimate add. Every
    # other rewrite is already rejected for not being an ADD COLUMN at all — which a bite check
    # established by deleting the ban and finding nothing turned red.
    ("ALTER TABLE acr_criterion ADD COLUMN IF NOT EXISTS a TEXT, "
     "ALTER COLUMN chapter TYPE INT", False),
])
def test_the_class_a_predicate_admits_and_rejects_the_right_statements(stmt, allowed):
    """The sweep above can only fail on a statement somebody wrote. This is what proves the
    predicate would catch one — written after a bite check found that deleting the Class C ban
    turned nothing red, because `_SCHEMA` rightly contains no rewrite to catch.
    """
    assert _is_class_a(stmt) is allowed


def test_the_acr_tables_do_not_join_to_scan_data():
    """The line docs/conformance-report.md draws in prose, enforced in the schema.

    An ACR is about ACP'S OWN WEB UI; scan_runs/issue_records are about a CUSTOMER'S FILES. A
    foreign key between them would make it natural — and eventually inevitable — for a finding
    about someone's Word document to become evidence for a conformance claim about ACP, which is
    the unsupported compliance claim PRD §3 opens by naming.
    """
    schema = [s for s in store_mod._SCHEMA if isinstance(s, str)]
    for stmt in schema:
        if "CREATE TABLE IF NOT EXISTS acr_" not in stmt:
            continue
        body = stmt.upper()
        for forbidden in ("SCAN_ID", "FILE_RECORDS", "ISSUE_RECORDS", "REFERENCES"):
            assert forbidden not in body, f"{forbidden} appears in an ACR table: {stmt[:120]}"


def test_existing_reset_behaviour_is_unchanged_for_pre_existing_tables():
    """Adding seven names to _ANALYTICS_TABLES must not have removed or reordered any."""
    tables = store_mod.Store._ANALYTICS_TABLES
    assert len(tables) == len(set(tables)), "a table is listed twice"
    for expected in ("scan_runs", "file_records", "issue_records", "decision_log",
                     "content_workspaces", "overview_snapshots", "worker_instances"):
        assert expected in tables, expected
    assert ACR_TABLES <= set(tables)


def test_the_acr_modules_do_not_import_the_scan_engine():
    """Import-level proof of the same separation. acr_* must stay loadable with no scanner,
    no analyser and no engine present — and must not reach into them by accident."""
    import ast

    for name in ("acr_catalog", "acr_model", "acr_rules", "acr_freshness", "acr_validation",
                 "acr_authz", "acr_export_preview"):
        source = (ACP / "api" / f"{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        forbidden = imported & {"scanner", "handlers", "remediate", "remediate_office",
                                "remediate_pdf", "store", "core"}
        assert not forbidden, f"{name} imports {sorted(forbidden)}"


def test_the_rule_modules_stay_free_of_io():
    """acr_rules and acr_freshness are pure functions over records. That is what lets them be
    tested against constructed evidence with no database — and what stops a rule quietly
    depending on a stored `is_stale` column instead of deriving it."""
    import acr_freshness
    import acr_rules

    for module in (acr_rules, acr_freshness):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("core.store", "cursor(", "SELECT ", "INSERT "):
            assert forbidden not in source, f"{module.__name__} contains {forbidden!r}"
