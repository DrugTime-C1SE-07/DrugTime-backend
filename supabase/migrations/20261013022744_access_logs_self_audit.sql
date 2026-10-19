-- Discover the legacy unnamed checks rather than relying on generated names.
DO $$
DECLARE legacy_check record;
BEGIN
    FOR legacy_check IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'public.access_logs'::regclass AND contype = 'c'
          AND (pg_get_constraintdef(oid) LIKE '%actor_user_id%'
               OR pg_get_constraintdef(oid) LIKE '%actor_role%')
    LOOP
        EXECUTE format('ALTER TABLE public.access_logs DROP CONSTRAINT %I', legacy_check.conname);
    END LOOP;
END $$;

ALTER TABLE public.access_logs
    ADD CONSTRAINT access_logs_actor_identity_check
        CHECK ((actor_role = 'patient') = (actor_user_id = patient_user_id)),
    ADD CONSTRAINT access_logs_allowed_role_check
        CHECK (result = 'denied' OR actor_role IN ('patient', 'family', 'admin'));

REVOKE UPDATE, DELETE, TRUNCATE ON public.access_logs
    FROM PUBLIC, anon, authenticated, service_role, api_role, worker_role;

CREATE FUNCTION public.forbid_access_log_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'access_logs is append-only';
END $$;

CREATE TRIGGER access_logs_append_only
    BEFORE UPDATE OR DELETE ON public.access_logs
    FOR EACH ROW EXECUTE FUNCTION public.forbid_access_log_mutation();
CREATE TRIGGER access_logs_no_truncate
    BEFORE TRUNCATE ON public.access_logs
    FOR EACH STATEMENT EXECUTE FUNCTION public.forbid_access_log_mutation();
