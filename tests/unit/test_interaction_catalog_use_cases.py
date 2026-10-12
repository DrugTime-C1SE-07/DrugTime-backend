"""Unit test use case quy tắc tương tác có phiên bản, với port giả (task 2.16)."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from drugtime.modules.interaction.application.manage_drug_food_interactions import (
    drug_food_interaction_service,
)
from drugtime.modules.interaction.application.manage_drug_interactions import (
    drug_interaction_service,
)
from drugtime.modules.interaction.application.manage_rules import ListQuery
from drugtime.modules.interaction.domain.catalog_rules import (
    DoseThreshold,
    DrugFoodInteractionContent,
    DrugInteractionContent,
    HandlingType,
    InteractionType,
    RecordState,
    RuleRecord,
    VersionMeta,
)
from drugtime.shared.errors import Conflict, DomainError, NotFound

T0 = datetime(2026, 10, 11, tzinfo=UTC)
ADMIN = uuid4()
UOW = object()


class FakeStore:
    """Mô phỏng hành vi DB: mỗi phiên bản một bản ghi, trùng cặp → Conflict."""

    def __init__(self, pair_key):
        self.rows: dict[int, RuleRecord] = {}
        self.next_id = 100
        self.pair_key = pair_key
        self.calls: list[str] = []
        self.last_filters = None

    def _open(self):
        return [
            r
            for r in self.rows.values()
            if r.meta.superseded_at is None and r.meta.deleted_at is None
        ]

    def insert(self, uow, content, *, rule_id, version, created_by):
        self.calls.append("insert")
        if any(
            self.pair_key(r.content) == self.pair_key(content) and r.meta.rule_id != rule_id
            for r in self._open()
        ):
            raise Conflict("interaction_rule_exists")
        vid = self.next_id
        self.next_id += 1
        rid = rule_id or vid
        first = self.rows.get(rid)
        meta = VersionMeta(
            rid, version, vid, first.meta.created_at if first else T0, T0, created_by,
            None, None, None,
        )  # fmt: skip
        if isinstance(content, DrugInteractionContent):
            content = replace(
                content,
                dose_thresholds=tuple(
                    replace(t, id=1000 + vid * 10 + i)
                    for i, t in enumerate(content.dose_thresholds)
                ),
            )
        self.rows[vid] = RuleRecord(content, meta)
        return vid

    def lock(self, uow, rule_id):
        self.calls.append("lock")
        return any(r.meta.rule_id == rule_id for r in self.rows.values())

    def current(self, uow, rule_id):
        found = [
            r
            for r in self.rows.values()
            if r.meta.rule_id == rule_id and r.meta.superseded_at is None
        ]
        return found[0] if found else None

    def supersede(self, uow, version_id):
        self.calls.append("supersede")
        r = self.rows[version_id]
        self.rows[version_id] = replace(r, meta=replace(r.meta, superseded_at=T0))

    def mark_deleted(self, uow, version_id, deleted_by):
        self.calls.append("delete")
        r = self.rows[version_id]
        self.rows[version_id] = replace(
            r, meta=replace(r.meta, deleted_at=T0, deleted_by=deleted_by)
        )

    def get_version(self, uow, version_id):
        return self.rows.get(version_id)

    def versions(self, uow, rule_id):
        found = [r for r in self.rows.values() if r.meta.rule_id == rule_id]
        return sorted(found, key=lambda r: -r.meta.version)

    def list_current(self, uow, filters, skip, limit):
        self.last_filters = filters
        rows = [r for r in self._open()]
        return rows[skip : skip + limit], len(rows)


class FakeIngredients:
    def __init__(self, existing=(1, 2, 3), medication=None, matching=None):
        self.existing = set(existing)
        self.medication = medication or {}
        self.matching = matching or []

    def existing_ids(self, uow, ids):
        return self.existing & set(ids)

    def names(self, uow, ids):
        return {i: f"ingredient-{i}" for i in ids}

    def ids_matching(self, uow, q):
        return self.matching

    def ids_of_medication(self, uow, medication_id):
        return self.medication.get(medication_id, [])


class FakeAdmins:
    def emails(self, uow, user_ids):
        return {u: "admin@test.local" for u in user_ids}


def _ddi(**kw) -> DrugInteractionContent:
    base = dict(
        ingredient_a_id=1,
        ingredient_b_id=2,
        ingredient_b_external_name=None,
        interaction_type=InteractionType.DOSE_DEPENDENT,
        severity_level=2,
        handling_type=HandlingType.MONITOR,
        min_interval_hours=None,
        description="d",
        source="s",
        dose_thresholds=(DoseThreshold("A", 0.0, 100.0, "mg/ngày", 2, "w"),),
    )
    return DrugInteractionContent(**{**base, **kw})


def _pair(c):
    return frozenset(c.ingredient_ids()) if isinstance(c, DrugInteractionContent) else c


@pytest.fixture
def store():
    return FakeStore(_pair)


@pytest.fixture
def service(store):
    return drug_interaction_service(store, FakeIngredients(), FakeAdmins())


def test_create_returns_version_1_with_names(service):
    view = service.create(UOW, ADMIN, _ddi())
    assert view.record.meta.version == 1
    assert view.record.meta.state == RecordState.CURRENT
    assert view.ingredient_names == {1: "ingredient-1", 2: "ingredient-2"}
    assert view.admin_emails == {ADMIN: "admin@test.local"}


def test_create_unknown_ingredient_writes_nothing(store, service):
    with pytest.raises(DomainError, match="active_ingredient_not_found"):
        service.create(UOW, ADMIN, _ddi(ingredient_b_id=99))
    assert store.calls == []


def test_create_rule_violation_writes_nothing(store, service):
    with pytest.raises(DomainError, match="contraindication_severity_mismatch"):
        service.create(UOW, ADMIN, _ddi(interaction_type=InteractionType.CONTRAINDICATED))
    assert store.calls == []


def test_create_duplicate_pair_conflict(service):
    service.create(UOW, ADMIN, _ddi())
    with pytest.raises(Conflict, match="interaction_rule_exists"):
        service.create(UOW, ADMIN, _ddi(ingredient_a_id=2, ingredient_b_id=1))


def test_update_creates_new_version_and_keeps_old(store, service):
    v1 = service.create(UOW, ADMIN, _ddi())
    rid = v1.record.meta.rule_id
    v2 = service.update(UOW, ADMIN, rid, 1, {"severity_level": 3})
    assert (v2.record.meta.rule_id, v2.record.meta.version) == (rid, 2)
    assert v2.record.content.severity_level == 3
    old = store.get_version(UOW, v1.record.meta.version_id)
    assert old.meta.state == RecordState.SUPERSEDED
    assert old.content.severity_level == 2


def test_update_copies_thresholds_when_absent_and_replaces_when_sent(service):
    rid = service.create(UOW, ADMIN, _ddi()).record.meta.rule_id
    v2 = service.update(UOW, ADMIN, rid, 1, {"description": "new"})
    assert [t.min_dose for t in v2.record.content.dose_thresholds] == [0.0]
    new = [DoseThreshold("A", 300.0, None, "mg/ngày", 4, "x")]
    v3 = service.update(UOW, ADMIN, rid, 2, {"dose_thresholds": new})
    assert [t.min_dose for t in v3.record.content.dose_thresholds] == [300.0]


def test_update_noop_does_not_write(store, service):
    rid = service.create(UOW, ADMIN, _ddi()).record.meta.rule_id
    store.calls.clear()
    view = service.update(UOW, ADMIN, rid, 1, {"severity_level": 2})
    assert view.record.meta.version == 1
    assert store.calls == ["lock"]


def test_update_order_of_checks(store, service):
    with pytest.raises(NotFound, match="interaction_rule_not_found"):
        service.update(UOW, ADMIN, 12345, 1, {"severity_level": 3})
    rid = service.create(UOW, ADMIN, _ddi()).record.meta.rule_id
    # sai phiên bản báo 409 trước lỗi nghiệp vụ
    with pytest.raises(Conflict, match="version_conflict"):
        service.update(UOW, ADMIN, rid, 7, {"interaction_type": InteractionType.CONTRAINDICATED})
    with pytest.raises(DomainError, match="contraindication_severity_mismatch"):
        service.update(UOW, ADMIN, rid, 1, {"interaction_type": InteractionType.CONTRAINDICATED})


def test_update_after_delete_is_404(service):
    rid = service.create(UOW, ADMIN, _ddi()).record.meta.rule_id
    service.delete(UOW, ADMIN, rid, 1)
    with pytest.raises(NotFound):
        service.update(UOW, ADMIN, rid, 1, {"severity_level": 3})
    with pytest.raises(NotFound):
        service.get(UOW, rid)
    with pytest.raises(NotFound):
        service.delete(UOW, ADMIN, rid, 1)


def test_delete_stale_version_conflict(store, service):
    rid = service.create(UOW, ADMIN, _ddi()).record.meta.rule_id
    service.update(UOW, ADMIN, rid, 1, {"severity_level": 3})
    store.calls.clear()
    with pytest.raises(Conflict, match="version_conflict"):
        service.delete(UOW, ADMIN, rid, 1)
    assert "delete" not in store.calls


def test_history_newest_first_and_kept_after_delete(service):
    rid = service.create(UOW, ADMIN, _ddi()).record.meta.rule_id
    service.update(UOW, ADMIN, rid, 1, {"severity_level": 3})
    service.delete(UOW, ADMIN, rid, 2)
    history = service.history(UOW, rid)
    assert [v.record.meta.version for v in history] == [2, 1]
    assert [v.record.meta.state for v in history] == [RecordState.DELETED, RecordState.SUPERSEDED]
    with pytest.raises(NotFound, match="interaction_rule_not_found"):
        service.history(UOW, 999)


def test_get_version_not_found(service):
    with pytest.raises(NotFound, match="interaction_version_not_found"):
        service.get_version(UOW, 999)


def test_list_with_unknown_medication_short_circuits(store):
    service = drug_interaction_service(store, FakeIngredients(medication={}), FakeAdmins())
    assert service.list(UOW, ListQuery(medication_id=5)) == ([], 0)
    assert store.last_filters is None


def test_list_builds_filters(store):
    ingredients = FakeIngredients(medication={5: [1, 3]}, matching=[2])
    service = drug_interaction_service(store, ingredients, FakeAdmins())
    service.list(UOW, ListQuery(q="  war ", medication_id=5, severity_level=2, ingredient_id=1))
    f = store.last_filters
    assert (f.query_text, f.query_ingredient_ids, f.medication_ingredient_ids) == (
        "war",
        [2],
        [1, 3],
    )
    assert (f.severity_level, f.ingredient_id) == (2, 1)
    service.list(UOW, ListQuery(q="   "))
    assert store.last_filters.query_text is None


def test_food_service_flow():
    store = FakeStore(lambda c: (c.ingredient_id, c.food_to_avoid.lower()))
    service = drug_food_interaction_service(store, FakeIngredients(), FakeAdmins())
    food = DrugFoodInteractionContent(1, "Bưởi", 3, "r", "s")
    rid = service.create(UOW, ADMIN, food).record.meta.rule_id
    with pytest.raises(Conflict, match="interaction_rule_exists"):
        service.create(UOW, ADMIN, replace(food, food_to_avoid="bưởi"))
    v2 = service.update(UOW, ADMIN, rid, 1, {"severity_level": 4})
    assert v2.record.meta.version == 2
    with pytest.raises(DomainError, match="active_ingredient_not_found"):
        service.create(UOW, ADMIN, replace(food, ingredient_id=42))
