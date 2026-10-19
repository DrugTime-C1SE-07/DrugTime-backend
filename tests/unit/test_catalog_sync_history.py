from datetime import UTC, datetime

from drugtime.modules.catalog.adapters.inbound.http import router
from drugtime.modules.catalog.adapters.inbound.schemas import CatalogSyncRunList
from drugtime.modules.catalog.application.list_sync_runs import list_sync_runs
from drugtime.modules.catalog.domain.sync_run import (
    CatalogSyncRun,
    CatalogSyncRunPage,
    CatalogSyncSource,
    CatalogSyncStatus,
    CatalogSyncTrigger,
)


class FakeReader:
    def __init__(self, page):
        self.page = page
        self.arguments = None

    def list_runs(self, _uow, **kwargs):
        self.arguments = kwargs
        return self.page


def test_history_use_case_forwards_filters_and_pagination():
    page = CatalogSyncRunPage(items=[], total=0, limit=10, offset=20)
    reader = FakeReader(page)

    result = list_sync_runs(
        object(),
        reader,
        source=CatalogSyncSource.DAV_DRUGBANK,
        status=CatalogSyncStatus.FAILED,
        limit=10,
        offset=20,
    )

    assert result is page
    assert reader.arguments == {
        "source": CatalogSyncSource.DAV_DRUGBANK,
        "status": CatalogSyncStatus.FAILED,
        "limit": 10,
        "offset": 20,
    }


def test_history_response_matches_contract_shape():
    run = CatalogSyncRun(
        id=1,
        source=CatalogSyncSource.DAV_DRUGBANK,
        started_at=datetime(2026, 10, 8, tzinfo=UTC),
        finished_at=datetime(2026, 10, 8, 0, 1, tzinfo=UTC),
        status=CatalogSyncStatus.SUCCEEDED,
        records_inserted=2,
        records_updated=1,
        records_failed=0,
        error_details=None,
        triggered_by=CatalogSyncTrigger.SCHEDULER,
    )

    value = CatalogSyncRunList.from_domain(
        CatalogSyncRunPage(items=[run], total=1, limit=20, offset=0)
    ).model_dump(mode="json")

    assert set(value) == {"items", "total", "limit", "offset"}
    assert set(value["items"][0]) == {
        "id",
        "source",
        "started_at",
        "finished_at",
        "status",
        "records_inserted",
        "records_updated",
        "records_failed",
        "error_details",
        "triggered_by",
    }


def test_admin_history_route_uses_admin_dependency_and_query_bounds():
    route = next(route for route in router.routes if route.path == "/admin/catalog/sync-runs")
    dependencies = {dependency.call.__name__ for dependency in route.dependant.dependencies}
    params = {parameter.name: parameter for parameter in route.dependant.query_params}

    assert route.methods == {"GET"}
    assert "require_admin" in dependencies
    assert params["limit"].field_info.metadata[0].ge == 1
    assert params["limit"].field_info.metadata[1].le == 100
    assert params["offset"].field_info.metadata[0].ge == 0
