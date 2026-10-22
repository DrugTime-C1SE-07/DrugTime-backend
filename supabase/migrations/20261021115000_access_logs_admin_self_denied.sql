BEGIN;

-- Admin self-access is denied, but its audit must retain the admin role.
ALTER TABLE public.access_logs
    DROP CONSTRAINT access_logs_actor_identity_check,
    ADD CONSTRAINT access_logs_actor_identity_check CHECK (
        ((actor_role = 'patient') = (actor_user_id = patient_user_id))
        OR (actor_role = 'admin' AND actor_user_id = patient_user_id AND result = 'denied')
    );

COMMIT;
