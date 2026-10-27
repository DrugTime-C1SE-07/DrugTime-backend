-- Task 3.19: liều đã quá giờ dự kiến + 120' mà chưa xác minh được (checkpoint của patient còn
-- trước hạn chót). Worker xét lại ở các lượt sau, kể cả khi cursor quét đã đi qua liều.
-- Đây là hàng việc nội bộ của Worker, không phải trạng thái liều (BS-01); API không có quyền.

CREATE TABLE missed_dose_pending_verifications (
    medication_schedule_id bigint NOT NULL REFERENCES medication_schedules (id) ON DELETE CASCADE,
    scheduled_at timestamptz NOT NULL,
    patient_user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (medication_schedule_id, scheduled_at)
);

CREATE INDEX missed_dose_pending_verifications_patient_idx
    ON missed_dose_pending_verifications (patient_user_id);

ALTER TABLE missed_dose_pending_verifications ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON missed_dose_pending_verifications FROM PUBLIC, api_role, worker_role;
GRANT SELECT, INSERT, DELETE ON missed_dose_pending_verifications TO worker_role;

CREATE POLICY missed_dose_pending_verifications_worker_role ON missed_dose_pending_verifications
    FOR ALL TO worker_role USING (true) WITH CHECK (true);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON missed_dose_pending_verifications FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON missed_dose_pending_verifications FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON missed_dose_pending_verifications FROM service_role;
    END IF;
END
$$;

COMMENT ON TABLE missed_dose_pending_verifications IS
'Worker-only queue of doses past deadline whose patient has not synced since (task 3.19). '
'Not a dose status (BS-01); GET /adherence derives chua_xac_minh from dose_sync_checkpoints.';
