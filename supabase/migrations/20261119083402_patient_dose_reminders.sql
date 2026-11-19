BEGIN;

CREATE TABLE dose_reminder_requests (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sender_user_id uuid NOT NULL REFERENCES users(id),
    patient_user_id uuid NOT NULL REFERENCES users(id),
    schedule_id bigint NOT NULL REFERENCES medication_schedules(id),
    scheduled_at timestamptz NOT NULL,
    client_uuid uuid NOT NULL,
    notification_id bigint NOT NULL UNIQUE REFERENCES notifications(id),
    requested_at timestamptz NOT NULL,
    next_allowed_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'accepted'
        CHECK (status IN ('accepted', 'dispatched', 'cancelled', 'failed')),
    UNIQUE (sender_user_id, client_uuid),
    CHECK (sender_user_id <> patient_user_id),
    CHECK (next_allowed_at = requested_at + interval '600 seconds')
);
CREATE INDEX dose_reminder_occurrence_idx ON dose_reminder_requests
    (sender_user_id, patient_user_id, schedule_id, scheduled_at, requested_at DESC, id DESC);
CREATE INDEX dose_reminder_patient_idx ON dose_reminder_requests
    (patient_user_id, requested_at DESC, id DESC);
CREATE INDEX dose_reminder_schedule_idx ON dose_reminder_requests(schedule_id);
CREATE INDEX dose_reminder_retention_idx ON dose_reminder_requests(requested_at, id);

CREATE TABLE dose_reminder_outbox (
    reminder_id bigint PRIMARY KEY REFERENCES dose_reminder_requests(id) ON DELETE CASCADE,
    attempt_count smallint NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 3),
    due_at timestamptz NOT NULL,
    lease_until timestamptz,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'leased', 'done', 'dead')),
    last_error_code text,
    delivered_token_hashes text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX dose_reminder_pending_idx ON dose_reminder_outbox(due_at, reminder_id)
    WHERE state = 'pending';
CREATE INDEX dose_reminder_leased_idx ON dose_reminder_outbox(lease_until, reminder_id)
    WHERE state = 'leased';
CREATE INDEX patient_active_medications_idx ON user_medications(user_id, id DESC)
    WHERE deleted_at IS NULL AND ended_at IS NULL;

ALTER TABLE dose_reminder_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE dose_reminder_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON dose_reminder_requests, dose_reminder_outbox
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE dose_reminder_requests_id_seq
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON dose_reminder_requests TO api_role;
GRANT SELECT, INSERT ON dose_reminder_outbox TO api_role;
GRANT USAGE ON SEQUENCE dose_reminder_requests_id_seq TO api_role;
GRANT SELECT, DELETE ON dose_reminder_requests, dose_reminder_outbox TO worker_role;
GRANT UPDATE (status) ON dose_reminder_requests TO worker_role;
GRANT UPDATE (attempt_count, due_at, lease_until, state, last_error_code, delivered_token_hashes)
    ON dose_reminder_outbox TO worker_role;
GRANT INSERT (user_id, about_patient_user_id, type, content, created_at)
    ON notifications TO api_role;
GRANT USAGE ON SEQUENCE notifications_id_seq TO api_role;

CREATE POLICY reminder_request_api_read ON dose_reminder_requests FOR SELECT TO api_role USING (true);
CREATE POLICY reminder_request_api_insert ON dose_reminder_requests FOR INSERT TO api_role WITH CHECK (true);
CREATE POLICY reminder_request_worker_read ON dose_reminder_requests FOR SELECT TO worker_role USING (true);
CREATE POLICY reminder_request_worker_update ON dose_reminder_requests FOR UPDATE TO worker_role USING (true) WITH CHECK (true);
CREATE POLICY reminder_request_worker_delete ON dose_reminder_requests FOR DELETE TO worker_role USING (true);
CREATE POLICY reminder_outbox_api_read ON dose_reminder_outbox FOR SELECT TO api_role USING (true);
CREATE POLICY reminder_outbox_api_insert ON dose_reminder_outbox FOR INSERT TO api_role WITH CHECK (true);
CREATE POLICY reminder_outbox_worker_read ON dose_reminder_outbox FOR SELECT TO worker_role USING (true);
CREATE POLICY reminder_outbox_worker_update ON dose_reminder_outbox FOR UPDATE TO worker_role USING (true) WITH CHECK (true);
CREATE POLICY reminder_outbox_worker_delete ON dose_reminder_outbox FOR DELETE TO worker_role USING (true);
-- Existing notifications INSERT policy belongs to worker_role only.
CREATE POLICY reminder_notification_api_insert ON notifications FOR INSERT TO api_role
    WITH CHECK (type = 'nhac_uong_thuoc' AND user_id = about_patient_user_id);

COMMIT;
