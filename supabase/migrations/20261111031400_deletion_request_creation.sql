ALTER TABLE data_deletion_requests
    ADD COLUMN scheduled_deletion_at timestamptz,
    ADD COLUMN cancelled_at timestamptz,
    ADD CONSTRAINT deletion_request_deadline_check CHECK (
        scheduled_deletion_at IS NULL OR
        scheduled_deletion_at = requested_at + interval '720 hours'
    ),
    ADD CONSTRAINT deletion_request_cancellation_check CHECK (
        cancelled_at IS NULL OR (
            scheduled_deletion_at IS NOT NULL AND status = 'cho_duyet'
            AND cancelled_at >= requested_at AND cancelled_at < scheduled_deletion_at
        )
    );

CREATE UNIQUE INDEX data_deletion_requests_active_idx ON data_deletion_requests (user_id)
    WHERE status IN ('cho_duyet', 'da_duyet') AND cancelled_at IS NULL;
DROP INDEX data_deletion_requests_one_open_idx;
CREATE INDEX data_deletion_requests_due_idx
    ON data_deletion_requests (scheduled_deletion_at, id)
    WHERE status = 'cho_duyet' AND scheduled_deletion_at IS NOT NULL AND cancelled_at IS NULL;

CREATE TABLE deletion_otp_challenges (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    challenge_id uuid,
    digest bytea,
    issued_at timestamptz,
    expires_at timestamptz,
    consumed_at timestamptz,
    last_sent_at timestamptz,
    send_window_at timestamptz,
    send_count integer NOT NULL DEFAULT 0 CHECK (send_count >= 0),
    failure_window_at timestamptz,
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    CHECK (num_nonnulls(challenge_id, digest, issued_at, expires_at) IN (0, 4)),
    CHECK (digest IS NULL OR octet_length(digest) = 32),
    CHECK (issued_at IS NULL OR expires_at > issued_at),
    CHECK (consumed_at IS NULL OR (
        issued_at IS NOT NULL AND consumed_at >= issued_at AND consumed_at < expires_at
    )),
    CHECK ((send_count = 0) = (send_window_at IS NULL)),
    CHECK ((failure_count = 0) = (failure_window_at IS NULL))
);

ALTER TABLE deletion_otp_challenges ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON deletion_otp_challenges FROM PUBLIC, anon, authenticated, service_role, worker_role;
GRANT SELECT, INSERT, UPDATE ON deletion_otp_challenges TO api_role;
CREATE POLICY deletion_otp_api ON deletion_otp_challenges TO api_role USING (true) WITH CHECK (true);
