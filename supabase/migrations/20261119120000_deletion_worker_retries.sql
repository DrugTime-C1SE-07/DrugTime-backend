BEGIN;
ALTER TABLE data_deletion_requests
    ADD COLUMN erasure_attempts integer NOT NULL DEFAULT 0 CHECK (erasure_attempts >= 0);
-- After five failures the row and last_error remain for the existing admin/support
-- workflow. No data is marked completed until all erasers and Auth deletion succeed.
COMMIT;
