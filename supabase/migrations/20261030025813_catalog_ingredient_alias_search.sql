-- Alias retrieval uses the same immutable unaccent expression as catalog name search.
-- Transactional GIN build can block writes; deploy in a maintenance window.
BEGIN;
CREATE INDEX ingredient_aliases_search_idx
    ON public.ingredient_aliases
    USING gin (public.catalog_search_key(alias_text) extensions.gin_trgm_ops);
COMMIT;
