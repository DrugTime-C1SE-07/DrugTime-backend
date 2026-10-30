"""OCR retrieval on local PostgreSQL as api_role. Fixtures use synthetic catalog data."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from drugtime.modules.catalog import api
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.domain.catalog_index import MatchKind
from drugtime.shared.db import SqlUnitOfWork, get_engine, unit_of_work


def lookup(raw):
    with unit_of_work() as uow:
        assert uow.connection.execute(text("SELECT current_user")).scalar_one() == "api_role"
        return api.lookup_ocr_candidates(uow, api.normalize_ocr_text(raw))


def entries(result):
    return {c.medication.id: c for g in result.clusters for c in g.candidates}


def link(db, mid, aid):
    db.execute(
        text(
            "INSERT INTO medication_active_ingredients "
            "(medication_id, active_ingredient_id, strength_value, strength_unit, dosing_unit) "
            "VALUES (:m, :a, 5, 'mg', 'vien')"
        ),
        {"m": mid, "a": aid},
    )


def capture(connection):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", record)
    return statements, record


def test_sources_preserve_raw_nulls_ids_and_explicit_links__AC17_AC21(make, db):
    tag = "fixture" + uuid4().hex
    query, raw = f"thuoc do {tag}", f"THUỐC ĐỎ {tag}"
    mids = [
        make.catalog_medication(name=raw, with_ingredient=False, dosage_form=None) for _ in range(2)
    ]
    db.execute(text("UPDATE medications SET strength_text = NULL WHERE id = :i"), {"i": mids[0]})
    db.execute(
        text("UPDATE medications SET strength_text = '500 mg', dosage_form = 'Viên' WHERE id = :i"),
        {"i": mids[1]},
    )
    ingredient_mid = make.catalog_medication(active_ingredient=raw, with_ingredient=False)
    aid = make.ingredient(aliases=(raw, raw + " alias"))
    aliases = list(
        db.execute(
            text(
                "SELECT id, alias_text FROM ingredient_aliases "
                "WHERE active_ingredient_id = :a ORDER BY id"
            ),
            {"a": aid},
        )
    )
    for mid in [*mids, ingredient_mid]:
        link(db, mid, aid)
    alias_only = make.medication_with([aid])
    deleted = make.catalog_medication(name=raw, deleted=True)
    link(db, deleted, aid)
    make.ingredient(aliases=(raw + " unlinked",))
    found = entries(lookup(query))
    assert set(found) == {*mids, ingredient_mid, alias_only}
    assert found[mids[0]].medication == api.CatalogMedication(mids[0], raw, None, None, True, None)
    assert found[mids[1]].medication.strength_text == "500 mg"
    assert found[mids[1]].medication.dosage_form == "Viên"
    assert found[ingredient_mid].medication.active_ingredient == raw
    assert {s.kind for s in found[mids[0]].sources} == {MatchKind.NAME, MatchKind.INGREDIENT_ALIAS}
    assert {s.kind for s in found[ingredient_mid].sources} == {
        MatchKind.RAW_ACTIVE_INGREDIENT,
        MatchKind.INGREDIENT_ALIAS,
    }
    for candidate in found.values():
        sources = [s for s in candidate.sources if s.kind == MatchKind.INGREDIENT_ALIAS]
        assert [(s.alias_id, s.alias_text) for s in sources] == list(aliases)
        assert all(
            s.active_ingredient_id == aid
            and s.query_key == query
            and s.line_ids == (1,)
            and s.cluster_id == 1
            for s in sources
        )


@pytest.mark.parametrize("kind", list(MatchKind))
@pytest.mark.parametrize("literal", ["percent%", "under_score", r"back\slash", "quote' OR TRUE--"])
def test_literal_wildcards_and_sql_text_are_bound__AC17_AC21(make, db, kind, literal):
    key = "fixture" + uuid4().hex + literal.lower()
    aid = make.ingredient(aliases=(key,))
    mid = make.catalog_medication(name=key, active_ingredient=key, with_ingredient=False)
    link(db, mid, aid)
    if "%" in key or "_" in key:
        make.catalog_medication(name=key.replace("%", "X").replace("_", "X"), with_ingredient=False)
    with unit_of_work() as uow:
        result = SqlCatalog().find_ocr_matches(uow, key, kind)
    assert {h.medication.id for h in result.hits} == {mid}
    assert not result.truncated


@pytest.mark.parametrize("kind", list(MatchKind))
@pytest.mark.parametrize("size", [199, 200, 201])
def test_distinct_id_budget_retains_all_alias_sources__AC18(make, db, kind, size):
    tag = "budget" + uuid4().hex
    aid = make.ingredient(aliases=(tag + " first", tag + " second"))
    ids = list(
        db.execute(
            text(
                "INSERT INTO medications (name, raw_active_ingredient) "
                "SELECT :tag, :tag FROM generate_series(1, :n) RETURNING id"
            ),
            {"tag": tag, "n": size},
        ).scalars()
    )
    db.execute(
        text(
            "INSERT INTO medication_active_ingredients "
            "(medication_id, active_ingredient_id, strength_value, strength_unit, dosing_unit) "
            "SELECT id, :a, 5, 'mg', 'vien' FROM medications WHERE id = ANY(:ids)"
        ),
        {"a": aid, "ids": ids},
    )
    with unit_of_work() as uow:
        result = SqlCatalog().find_ocr_matches(uow, tag, kind)
    assert sorted({h.medication.id for h in result.hits}) == sorted(ids)[:200]
    assert result.truncated == (size == 201)
    assert len(result.hits) == min(size, 200) * (2 if kind == MatchKind.INGREDIENT_ALIAS else 1)


def test_large_small_clusters_query_dedup_preserves_sources__AC18(make):
    tag = "multicluster" + uuid4().hex
    first, second = tag + " alpha", tag + " omega"
    big = {make.catalog_medication(name=first, with_ingredient=False) for _ in range(60)}
    small = make.catalog_medication(name=second, with_ingredient=False)
    document = api.normalize_ocr_text(f"{first} 16mg\n{first} 16mg\n{first} 160mg\n{second}")
    with unit_of_work() as uow:
        statements, recorder = capture(uow.connection)
        try:
            result = api.lookup_ocr_candidates(uow, document)
        finally:
            event.remove(uow.connection, "before_cursor_execute", recorder)
    assert [g.cluster_id for g in result.clusters] == [c.cluster_id for c in document.clusters]
    assert [c.count for c in document.clusters] == [2, 1, 1]
    assert len(statements) == 6
    assert all(
        s.lstrip().upper().startswith(("SELECT", "WITH"))
        and "catalog_search_key" in s
        and p["probe"] == 201
        for s, p in statements
    )
    for group, cluster in zip(result.clusters, document.clusters, strict=True):
        assert {c.medication.id for c in group.candidates} == (
            big if cluster.name_key == first else {small}
        )
        assert all(
            s.line_ids == cluster.member_line_ids for c in group.candidates for s in c.sources
        )
    assert not any(c.truncated for c in result.coverage)


def test_ineligible_inputs_issue_no_catalog_read__AC15_AC21():
    with unit_of_work() as uow:
        statements, recorder = capture(uow.connection)
        try:
            for raw in ("", " \n", "SDK: VD-13882-11", "5mg", "Met."):
                result = api.lookup_ocr_candidates(uow, api.normalize_ocr_text(raw))
                assert not entries(result) and result.coverage == ()
        finally:
            event.remove(uow.connection, "before_cursor_execute", recorder)
    assert statements == []


def test_medication_commits_visible_and_old_result_immutable__AC19(make, db):
    tag = "freshness" + uuid4().hex
    mid = make.catalog_medication(name=tag, with_ingredient=False)
    original = lookup(tag)
    assert set(entries(original)) == {mid}
    with pytest.raises(FrozenInstanceError):
        original.clusters = ()
    added = make.catalog_medication(name=tag, with_ingredient=False)
    assert set(entries(lookup(tag))) == {mid, added}
    db.execute(
        text(
            "UPDATE medications SET name = :n, strength_text = '250 mg', "
            "dosage_form = 'Siro', raw_active_ingredient = 'Đồng' WHERE id = :i"
        ),
        {"n": tag + " changed", "i": mid},
    )
    changed = entries(lookup(tag))[mid].medication
    assert (
        changed.name,
        changed.strength_text,
        changed.dosage_form,
        changed.active_ingredient,
    ) == (tag + " changed", "250 mg", "Siro", "Đồng")
    db.execute(text("UPDATE medications SET deleted_at = now() WHERE id = :i"), {"i": mid})
    assert set(entries(lookup(tag))) == {added}
    db.execute(text("UPDATE medications SET deleted_at = NULL WHERE id = :i"), {"i": mid})
    assert set(entries(lookup(tag))) == {mid, added}
    assert entries(original)[mid].medication.name == tag


def test_alias_and_link_commits_visible_next_transaction__AC19(make, db):
    tag = "aliasfresh" + uuid4().hex
    aid, mid = make.ingredient(), make.catalog_medication(with_ingredient=False)
    assert not entries(lookup(tag))
    alias_id = db.execute(
        text(
            "INSERT INTO ingredient_aliases (active_ingredient_id, alias_text) "
            "VALUES (:a, :t) RETURNING id"
        ),
        {"a": aid, "t": tag},
    ).scalar_one()
    assert not entries(lookup(tag))
    link(db, mid, aid)
    assert set(entries(lookup(tag))) == {mid}
    renamed = tag + " renamed"
    db.execute(
        text("UPDATE ingredient_aliases SET alias_text = :t WHERE id = :i"),
        {"t": renamed, "i": alias_id},
    )
    assert entries(lookup(renamed))[mid].sources[0].alias_text == renamed
    db.execute(
        text(
            "DELETE FROM medication_active_ingredients "
            "WHERE medication_id = :m AND active_ingredient_id = :a"
        ),
        {"m": mid, "a": aid},
    )
    assert not entries(lookup(renamed))
    link(db, mid, aid)
    db.execute(text("DELETE FROM ingredient_aliases WHERE id = :i"), {"i": alias_id})
    assert not entries(lookup(renamed))


@pytest.mark.parametrize("break_after", [0, 1, 2])
def test_each_read_branch_failure_raises_without_partial_or_stale__AC19(
    admin_engine, make, break_after
):
    tag = "failure" + uuid4().hex
    make.catalog_medication(name=tag, active_ingredient=tag, with_ingredient=False)
    assert entries(lookup(tag))
    engine = create_engine(get_engine().url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            count = 0

            def terminate(conn, cursor, statement, parameters, context, executemany):
                nonlocal count
                if "catalog_search_key" in statement:
                    if count == break_after:
                        with admin_engine.connect() as killer:
                            assert killer.execute(
                                text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
                            ).scalar_one()
                    count += 1

            event.listen(connection, "before_cursor_execute", terminate)
            try:
                with pytest.raises(DBAPIError):
                    api.lookup_ocr_candidates(
                        SqlUnitOfWork(connection), api.normalize_ocr_text(tag)
                    )
            finally:
                event.remove(connection, "before_cursor_execute", terminate)
            assert count == break_after + 1
    finally:
        engine.dispose()


def test_expression_indexes_ready_and_used_in_eligibility_probe__AC16(make, db):
    key = "indexprobe" + uuid4().hex
    make.catalog_medication(name=key, active_ingredient=key, with_ingredient=False)
    make.ingredient(aliases=(key,))
    expected = {
        MatchKind.NAME: "medications_name_search_idx",
        MatchKind.RAW_ACTIVE_INGREDIENT: "medications_ingredient_search_idx",
        MatchKind.INGREDIENT_ALIAS: "ingredient_aliases_search_idx",
    }
    # Bulk budget fixtures can fill GIN's pending list; flush it and collect statistics
    # on the dedicated local test DB before probing planner eligibility.
    for index_name in expected.values():
        db.execute(text("SELECT gin_clean_pending_list(CAST(:i AS regclass))"), {"i": index_name})
    db.execute(text("ANALYZE medications"))
    db.execute(text("ANALYZE ingredient_aliases"))
    with unit_of_work() as uow:
        rows = list(
            uow.connection.execute(
                text(
                    "SELECT c.relname, i.indisvalid, i.indisready, "
                    "pg_get_indexdef(c.oid) AS definition "
                    "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE c.relname = ANY(:names)"
                ),
                {"names": list(expected.values())},
            )
        )
        assert {r.relname for r in rows} == set(expected.values())
        assert all(
            r.indisvalid
            and r.indisready
            and "USING gin" in r.definition
            and "catalog_search_key" in r.definition
            for r in rows
        )
        uow.connection.execute(text("SET LOCAL enable_seqscan = off"))
        uow.connection.execute(text("SET LOCAL enable_indexscan = off"))
        for kind, index_name in expected.items():
            statements, recorder = capture(uow.connection)
            try:
                SqlCatalog().find_ocr_matches(uow, key, kind)
            finally:
                event.remove(uow.connection, "before_cursor_execute", recorder)
            statement, params = statements[0]
            plan = uow.connection.exec_driver_sql(
                "EXPLAIN (FORMAT JSON) " + statement, params
            ).scalar_one()

            def names(node):
                found = {node["Index Name"]} if "Index Name" in node else set()
                for child in node.get("Plans", []):
                    found |= names(child)
                return found

            assert index_name in names(plan[0]["Plan"]), plan


def test_read_only_lookup_and_client_grants_remain_closed__AC21(make, db):
    tag = "readonly" + uuid4().hex
    make.catalog_medication(name=tag, with_ingredient=False)
    with unit_of_work() as uow:
        uow.connection.execute(text("SET TRANSACTION READ ONLY"))
        assert entries(api.lookup_ocr_candidates(uow, api.normalize_ocr_text(tag)))
    for role in ("anon", "authenticated"):
        for table in ("medications", "ingredient_aliases", "medication_active_ingredients"):
            assert not db.execute(
                text("SELECT has_table_privilege(:r, :t, 'SELECT')"), {"r": role, "t": table}
            ).scalar_one()
