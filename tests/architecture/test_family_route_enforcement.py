"""All link-management routes must have an explicit enforcement classification.

This structural check complements behavioral ownership/consent/audit tests.
"""

from fastapi.routing import APIRoute

from drugtime.modules.family.adapters.inbound import http

REGISTRY = {
    ("GET", "/family/links"): ("listPendingFamilyLinks", "metadata_owner_audit"),
    ("POST", "/family/links/{link_id}/approve"): ("approveFamilyLink", "owner_consent_audit"),
    ("POST", "/family/links/{link_id}/reject"): ("rejectFamilyLink", "metadata_owner_audit"),
    ("GET", "/family/caregivers"): ("listMyCaregivers", "metadata_owner_audit"),
    ("PATCH", "/family/links/{link_id}/sharing"): (
        "updateFamilyLinkSharing",
        "owner_consent_audit",
    ),
    ("POST", "/family/links/{link_id}/revoke"): ("revokeFamilyLink", "metadata_owner_audit"),
}
MANAGED_PREFIXES = ("/family/links", "/family/caregivers")


def dependencies(node):
    yield node
    for child in node.dependencies:
        yield from dependencies(child)


def test_every_family_links_route_is_classified_and_enforced():
    actual = {}
    for route in http.router.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(MANAGED_PREFIXES):
            continue
        for method in route.methods:
            key = (method, route.path)
            assert key in REGISTRY, f"Unclassified family link route: {key}"
            assert route.operation_id == REGISTRY[key][0]
            deps = list(dependencies(route.dependant))
            calls = {dep.call for dep in deps}
            assert {http.link_user, http.get_link_uow, http.validate_link_input} <= calls
            guarded = [d for d in deps if d.call is http.get_link_uow]
            assert guarded and all(d.scope == "function" for d in guarded)
            actual[key] = route.operation_id
    assert set(actual) == set(REGISTRY)
