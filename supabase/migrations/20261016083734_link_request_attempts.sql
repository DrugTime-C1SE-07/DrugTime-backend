-- Task 3.13: lượt nhập sai mã liên kết của từng tài khoản (QD-34 (c)).
-- Mỗi dòng là một lần nhận 404 link_code_not_found; account_locked_until ghi quyết định khóa
-- sinh ra từ lượt đó, nên API chỉ cần SELECT/INSERT. Không lưu mã đã thử.

CREATE TABLE link_request_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    family_user_id uuid NOT NULL REFERENCES users (id),
    client_uuid uuid NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now(),
    account_locked_until timestamptz,
    CONSTRAINT link_request_attempts_family_client_uuid_key UNIQUE (family_user_id, client_uuid),
    CONSTRAINT link_request_attempts_locked_after_attempt_check
        CHECK (account_locked_until IS NULL OR account_locked_until > attempted_at)
);

CREATE INDEX link_request_attempts_family_time_idx
    ON link_request_attempts (family_user_id, attempted_at);

-- RLS như mọi bảng public; policy chỉ cho role của API và Worker.
ALTER TABLE link_request_attempts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON link_request_attempts FROM PUBLIC, api_role, worker_role;
GRANT SELECT, INSERT ON link_request_attempts TO api_role;
GRANT SELECT, DELETE ON link_request_attempts TO worker_role;  -- xóa dữ liệu user (QD-35)

CREATE POLICY link_request_attempts_api_role ON link_request_attempts
    FOR ALL TO api_role USING (true) WITH CHECK (true);
CREATE POLICY link_request_attempts_worker_role ON link_request_attempts
    FOR ALL TO worker_role USING (true) WITH CHECK (true);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON link_request_attempts FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON link_request_attempts FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON link_request_attempts FROM service_role;
    END IF;
END
$$;

COMMENT ON TABLE link_request_attempts IS
'Wrong link-code attempts per family account (QD-34 (c), task 3.13). Never stores the attempted code.';
COMMENT ON COLUMN link_request_attempts.account_locked_until IS
'Set on the attempt that reached the failure limit: the account cannot send link requests until then.';
