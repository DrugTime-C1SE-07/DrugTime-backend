-- Task 2.01: thuốc dùng khi cần, cách uống, tồn kho, chống tạo trùng khi thêm thuốc.
-- Không đổi grant: grant của user_medications/prescriptions cấp ở mức bảng nên phủ cột mới.
BEGIN;

CREATE TYPE medication_dosing_mode AS ENUM ('theo_gio', 'khi_can');
CREATE TYPE medication_intake_timing AS ENUM ('truoc_an', 'sau_an', 'khong_lien_quan');

-- Mọi dòng cũ là thuốc theo giờ nên DEFAULT 'theo_gio' đúng cho dữ liệu có sẵn.
ALTER TABLE user_medications
    ADD COLUMN dosing_mode medication_dosing_mode NOT NULL DEFAULT 'theo_gio',
    ADD COLUMN intake_timing medication_intake_timing,
    ADD COLUMN stock_quantity integer CHECK (stock_quantity BETWEEN 0 AND 9999),
    ADD COLUMN client_uuid uuid,
    -- Dòng cũ có client_uuid NULL; UNIQUE mặc định NULLS DISTINCT nên không vi phạm.
    ADD CONSTRAINT user_medications_client_uuid_uq UNIQUE (user_id, client_uuid);

COMMENT ON COLUMN user_medications.doses_per_day IS
    'theo_gio: số lần uống mỗi ngày (= số giờ của lịch đang mở). khi_can: số lần tối đa mỗi ngày.';
COMMENT ON COLUMN user_medications.client_uuid IS
    'Khóa chống tạo trùng do client sinh khi thêm thuốc; duy nhất theo người dùng.';
COMMENT ON COLUMN user_medications.stock_quantity IS
    'Số đơn vị còn lại; NULL = không theo dõi tồn kho.';

-- Mỗi người dùng có tối đa một đơn thuốc mặc định (thuốc nhập tay không thuộc đơn nào).
-- Trước khi áp lên môi trường có dữ liệu, truy vấn sau phải rỗng:
--   SELECT user_id FROM prescriptions WHERE entry_source = 'mac_dinh' GROUP BY 1 HAVING count(*) > 1;
CREATE UNIQUE INDEX prescriptions_one_default_per_user_uq
    ON prescriptions (user_id) WHERE entry_source = 'mac_dinh';

COMMIT;
