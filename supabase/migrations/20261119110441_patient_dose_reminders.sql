BEGIN;

GRANT INSERT ON public.access_logs TO worker_role;

CREATE POLICY access_logs_worker_reminder_insert ON public.access_logs
    FOR INSERT TO worker_role
    WITH CHECK (
        data_scope = 'lich_su_tuan_thu'
        AND (
            (result = 'allowed' AND actor_role = 'family')
            OR (result = 'denied' AND actor_role IN ('family', 'khong_co_quyen'))
        )
    );

COMMIT;
