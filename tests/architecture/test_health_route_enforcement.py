"""Registry CI của health route mới; test hành vi PEP nằm ở unit/integration.

Metadata không cấp quyền: registry bắt route khai báo cả identity và scope/audit,
còn test use case/HTTP kiểm thứ tự PEP, fail-closed và audit commit trước response.
"""

import pytest
from fastapi import routing
from fastapi.security import HTTPBearer

from drugtime.main import create_app
from drugtime.modules.identity import api as identity

PROTECTED_HEALTH_ROUTES = {
    ("GET", "/adherence"): ("lich_su_tuan_thu", "getAdherenceHistory"),
}


def dependencies(node):
    yield node.call
    for child in node.dependencies:
        yield from dependencies(child)


def api_routes(app):
    # New FastAPI keeps include_router branches deferred. Its public iterator
    # yields effective contexts; older versions expose flattened APIRoutes.
    iterator = getattr(routing, "iter_route_contexts", iter)
    return [route for route in iterator(app.routes) if hasattr(route, "dependant")]


@pytest.mark.parametrize("method,path", PROTECTED_HEALTH_ROUTES)
def test_adherence_health_route_registered_with_bearer_identity_and_scope(method, path):
    app = create_app()
    matches = [r for r in api_routes(app) if r.path == path and method in r.methods]
    assert len(matches) == 1
    route = matches[0]
    scope, operation = PROTECTED_HEALTH_ROUTES[(method, path)]
    assert route.openapi_extra["x-health-scope"] == scope
    assert route.openapi_extra["x-health-audit-self"] is True
    calls = list(dependencies(route.dependant))
    assert identity.current_user in calls
    assert any(isinstance(call, HTTPBearer) and call.scheme_name == "bearerAuth" for call in calls)
    op = app.openapi()["paths"][path][method.lower()]
    assert op["operationId"] == operation and op["security"] == [{"bearerAuth": []}]


def test_scoped_health_routes_have_registry_entries():
    app = create_app()
    declared = {
        (method, route.path)
        for route in api_routes(app)
        if (route.openapi_extra or {}).get("x-health-scope")
        for method in route.methods
    }
    assert declared == set(PROTECTED_HEALTH_ROUTES)
