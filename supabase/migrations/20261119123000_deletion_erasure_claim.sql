BEGIN;
ALTER TABLE data_deletion_requests
    ADD COLUMN erasure_started_at timestamptz,
    ADD CONSTRAINT deletion_no_cancel_after_erasure CHECK (
        cancelled_at IS NULL OR erasure_started_at IS NULL
    ),
    ADD CONSTRAINT deletion_erasure_after_deadline CHECK (
        erasure_started_at IS NULL OR scheduled_deletion_at IS NULL
        OR erasure_started_at >= scheduled_deletion_at
    );
-- Terminal lookup for an idempotent cancel after a lost ACK.
CREATE INDEX data_deletion_requests_user_history_idx
    ON data_deletion_requests (user_id, requested_at DESC, id DESC);
COMMIT;
