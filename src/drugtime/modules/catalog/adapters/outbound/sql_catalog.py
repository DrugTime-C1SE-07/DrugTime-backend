from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.catalog.application.search_medications import escape_like
from drugtime.modules.catalog.domain.catalog_index import (
    CatalogHit,
    CatalogQueryResult,
    MatchKind,
)
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.errors import DomainError
from drugtime.shared.uow import UnitOfWork

_TABLE = "medications"


class SqlCatalog:
    # --- Dành cho tìm kiếm Mobile K04 & module khác ---
    def find_ocr_matches(
        self, uow: UnitOfWork, query_key: str, kind: MatchKind, *, limit: int = 200
    ) -> CatalogQueryResult:
        """Bound distinct IDs per source, retaining every alias hit for selected IDs."""
        if not query_key:
            return CatalogQueryResult(())
        if limit <= 0:
            raise ValueError("OCR candidate limit must be positive")
        columns = (
            "m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
            "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
            "WHERE mai.medication_id = m.id) AS has_active_ingredients "
        )
        if kind == MatchKind.INGREDIENT_ALIAS:
            sql = (
                "WITH matched AS MATERIALIZED ("
                "SELECT a.id AS alias_id, a.alias_text, a.active_ingredient_id, m.id "
                "FROM ingredient_aliases a "
                "JOIN medication_active_ingredients mai "
                "ON mai.active_ingredient_id = a.active_ingredient_id "
                "JOIN medications m ON m.id = mai.medication_id "
                "WHERE m.deleted_at IS NULL "
                "AND public.catalog_search_key(a.alias_text) LIKE :pattern ESCAPE '\\'), "
                "selected AS (SELECT DISTINCT id FROM matched ORDER BY id LIMIT :probe) "
                "SELECT " + columns + ", h.alias_id, h.alias_text, h.active_ingredient_id "
                "FROM selected s JOIN medications m ON m.id = s.id "
                "JOIN matched h ON h.id = s.id ORDER BY m.id, h.alias_id"
            )
        else:
            # Only these fixed identifiers enter SQL; OCR text is always a bound value.
            column = {
                MatchKind.NAME: "m.name",
                MatchKind.RAW_ACTIVE_INGREDIENT: "m.raw_active_ingredient",
            }[kind]
            sql = (
                "SELECT " + columns + " FROM medications m WHERE m.deleted_at IS NULL "
                f"AND public.catalog_search_key({column}) LIKE :pattern ESCAPE '\\' "
                "ORDER BY m.id LIMIT :probe"
            )
        rows = uow.connection.execute(
            text(sql), {"pattern": f"%{escape_like(query_key)}%", "probe": limit + 1}
        )
        # Consume the iterator before returning, so any late read failure aborts the call.
        hits = tuple(
            CatalogHit(
                CatalogMedication(
                    row.id, row.name, row.strength_text, row.dosage_form,
                    row.has_active_ingredients, row.raw_active_ingredient,
                ),
                row.alias_id if kind == MatchKind.INGREDIENT_ALIAS else None,
                row.alias_text if kind == MatchKind.INGREDIENT_ALIAS else None,
                row.active_ingredient_id if kind == MatchKind.INGREDIENT_ALIAS else None,
            )
            for row in rows
        )
        selected_ids = sorted({hit.medication.id for hit in hits})
        truncated = len(selected_ids) > limit
        allowed = set(selected_ids[:limit])
        return CatalogQueryResult(
            tuple(hit for hit in hits if hit.medication.id in allowed), truncated
        )

    def find_fuzzy_name_matches(
        self, uow: UnitOfWork, query_key: str, *, threshold: float, limit: int
    ) -> tuple[tuple[CatalogMedication, ...], bool]:
        """Names whose trigram similarity to `query_key` reaches `threshold` (pg_trgm `%`,
        served by the GIN index on catalog_search_key(name)); most similar first, then id."""
        if not query_key:
            return (), False
        if limit <= 0:
            raise ValueError("OCR fuzzy limit must be positive")
        c = uow.connection
        # Local to the request transaction; the OCR key is always a bound value.
        c.execute(
            text("SELECT set_config('pg_trgm.similarity_threshold', :t, true)"),
            {"t": str(threshold)},
        )
        rows = c.execute(
            text(
                "SELECT m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
                "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
                "WHERE mai.medication_id = m.id) AS has_active_ingredients "
                "FROM medications m WHERE m.deleted_at IS NULL "
                "AND public.catalog_search_key(m.name) OPERATOR(extensions.%) CAST(:key AS text) "
                "ORDER BY extensions.similarity(public.catalog_search_key(m.name), "
                "CAST(:key AS text)) DESC, m.id "
                "LIMIT :probe"
            ),
            {"key": query_key, "probe": limit + 1},
        ).all()
        found = tuple(
            CatalogMedication(
                row.id, row.name, row.strength_text, row.dosage_form,
                row.has_active_ingredients, row.raw_active_ingredient,
            )
            for row in rows[:limit]
        )
        return found, len(rows) > limit

    def get_medication(
        self, uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
    ) -> CatalogMedication | None:
        row = uow.connection.execute(
            text(
                "SELECT m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
                "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
                "        WHERE mai.medication_id = m.id) AS has_active_ingredients "
                "FROM medications m "
                "WHERE m.id = :id AND (:include_deleted OR m.deleted_at IS NULL)"
            ),
            {"id": medication_id, "include_deleted": include_deleted},
        ).first()
        if row is None:
            return None
        return CatalogMedication(
            id=row.id,
            name=row.name,
            strength_text=row.strength_text,
            dosage_form=row.dosage_form,
            has_active_ingredients=row.has_active_ingredients,
            active_ingredient=row.raw_active_ingredient,
        )

    def search(
        self, uow: UnitOfWork, terms: list[str], query: str, limit: int
    ) -> list[CatalogMedication]:
        """Tìm theo từ (contract `GET /catalog/medications`). `terms`, `query`: đã escape
        `\\ % _` (xem search_medications). Mọi phía so trên catalog_search_key (bỏ dấu, chữ
        thường); từ chữ đi qua index trigram của tên và hoạt chất. Từ có chữ số so sau khi bỏ
        khoảng trắng, thêm cột hàm lượng ("500mg" khớp "500 mg")."""
        if not terms:
            return []
        c = uow.connection
        # Chuẩn hóa trong DB (đúng hàm của index), một lần cho mọi từ, để mẫu LIKE là hằng.
        selects = ", ".join(f"public.catalog_search_key(:w{i})" for i in range(len(terms)))
        keys = c.execute(
            text(f"SELECT public.catalog_search_key(:q), {selects}"),
            {"q": query, **{f"w{i}": t for i, t in enumerate(terms)}},
        ).one()
        query_key, term_keys = keys[0], keys[1:]

        name = "public.catalog_search_key(m.name)"
        ingredient = "public.catalog_search_key(m.raw_active_ingredient)"
        strength = "replace(public.catalog_search_key(m.strength_text), ' ', '')"
        params: dict[str, object] = {"prefix": f"{query_key}%", "q": query_key, "limit": limit}
        where, in_name, in_strength = [], [], []
        for i, key in enumerate(term_keys):
            p = f":p{i}"
            if any(ch.isdigit() for ch in key):
                params[f"p{i}"] = f"%{key.replace(' ', '')}%"
                where.append(
                    f"(replace({name}, ' ', '') LIKE {p} ESCAPE '\\' "
                    f"OR replace({ingredient}, ' ', '') LIKE {p} ESCAPE '\\' "
                    f"OR {strength} LIKE {p} ESCAPE '\\')"
                )
                in_strength.append(f"coalesce({strength} LIKE {p} ESCAPE '\\', false)")
            else:
                params[f"p{i}"] = f"%{key}%"
                where.append(
                    f"({name} LIKE {p} ESCAPE '\\' OR {ingredient} LIKE {p} ESCAPE '\\' "
                    f"OR public.catalog_search_key(m.strength_text) LIKE {p} ESCAPE '\\')"
                )
                in_name.append(f"{name} LIKE {p} ESCAPE '\\'")
        # Thứ tự (contract): tên bắt đầu bằng q; mọi từ chữ nằm trong tên; mọi từ số khớp hàm
        # lượng; độ giống tên–q; tên, id. Nhóm từ rỗng thì bỏ bậc đó (Postgres không cho hằng
        # trong ORDER BY, và hằng cũng không đổi thứ tự).
        ranks = "".join(
            f"({' AND '.join(group)}) DESC, " for group in (in_name, in_strength) if group
        )
        rows = c.execute(
            text(
                "SELECT m.id, m.name, m.raw_active_ingredient, m.strength_text, m.dosage_form, "
                "EXISTS (SELECT 1 FROM medication_active_ingredients mai "
                "        WHERE mai.medication_id = m.id) AS has_active_ingredients "
                "FROM medications m "
                "WHERE m.deleted_at IS NULL AND " + " AND ".join(where) + " "
                f"ORDER BY ({name} LIKE :prefix ESCAPE '\\') DESC, {ranks}"
                f"extensions.similarity({name}, :q) DESC, "
                "m.name, m.id "
                "LIMIT :limit"
            ),
            params,
        )
        return [
            CatalogMedication(
                id=r.id,
                name=r.name,
                strength_text=r.strength_text,
                dosage_form=r.dosage_form,
                has_active_ingredients=r.has_active_ingredients,
                active_ingredient=r.raw_active_ingredient,
            )
            for r in rows
        ]

    # --- Dành cho Admin CRUD PB04 ---
    def create(self, uow: UnitOfWork, data: dict) -> dict:
        try:
            row = uow.connection.execute(
                text(f"""
                    INSERT INTO {_TABLE}
                      (name, raw_active_ingredient, strength_text, dosage_form,
                       manufacturer_name, manufacturer_country, packaging_spec, source, source_ref)
                    VALUES
                      (:name, :raw_active_ingredient, :strength_text, :dosage_form,
                       :manufacturer_name, :manufacturer_country, :packaging_spec, :source, :source_ref)
                    RETURNING id, name, raw_active_ingredient, strength_text, dosage_form,
                              manufacturer_name, manufacturer_country, packaging_spec, source, source_ref, deleted_at
                """),
                data,
            ).mappings().one()
        except IntegrityError as exc:
            # UNIQUE(source, source_ref) hoặc CHECK pair
            raise DomainError("Duplicate source/source_ref or constraint violation") from exc
        return dict(row)

    def get_active(self, uow: UnitOfWork, med_id: int) -> dict | None:
        row = uow.connection.execute(
            text(f"SELECT * FROM {_TABLE} WHERE id = :id AND deleted_at IS NULL"),
            {"id": med_id},
        ).mappings().first()
        return dict(row) if row else None

    def list_active(
        self, uow: UnitOfWork, q: str | None, skip: int, limit: int
    ) -> tuple[list[dict], int]:
        where = "WHERE deleted_at IS NULL"
        params: dict = {}
        if q:
            where += " AND name ILIKE :q"
            params["q"] = f"%{q}%"
        total = uow.connection.execute(
            text(f"SELECT count(*) FROM {_TABLE} {where}"), params
        ).scalar_one()
        rows = uow.connection.execute(
            text(f"SELECT * FROM {_TABLE} {where} ORDER BY id OFFSET :skip LIMIT :limit"),
            {**params, "skip": skip, "limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows], int(total)

    def update(self, uow: UnitOfWork, med_id: int, data: dict) -> dict | None:
        if not data:
            return self.get_active(uow, med_id)
        sets = ", ".join(f"{k} = :{k}" for k in data)
        try:
            row = uow.connection.execute(
                text(f"""
                    UPDATE {_TABLE} SET {sets}
                    WHERE id = :id AND deleted_at IS NULL
                    RETURNING *
                """),
                {"id": med_id, **data},
            ).mappings().first()
        except IntegrityError as exc:
            raise DomainError("Duplicate source/source_ref or constraint violation") from exc
        return dict(row) if row else None

    def soft_delete(self, uow: UnitOfWork, med_id: int) -> bool:
        row = uow.connection.execute(
            text(f"""
                UPDATE {_TABLE} SET deleted_at = now()
                WHERE id = :id AND deleted_at IS NULL
                RETURNING id
            """),
            {"id": med_id},
        ).first()
        return row is not None
