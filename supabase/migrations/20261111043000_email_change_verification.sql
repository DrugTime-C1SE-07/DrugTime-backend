CREATE TABLE email_change_challenges (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    challenge_id uuid UNIQUE,
    old_email text,
    new_email text,
    stage text NOT NULL DEFAULT 'idle' CHECK (stage IN ('idle', 'old', 'new', 'applying', 'done')),
    digest bytea,
    issued_at timestamptz,
    expires_at timestamptz,
    last_sent_at timestamptz,
    send_window_at timestamptz,
    send_count integer NOT NULL DEFAULT 0 CHECK (send_count >= 0),
    failure_window_at timestamptz,
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    CHECK (digest IS NULL OR octet_length(digest) = 32),
    CHECK ((send_count = 0) = (send_window_at IS NULL)),
    CHECK ((failure_count = 0) = (failure_window_at IS NULL)),
    CHECK (stage = 'idle' OR (challenge_id IS NOT NULL AND old_email IS NOT NULL
           AND new_email IS NOT NULL AND old_email <> new_email)),
    CHECK (stage NOT IN ('old', 'new') OR (digest IS NOT NULL AND issued_at IS NOT NULL
           AND expires_at IS NOT NULL AND expires_at > issued_at))
);
CREATE INDEX email_change_challenges_expires_idx ON email_change_challenges (expires_at)
    WHERE stage IN ('old', 'new');
ALTER TABLE email_change_challenges ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON email_change_challenges FROM PUBLIC, anon, authenticated, service_role, worker_role;
GRANT SELECT, INSERT, UPDATE ON email_change_challenges TO api_role;
CREATE POLICY email_change_api ON email_change_challenges TO api_role USING (true) WITH CHECK (true);
