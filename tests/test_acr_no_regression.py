"""PRD §21.18 — no existing ACP workflow regresses because the ACR workspace exists.

The ACR feature is additive by construction: new tables, new modules, one new router. This file
pins the four ways "additive" could quietly stop being true, each of which would surface far from
its cause.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import core  # noqa: E402
import store as store_mod  # noqa: E402

ACR_TABLES = {"acr_report", "acr_criterion", "acr_evidence", "acr_manual_test",
              "acr_decision_log", "acr_snapshot", "acr_role"}


def test_the_acr_router_did_not_displace_any_existing_route():
    """Route count only goes up. A path collision would shadow an existing endpoint silently —
    FastAPI dispatches the first match and reports nothing."""
    from app import app
    paths = {r.path for r in core.enumerate_api_routes(app)}
    acr = {p for p in paths if p == "/acr" or p.startswith("/acr/")}
    assert len(acr) == 11, sorted(acr)

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
    """No ALTER, no DROP, no rename of an existing table. A migration that modified an existing
    table would break a replica still running the previous image (ADR 0045)."""
    schema = [s for s in store_mod._SCHEMA if isinstance(s, str)]
    acr_statements = [s for s in schema if "acr_" in s]
    assert acr_statements, "the ACR schema is missing entirely"
    for stmt in acr_statements:
        head = stmt.strip().upper()
        assert head.startswith("CREATE TABLE IF NOT EXISTS") or \
               head.startswith("CREATE INDEX IF NOT EXISTS"), stmt[:90]
        assert "DROP " not in head, stmt[:90]


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
