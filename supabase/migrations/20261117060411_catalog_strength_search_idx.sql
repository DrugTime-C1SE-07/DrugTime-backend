-- Tìm danh mục theo từ: mỗi từ có thể nằm ở tên, hoạt chất hoặc hàm lượng
-- (task adhoc-20261116-ocr-candidate-regression, contract GET /catalog/medications).
-- Tên và hoạt chất đã có index trigram (20261002101033_catalog_search_unaccent.sql); thiếu
-- index trên hàm lượng thì điều kiện OR của mỗi từ buộc quét cả bảng. Chỉ thêm index: không
-- đổi bảng, cột, quyền hay dữ liệu. catalog_search_key đã IMMUTABLE; đổi từ điển unaccent thì
-- phải REINDEX cả index này.
BEGIN;

CREATE INDEX medications_strength_search_idx
    ON medications USING gin (public.catalog_search_key(strength_text) extensions.gin_trgm_ops);

COMMIT;
