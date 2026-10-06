-- Xoá mềm thuốc của người bệnh (task adhoc-20261002-mobile-medication-api-integration).
-- Không xoá cứng: dose_logs và regimen_analysis_finding_medications trỏ tới thuốc/lịch bằng FK
-- không cascade, và lịch sử liều phải giữ cho báo cáo tuân thủ.
-- Không đổi grant: grant của user_medications cấp ở mức bảng nên phủ cột mới.
BEGIN;

-- Nullable, mọi dòng cũ là chưa xoá nên an toàn trên bảng có dữ liệu.
ALTER TABLE user_medications
    ADD COLUMN deleted_at timestamptz,
    ADD CONSTRAINT user_medications_deleted_requires_ended
        CHECK (deleted_at IS NULL OR ended_at IS NOT NULL);

COMMENT ON COLUMN user_medications.deleted_at IS
    'Xoá mềm do người bệnh; NULL = chưa xoá. Thuốc đã xoá phải có ended_at và không còn lịch mở.';

-- Phục vụ GET /medications: thuốc chưa xoá của một người, id giảm dần.
CREATE INDEX user_medications_user_active_idx
    ON user_medications (user_id, id DESC)
    WHERE deleted_at IS NULL;

COMMIT;
