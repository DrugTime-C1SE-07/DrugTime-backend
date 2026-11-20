BEGIN;
-- Legacy rows still require human approval. OTP-confirmed scheduled requests
-- are automatically claimed by the worker only once their deadline is reached.
DO $$
DECLARE constraint_name text;
BEGIN
    SELECT conname INTO constraint_name FROM pg_constraint
    WHERE conrelid = 'data_deletion_requests'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%handled_by_admin_id IS NOT NULL%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE data_deletion_requests DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;
ALTER TABLE data_deletion_requests ADD CONSTRAINT deletion_request_approval_check CHECK (
    status = 'cho_duyet' OR (handled_by_admin_id IS NOT NULL AND handled_at IS NOT NULL)
    OR (scheduled_deletion_at IS NOT NULL AND handled_by_admin_id IS NULL AND handled_at IS NULL
        AND status IN ('da_duyet', 'hoan_tat'))
);
ALTER TABLE data_deletion_requests DROP CONSTRAINT deletion_request_cancellation_check;
ALTER TABLE data_deletion_requests ADD CONSTRAINT deletion_request_cancellation_check CHECK (
    cancelled_at IS NULL OR (
        scheduled_deletion_at IS NOT NULL AND status IN ('cho_duyet', 'da_duyet')
        AND cancelled_at >= requested_at AND cancelled_at < scheduled_deletion_at
    )
);
-- No consent/link mutation: the pending-request PEP overlay is removed by cancellation.
COMMIT;
