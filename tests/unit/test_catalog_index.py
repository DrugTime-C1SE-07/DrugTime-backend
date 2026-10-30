"""Internal candidate retrieval contracts; SQL execution is tested in integration."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from drugtime.modules.catalog import api
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.application.lookup_ocr_candidates import lookup_ocr_candidates
from drugtime.modules.catalog.domain.catalog_index import (
    CatalogHit,
    CatalogQueryResult,
    MatchKind,
    OcrCatalogLookup,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication


def med(id_=1, name="Thuốc Đỏ", strength="500MG", form=None):
    return CatalogMedication(id_, name, strength, form, True, "Hoạt Chất Đỏ")


class Reader:
    def __init__(self, hits=()):
        self.hits = hits
        self.calls = []

    def find_ocr_matches(self, uow, query_key, kind, *, limit=200):
        self.calls.append((uow, query_key, kind, limit))
        return CatalogQueryResult(self.hits)


def test_candidate_mapping_and_all_sources_preserve_raw_ids_nulls():
    original, other = med(), med(2, strength=None, form="Viên Nén")

    class Sources(Reader):
        def find_ocr_matches(self, uow, query_key, kind, *, limit=200):
            if kind == MatchKind.INGREDIENT_ALIAS:
                return CatalogQueryResult((CatalogHit(original, 17, "Bí Danh Đỏ", 8),))
            return CatalogQueryResult((CatalogHit(original), CatalogHit(other)))

    normalized = api.normalize_ocr_text("Thuốc Đỏ 500mg\nTHUỐC ĐỎ 500mg")
    result = lookup_ocr_candidates(object(), normalized, Sources())
    assert result.normalized is normalized
    candidates = result.clusters[0].candidates
    assert [c.medication.id for c in candidates] == [1, 2]
    assert candidates[0].medication is original
    assert candidates[1].medication is other
    assert len(candidates[0].sources) == 3
    alias = candidates[0].sources[-1]
    assert (alias.alias_id, alias.alias_text, alias.active_ingredient_id) == (17, "Bí Danh Đỏ", 8)
    assert alias.line_ids == (1, 2) and alias.query_key == "thuoc do"
    assert alias.cluster_id == normalized.clusters[0].cluster_id
    assert not hasattr(result, "selected_id") and not hasattr(result, "confidence")
    with pytest.raises(FrozenInstanceError):
        candidates[0].medication.id = 9


@pytest.mark.parametrize("text", ["", "\n", "hop 10 vi", "5mg", "B12", "Met.", "SDK: VD-1234-56"])
def test_ineligible_no_read(text):
    reader = Reader()
    result = lookup_ocr_candidates(object(), api.normalize_ocr_text(text), reader)
    assert reader.calls == []
    assert not any(g.candidates for g in result.clusters)
    assert result.coverage == ()


def test_independent_cluster_queries_and_deduplication():
    normalized = api.normalize_ocr_text(
        "Metformin 500mg\nMetformin 500mg\nMetformin 850mg\nMetformim 500mg\nAspirin"
    )
    reader = Reader((CatalogHit(med()),))
    result = lookup_ocr_candidates(object(), normalized, reader)
    assert [query for _, query, kind, _ in reader.calls if kind == MatchKind.NAME] == [
        "metformin",
        "metformim",
        "aspirin",
    ]
    assert [c.count for c in normalized.clusters] == [3, 1, 1]
    assert len(result.clusters) == 3
    first, second = result.clusters[:2]
    assert first.candidates[0].sources[0].line_ids == (1, 2)
    assert second.candidates[0].sources[0].line_ids == (3,)


def test_truncation_is_per_query_and_source_and_keeps_small_cluster():
    class Budget(Reader):
        def find_ocr_matches(self, uow, query_key, kind, *, limit=200):
            if query_key == "metformin" and kind == MatchKind.NAME:
                return CatalogQueryResult(tuple(CatalogHit(med(i)) for i in range(1, 201)), True)
            return CatalogQueryResult((CatalogHit(med(300)),))

    result = lookup_ocr_candidates(object(), api.normalize_ocr_text("Metformin\nAspirin"), Budget())
    assert len(result.clusters[0].candidates) == 201  # 200 name IDs + another-source ID.
    assert len(result.clusters[1].candidates) == 1
    assert sum(c.truncated for c in result.coverage) == 1


def test_two_facade_callers_fresh_uow_no_snapshot(monkeypatch):
    reader = Reader((CatalogHit(med()),))
    monkeypatch.setattr(api, "SqlCatalog", lambda: reader)
    normalized = api.normalize_ocr_text("Thuốc Đỏ 500mg")

    def caller_413(uow):
        return api.lookup_ocr_candidates(uow, normalized)

    def caller_415(uow):
        return api.lookup_ocr_candidates(uow, normalized)

    a, b = object(), object()
    first = caller_413(a)
    reader.hits = (CatalogHit(med(2)),)
    second = caller_415(b)
    assert isinstance(first, OcrCatalogLookup) and isinstance(second, OcrCatalogLookup)
    assert first.clusters[0].candidates[0].medication.id == 1
    assert second.clusters[0].candidates[0].medication.id == 2
    assert [call[0] for call in reader.calls] == [a] * 3 + [b] * 3


@pytest.mark.parametrize("failure_kind", list(MatchKind))
def test_any_branch_error_propagates_without_partial_or_fallback(failure_kind):
    class Failing(Reader):
        def find_ocr_matches(self, uow, query_key, kind, *, limit=200):
            if kind == failure_kind:
                raise RuntimeError("synthetic read failure")
            return CatalogQueryResult((CatalogHit(med()),))

    with pytest.raises(RuntimeError, match="synthetic read failure"):
        lookup_ocr_candidates(object(), api.normalize_ocr_text("Metformin"), Failing())


def row(id_, alias_id=1):
    return SimpleNamespace(
        id=id_,
        name="Thuốc Đỏ",
        raw_active_ingredient=None,
        strength_text=None,
        dosage_form="Viên Nén",
        has_active_ingredients=True,
        alias_id=alias_id,
        alias_text="Bí Danh",
        active_ingredient_id=9,
    )


class Connection:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return iter(self.rows)


@pytest.mark.parametrize("count", [60, 199, 200, 201])
@pytest.mark.parametrize("kind", list(MatchKind))
def test_sql_distinct_id_budget_all_alias_hits_and_bound_literal(count, kind):
    rows = [
        row(i, alias_id=a)
        for i in range(1, count + 1)
        for a in ([1, 2, 3] if kind == MatchKind.INGREDIENT_ALIAS else [1])
    ]
    connection = Connection(rows)
    result = SqlCatalog().find_ocr_matches(
        SimpleNamespace(connection=connection), "thuoc_%\\", kind
    )
    ids = {h.medication.id for h in result.hits}
    assert len(ids) == min(count, 200)
    assert result.truncated is (count > 200)
    assert len(result.hits) == min(count, 200) * (3 if kind == MatchKind.INGREDIENT_ALIAS else 1)
    assert result.hits[0].medication.active_ingredient is None
    sql, params = connection.calls[0]
    assert "thuoc" not in sql
    assert params == {"pattern": "%thuoc\\_\\%\\\\%", "probe": 201}
    assert "deleted_at IS NULL" in sql and "ESCAPE" in sql
    assert sql.lstrip().startswith(("SELECT", "WITH"))
    if kind == MatchKind.INGREDIENT_ALIAS:
        assert "SELECT DISTINCT id" in sql
        assert "mai.active_ingredient_id = a.active_ingredient_id" in sql
        assert "catalog_search_key(a.alias_text)" in sql
    else:
        column = "m.name" if kind == MatchKind.NAME else "m.raw_active_ingredient"
        assert f"catalog_search_key({column})" in sql


def test_sql_iterator_error_is_not_swallowed():
    def broken():
        yield row(1)
        raise RuntimeError("synthetic iterator failure")

    with pytest.raises(RuntimeError, match="iterator failure"):
        SqlCatalog().find_ocr_matches(
            SimpleNamespace(connection=Connection(broken())), "name", MatchKind.NAME
        )


def test_no_read_for_empty_key_and_invalid_limit():
    connection = Connection([])
    uow = SimpleNamespace(connection=connection)
    assert SqlCatalog().find_ocr_matches(uow, "", MatchKind.NAME).hits == ()
    assert connection.calls == []
    with pytest.raises(ValueError):
        SqlCatalog().find_ocr_matches(uow, "name", MatchKind.NAME, limit=0)


def test_lookup_never_calls_writers_or_catalog_builder(monkeypatch, caplog, capsys):
    def reject(*args, **kwargs):
        raise AssertionError("Unexpected write")

    for method in ("create", "update", "soft_delete", "list_active", "search"):
        monkeypatch.setattr(SqlCatalog, method, reject)
    reader = Reader((CatalogHit(med()),))
    monkeypatch.setattr(api, "SqlCatalog", lambda: reader)
    api.lookup_ocr_candidates(object(), api.normalize_ocr_text("synthetic-private-marker"))
    assert not hasattr(api, "build_catalog_index")
    assert not hasattr(api, "load_catalog_index")
    assert not hasattr(SqlCatalog, "list_for_index")
    assert "synthetic-private-marker" not in caplog.text + capsys.readouterr().out
