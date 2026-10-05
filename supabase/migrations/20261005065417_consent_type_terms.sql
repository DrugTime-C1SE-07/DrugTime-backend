-- Thêm mục đích `terms` (đồng ý Điều khoản dịch vụ và Chính sách quyền riêng tư)
-- vào enum consent_type (task adhoc-20261003-login-medication-ui-fixes).
-- Bản ghi đồng ý điều khoản dùng lại bảng user_consents: cùng cột document_version,
-- cùng index một-dòng-hiệu-lực. Không đổi bảng, cột, grant hay RLS:
-- api_role đã có SELECT, INSERT, UPDATE trên user_consents.
--
-- Không đảo ngược được bằng một câu: Postgres không có DROP VALUE cho enum.
-- Muốn gỡ thì viết migration mới tạo lại kiểu consent_type.
-- Giá trị mới không được dùng trong cùng transaction với ADD VALUE, nên migration
-- này không chèn dữ liệu nào.
BEGIN;

ALTER TYPE consent_type ADD VALUE IF NOT EXISTS 'terms';

COMMIT;
