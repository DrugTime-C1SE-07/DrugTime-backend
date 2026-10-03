-- Tìm danh mục thuốc không phân biệt dấu tiếng Việt và hoa thường
-- (task adhoc-20261002-mobile-medication-api-integration, GET /catalog/medications).
BEGIN;

-- Supabase đặt extension ở schema `extensions`.
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;

-- api_role thực thi catalog_search_key, hàm này gọi extensions.unaccent.
GRANT USAGE ON SCHEMA extensions TO api_role;

-- Khóa so khớp: bỏ dấu (kể cả đ -> d) rồi chữ thường. Dạng hai tham số với từ điển chỉ định
-- rõ và search_path rỗng để kết quả không phụ thuộc phiên, nên khai báo IMMUTABLE được và
-- dùng làm biểu thức index. Đổi từ điển unaccent thì phải REINDEX hai index bên dưới.
CREATE FUNCTION public.catalog_search_key(t text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    STRICT
    PARALLEL SAFE
    SET search_path = ''
AS $$
    SELECT pg_catalog.lower(extensions.unaccent('extensions.unaccent'::regdictionary, t))
$$;

REVOKE ALL ON FUNCTION public.catalog_search_key(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.catalog_search_key(text) TO api_role;

-- Tìm theo chuỗi con ('%q%') ở mỗi lần gõ: cần trigram, B-tree không dùng được.
CREATE INDEX medications_name_search_idx
    ON medications USING gin (public.catalog_search_key(name) extensions.gin_trgm_ops);
CREATE INDEX medications_ingredient_search_idx
    ON medications USING gin (public.catalog_search_key(raw_active_ingredient) extensions.gin_trgm_ops);

COMMIT;
