"""Notification registry complements PEP behavioral tests, never replaces them."""

from fastapi.routing import APIRoute

from drugtime.modules.adherence.adapters.inbound import http

REGISTRY = {
    ("GET", "/notifications"): "listMyNotifications",
    ("GET", "/notifications/{id}"): "getMyNotification",
    ("PATCH", "/notifications/{id}"): "updateNotificationStatus",
}


def dependencies(node):
    yield node
    for child in node.dependencies:
        yield from dependencies(child)


def test_notification_routes_use_guarded_function_transaction():
    actual = {}
    for route in http.notification_router.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/notifications"):
            continue
        assert isinstance(route, http.NotificationRoute)
        for method in route.methods:
            key = method, route.path
            assert route.operation_id == REGISTRY[key]
            deps = list(dependencies(route.dependant))
            assert {http.notification_user, http.get_notification_uow} <= {d.call for d in deps}
            assert all(d.scope == "function" for d in deps if d.call is http.get_notification_uow)
            actual[key] = route.operation_id
    assert actual == REGISTRY
