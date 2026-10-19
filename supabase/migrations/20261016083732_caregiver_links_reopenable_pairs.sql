-- Task 3.13: gửi lại yêu cầu liên kết sau khi bị từ chối hoặc bị hủy (QD-30, BS-04).
-- Mỗi cặp (người bệnh, người thân) có tối đa một dòng pending/active; dòng rejected/revoked
-- giữ làm lịch sử. Mọi dòng hiện có đã thỏa vì UNIQUE cũ chặt hơn index mới.

-- 1. Thay UNIQUE toàn phần bằng unique index một phần.
ALTER TABLE caregiver_links DROP CONSTRAINT caregiver_links_patient_user_id_family_user_id_key;

CREATE UNIQUE INDEX caregiver_links_one_open_pair_idx
    ON caregiver_links (patient_user_id, family_user_id)
    WHERE status IN ('pending', 'active');

-- Tra cặp (đang mở, chuỗi từ chối) thay cho index của UNIQUE vừa bỏ.
CREATE INDEX caregiver_links_pair_idx ON caregiver_links (patient_user_id, family_user_id);

-- Đếm yêu cầu người thân tạo trong ngày (QD-34: 10 yêu cầu/ngày).
CREATE INDEX caregiver_links_family_linked_at_idx ON caregiver_links (family_user_id, linked_at);

-- 2. Khóa chống gửi trùng của POST /family/link-requests. Dòng cũ không có nên để NULL.
ALTER TABLE caregiver_links ADD COLUMN client_uuid uuid;

CREATE UNIQUE INDEX caregiver_links_family_client_uuid_idx
    ON caregiver_links (family_user_id, client_uuid)
    WHERE client_uuid IS NOT NULL;

COMMENT ON COLUMN caregiver_links.client_uuid IS
'Idempotency key sent by the family member with POST /family/link-requests; unique per family member.';
