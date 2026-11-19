BEGIN;

CREATE TABLE public.health_profile_setup (
    user_id uuid PRIMARY KEY REFERENCES public.users (id) ON DELETE CASCADE,
    revision bigint NOT NULL CHECK (revision > 0),
    allergies_none_known boolean NOT NULL DEFAULT false,
    conditions_none_known boolean NOT NULL DEFAULT false,
    allergen_ids text[] NOT NULL DEFAULT '{}',
    custom_allergies text[] NOT NULL DEFAULT '{}',
    custom_conditions text[] NOT NULL DEFAULT '{}',
    CHECK (array_position(allergen_ids, NULL) IS NULL),
    CHECK (array_position(custom_allergies, NULL) IS NULL),
    CHECK (array_position(custom_conditions, NULL) IS NULL),
    CHECK (cardinality(custom_allergies) <= 30 AND cardinality(custom_conditions) <= 30),
    CHECK (NOT allergies_none_known OR
           (cardinality(allergen_ids) = 0 AND cardinality(custom_allergies) = 0)),
    CHECK (NOT conditions_none_known OR cardinality(custom_conditions) = 0)
);

ALTER TABLE public.health_profile_setup ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.health_profile_setup FROM PUBLIC, anon, authenticated, service_role, api_role, worker_role;
GRANT SELECT, INSERT, UPDATE ON public.health_profile_setup TO api_role;
GRANT DELETE ON public.health_profile_setup TO worker_role;
GRANT SELECT (user_id) ON public.health_profile_setup TO worker_role;

CREATE POLICY health_profile_setup_api
    ON public.health_profile_setup FOR ALL TO api_role
    USING (true) WITH CHECK (true);
CREATE POLICY health_profile_setup_worker_owner_id
    ON public.health_profile_setup FOR SELECT TO worker_role USING (true);
CREATE POLICY health_profile_setup_worker_erase
    ON public.health_profile_setup FOR DELETE TO worker_role USING (true);

COMMIT;
