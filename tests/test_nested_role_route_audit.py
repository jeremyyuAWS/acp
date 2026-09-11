"""Lazy included-router endpoints must be audited and gated at their final path."""
from fastapi import APIRouter, FastAPI
from starlette.routing import Match
import core
import workspace_capability_map as capmap


def nested_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    child = APIRouter()
    @child.get('/secret/{item}')
    def secret(item: str): return {'item': item}
    parent = APIRouter()
    parent.include_router(child, prefix='/nested')
    app.include_router(parent, prefix='/outer')
    return app


def test_lazy_nested_unmapped_route_is_not_silently_skipped():
    app = nested_app()
    assert capmap.unmapped_routes(app.routes) == [('GET', '/outer/nested/secret/{item}')]


def test_capability_gate_resolves_effective_nested_path(monkeypatch):
    routes = core.enumerate_api_routes(nested_app())
    assert len(routes) == 1 and routes[0].path == '/outer/nested/secret/{item}'
    monkeypatch.setattr(core, '_PROTECTED_ROUTES', routes)
    route = core.match_registered_route('/outer/nested/secret/one', 'GET')
    assert route is not None and route.path == '/outer/nested/secret/{item}'
    assert core.match_registered_route('/secret/one', 'GET') is None
    monkeypatch.setitem(capmap.ROUTE_CAPABILITIES, ('GET', route.path), frozenset({'roles.manage'}))
    assert capmap.unmapped_routes(nested_app().routes) == []
    assert not capmap.allows('GET', route.path, {'remediate.view'})
    assert capmap.allows('GET', route.path, {'roles.manage'})


def test_flat_routes_remain_auditable():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    @app.get('/fresh')
    def fresh(): return {}
    assert capmap.unmapped_routes(app.routes) == [('GET', '/fresh')]


def test_accepted_plan_is_a_view_only_permission():
    path = '/scans/{sid}/remediation/accepted-plan/{run_id}'
    assert capmap.required_capabilities('GET', path) == frozenset({'remediate.view'})


def test_normalized_route_descriptors_are_audited_alongside_nested_routers():
    from types import SimpleNamespace
    routes = [*nested_app().routes, SimpleNamespace(path='/normalized/new', methods={'POST'})]
    assert capmap.unmapped_routes(routes) == [
        ('GET', '/outer/nested/secret/{item}'), ('POST', '/normalized/new')]
