-- Task 3.19: điểm đồng bộ của patient. App gọi POST /doses/sync-checkpoints sau khi mọi mục
-- trong hàng chờ liều đã có kết quả cuối; Worker chỉ ghi bo_lo khi synced_at >= giờ dự kiến + 120'.
-- Một dòng mỗi tài khoản (một máy là đủ); giá trị là giờ server và không bao giờ lùi.

CREATE TABLE dose_sync_checkpoints (
    user_id uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    synced_at timestamptz NOT NULL
);

-- RLS như mọi bảng public; policy chỉ cho role của API và Worker.
ALTER TABLE dose_sync_checkpoints ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON dose_sync_checkpoints FROM PUBLIC, api_role, worker_role;
GRANT SELECT, INSERT, UPDATE ON dose_sync_checkpoints TO api_role;  -- upsert, đọc trong lịch sử
GRANT SELECT, DELETE ON dose_sync_checkpoints TO worker_role;       -- quét bỏ lỡ; xóa dữ liệu user (QD-35)

CREATE POLICY dose_sync_checkpoints_api_role ON dose_sync_checkpoints
    FOR ALL TO api_role USING (true) WITH CHECK (true);
CREATE POLICY dose_sync_checkpoints_worker_role ON dose_sync_checkpoints
    FOR ALL TO worker_role USING (true) WITH CHECK (true);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON dose_sync_checkpoints FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON dose_sync_checkpoints FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON dose_sync_checkpoints FROM service_role;
    END IF;
END
$$;

COMMENT ON TABLE dose_sync_checkpoints IS
'Last time any device of the user reported an empty dose outbox (task 3.19). Server time; never moves back.';
