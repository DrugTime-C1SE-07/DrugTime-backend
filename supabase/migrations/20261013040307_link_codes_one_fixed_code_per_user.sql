-- QD-04: mỗi user có đúng một mã liên kết cố định, không hết hạn (task 3.10).
-- Mô hình cũ (mã dùng một lần, hết hạn) chưa từng được endpoint nào ghi.

-- 0. Xóa mã kiểu cũ sai định dạng mới: chưa từng được phát qua API. Nếu giữ lại, user đó nhận 500
--    vĩnh viễn vì mã không đổi được (QD-04); bỏ đi thì lần gọi đầu sinh mã mới.
DELETE FROM link_codes WHERE code !~ '^[A-HJKMNP-Z2-9]{10}$';

-- 1. Dọn trùng trước khi thêm UNIQUE: giữ dòng mới nhất của mỗi user.
DELETE FROM link_codes old
USING link_codes newer
WHERE newer.patient_user_id = old.patient_user_id
  AND (newer.created_at, newer.id) > (old.created_at, old.id);

-- 2. Bỏ mô hình mã dùng một lần, có hạn. CHECK và FK trên các cột này bị xóa theo cột.
DROP INDEX IF EXISTS link_codes_family_idx;
ALTER TABLE link_codes
    DROP COLUMN family_user_id,
    DROP COLUMN is_used,
    DROP COLUMN expires_at;

-- 3. Một mã mỗi user; index của UNIQUE thay cho index cũ. Định dạng mã khớp api_contract (QD-34).
DROP INDEX IF EXISTS link_codes_patient_idx;
ALTER TABLE link_codes
    ADD CONSTRAINT link_codes_patient_user_id_key UNIQUE (patient_user_id),
    ADD CONSTRAINT link_codes_code_format_check CHECK (code ~ '^[A-HJKMNP-Z2-9]{10}$');

-- 4. Grant tối thiểu: API đọc/tạo mã; Worker đọc/xóa khi xóa dữ liệu người dùng.
REVOKE UPDATE, DELETE ON link_codes FROM api_role;
REVOKE UPDATE ON link_codes FROM worker_role;
