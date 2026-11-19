BEGIN;

-- Shared allergen catalog for the health profile (task adhoc-20261118-health-profile-catalog).
-- Rows come from the reviewed data workbook via supabase/seeds/20_health_profile_catalog.sql.
-- health_profile_setup.allergen_ids stores these ids, so rows are never deleted: retire an
-- entry with is_active = false and it keeps its label for profiles that already chose it.
CREATE TABLE public.allergens (
    id text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9_]{0,63}$'),
    category text NOT NULL CHECK (category IN ('drug', 'food')),
    name text NOT NULL UNIQUE CHECK (btrim(name) <> ''),
    display_order smallint NOT NULL CHECK (display_order > 0),
    is_active boolean NOT NULL DEFAULT true,
    source text NOT NULL CHECK (btrim(source) <> ''),
    -- Deferred so a seed upsert may swap the order of two entries inside one transaction.
    CONSTRAINT allergens_category_display_order_key
        UNIQUE (category, display_order) DEFERRABLE INITIALLY DEFERRED
);

ALTER TABLE public.allergens ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.allergens FROM PUBLIC, anon, authenticated, service_role, api_role, worker_role;
GRANT SELECT ON public.allergens TO api_role;

CREATE POLICY allergens_api_read
    ON public.allergens FOR SELECT TO api_role USING (true);

CREATE FUNCTION public.forbid_allergen_delete() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = ''
AS $$
BEGIN
    RAISE EXCEPTION 'allergens rows cannot be deleted; set is_active = false instead';
END
$$;

CREATE TRIGGER allergens_no_delete
    BEFORE DELETE ON public.allergens
    FOR EACH ROW EXECUTE FUNCTION public.forbid_allergen_delete();
CREATE TRIGGER allergens_no_truncate
    BEFORE TRUNCATE ON public.allergens
    FOR EACH STATEMENT EXECUTE FUNCTION public.forbid_allergen_delete();

COMMIT;
