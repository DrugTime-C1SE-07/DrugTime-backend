BEGIN;

-- Patient chọn có báo người giám sát khi bỏ lỡ liều hay không (màn Thông báo & Nhắc nhở).
-- Mặc định bật để giữ hành vi cũ; quyền theo bảng users đã có (api_role UPDATE, worker_role SELECT).
ALTER TABLE users
    ADD COLUMN missed_dose_family_alerts boolean NOT NULL DEFAULT true;

COMMIT;
