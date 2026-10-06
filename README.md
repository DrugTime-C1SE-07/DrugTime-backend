# DrugTime Backend — API Scaffolding & Contract-First Specification

FastAPI Modular Monolith API phục vụ **Mobile App (Flutter)** và **Admin Web (Next.js)**.  
Hệ thống tuân thủ triệt để mô hình **Contract-First / API-First**, bảo vệ dữ liệu cá nhân theo **Nghị định 356/2025/NĐ-CP**, kiểm tra an toàn thuốc **Rule-based thuần túy (QA.04)** và ghi nhận vết kiểm toán **access_logs append-only (NFR06, QA.09)**.

---

## 🚀 Khởi Chạy Nhanh (Quick Start)

### 1. Cài đặt môi trường

```bash
cd backend
pip install -r requirements.txt
```

### 2. Chạy Dev Server

```bash
python main.py
# Hoặc:
python -m uvicorn drugtime.main:app --host 0.0.0.0 --port 8000
```

- **Swagger UI Interactive:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON Spec:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

### 3. Chạy Automated Test Suite (TDD)

```bash
pytest tests/ -v
```

---

## 🔑 Tài Khoản Mock Test Xác Thực (Auth Tokens)

Khi gọi API trên Swagger hoặc Postman, truyền header: `Authorization: Bearer <token>`:

- `Bearer usr-patient-1`: Bệnh nhân (chế độ Simple Mode bật, đầy đủ consent `health_data`, `family_sharing`, `ai_meal`).
- `Bearer usr-family-1`: Người thân có **cả quyền Xem lẫn quyền Ghi** (`cho_phep_chinh_sua: true`).
- `Bearer usr-family-readonly`: Người thân **chỉ có quyền Xem** (`cho_phep_chinh_sua: false`). Thao tác ghi sẽ bị chặn `403 INSUFFICIENT_WRITE_PERMISSION`.
- `Bearer usr-admin-1`: Quản trị viên hệ thống (Admin Catalog, can thiệp khẩn cấp, tra cứu `access_logs`).
- `Bearer usr-admin-2`: Quản trị viên độc lập thứ 2 (dùng thực hiện hậu kiểm Four-Eyes Post-Review `CANNOT_REVIEW_OWN_ACTION`).

---

## 🗺️ Bản Đồ Đối Chiếu Toàn Bộ Endpoints (Spec Mapping Table)

| STT        | Endpoint Gốc Đặc Tả                          | Endpoint Đã Scaffold                                           | Method     | Trạng Thái | Thay Đổi So Với Đặc Tả Gốc (27 Điểm)                                                             |
| ---------- | -------------------------------------------- | -------------------------------------------------------------- | ---------- | ---------- | ------------------------------------------------------------------------------------------------ |
| **Nhóm 1** | **Auth & User Profile**                      |                                                                |            |            |                                                                                                  |
| 1.1        | `/auth/sync-profile`                         | `/api/v1/auth/sync-profile`                                    | POST       | `done`     | Giữ nguyên, đồng bộ profile sang bảng `users`                                                    |
| 1.2        | `/users/me`                                  | `/api/v1/users/me`                                             | GET        | `done`     | Giữ nguyên, trả profile & Simple Mode                                                            |
| 1.3        | `/users/me`                                  | `/api/v1/users/me`                                             | PATCH      | `done`     | Giữ nguyên, cập nhật profile & Simple Mode                                                       |
| 1.4        | _(Mới - Điểm 12, 17)_                        | `/api/v1/users/me/data-export`                                 | POST       | `done`     | **[MỚI]** Khởi tạo Job xuất bản sao dữ liệu cá nhân bất đồng bộ (`202 Accepted`)                 |
| 1.5        | _(Mới - Điểm 17)_                            | `/api/v1/users/me/data-export/jobs/{job_id}`                   | GET        | `done`     | **[MỚI]** Poll trạng thái job xuất dữ liệu và nhận link tải file (hạn 24h)                       |
| 1.6        | `/users/me/device-tokens`                    | `/api/v1/users/me/device-tokens`                               | POST       | `done`     | Đăng ký FCM token                                                                                |
| 1.7        | `/users/me/device-tokens/{token}`            | `/api/v1/users/me/device-tokens/{fcm_token}`                   | DELETE     | `done`     | Hủy đăng ký FCM token                                                                            |
| **Nhóm 2** | **Consent & Privacy (NĐ 356)**               |                                                                |            |            |                                                                                                  |
| 2.1        | `/consents/me`                               | `/api/v1/consents/me`                                          | GET        | `done`     | Trả trạng thái 3 mục đích: `health_data`, `family_sharing`, `ai_meal`                            |
| 2.2        | `/consents`                                  | `/api/v1/consents`                                             | POST       | `done`     | Append-only lưu vết đồng thuận                                                                   |
| 2.3        | `/data-deletion-requests`                    | `/api/v1/data-deletion-requests`                               | POST       | `done`     | Gửi yêu cầu xóa dữ liệu cá nhân (chờ duyệt)                                                      |
| 2.4        | `/data-deletion-requests/me`                 | `/api/v1/data-deletion-requests/me`                            | GET        | `done`     | Kiểm tra tiến độ yêu cầu xóa dữ liệu                                                             |
| **Nhóm 3** | **Conditions & Health Profile**              |                                                                |            |            |                                                                                                  |
| 3.1        | `/conditions`                                | `/api/v1/conditions`                                           | GET        | `done`     | Danh mục bệnh nền chuẩn hóa (Bảng B)                                                             |
| 3.2        | `/patients/{id}/conditions`                  | `/api/v1/patients/{patient_id}/conditions`                     | GET        | `done`     | Đọc danh sách bệnh nền (RBAC kiểm tra quyền ĐỌC)                                                 |
| 3.3        | `/patients/{id}/conditions`                  | `/api/v1/patients/{patient_id}/conditions`                     | POST       | `done`     | Thêm bệnh nền (RBAC GHI + **Tự động trigger phân tích tương tác**)                               |
| 3.4        | `/patients/{id}/conditions/{id}`             | `/api/v1/patients/{patient_id}/conditions/{id}`                | DELETE     | `done`     | **[SỬA]** Soft-delete (`archived`), HTTP DELETE thuần không body                                 |
| **Nhóm 4** | **Prescriptions & Medications**              |                                                                |            |            |                                                                                                  |
| 4.1        | `/medications/search`                        | `/api/v1/medications/search`                                   | GET        | `done`     | Tra cứu catalog theo tên/hoạt chất                                                               |
| 4.2        | `/medications/{id}`                          | `/api/v1/medications/{id}`                                     | GET        | `done`     | Chi tiết thuốc & hoạt chất chuẩn Bảng A                                                          |
| 4.3        | `/medications/unmatched-scans`               | `/api/v1/medications/unmatched-scans`                          | POST       | `done`     | Ghi nhận chuỗi OCR không khớp catalog                                                            |
| 4.4        | _(Mới - Điểm 8, 16, 21)_                     | `/api/v1/patients/{patient_id}/prescriptions/ocr-upload`       | POST       | `done`     | **[MỚI]** Upload ảnh/PDF preview (Max 10MB; Quyền READ; Không ghi rác DB)                        |
| 4.5        | `/patients/{id}/prescriptions`               | `/api/v1/patients/{patient_id}/prescriptions`                  | GET        | `done`     | Lọc theo `trang_thai: dang_dung \| da_ket_thuc`                                                  |
| 4.6        | `/patients/{id}/prescriptions`               | `/api/v1/patients/{patient_id}/prescriptions`                  | POST       | `done`     | Tạo đơn mới kèm thuốc con (**Tự động trigger re-analyze**)                                       |
| 4.7        | `/prescriptions/{id}`                        | `/api/v1/prescriptions/{id}`                                   | GET        | `done`     | Chi tiết đơn thuốc                                                                               |
| 4.8        | _(Mới - Điểm 7)_                             | `/api/v1/prescriptions/{id}`                                   | PATCH      | `done`     | **[MỚI]** Sửa metadata đơn thuốc (`ngay_ke_don`, `noi_ke_don`) sau OCR                           |
| 4.9        | `/prescriptions/{id}/status`                 | `/api/v1/prescriptions/{id}/status`                            | PATCH      | `done`     | Kết thúc đơn thuốc (`da_ket_thuc`)                                                               |
| 4.10       | `/prescriptions/{id}/medications`            | `/api/v1/prescriptions/{id}/medications`                       | POST       | `done`     | Thêm thuốc lẻ vào đơn (**Tự động trigger re-analyze**)                                           |
| 4.11       | `/user-medications/{id}`                     | `/api/v1/user-medications/{id}`                                | PATCH      | `done`     | Sửa liều lượng (**Tự động trigger re-analyze**)                                                  |
| 4.12       | `/user-medications/{id}`                     | `/api/v1/user-medications/{id}`                                | DELETE     | `done`     | **[SỬA]** Soft-delete (`archived`), HTTP DELETE thuần không body                                 |
| **Nhóm 5** | **Schedules & Dose Logs**                    |                                                                |            |            |                                                                                                  |
| 5.1        | `/patients/{id}/schedules`                   | `/api/v1/patients/{patient_id}/schedules`                      | GET        | `done`     | Lấy lịch giờ uống phục vụ Local Notification                                                     |
| 5.2        | `/user-medications/{id}/schedules`           | `/api/v1/user-medications/{id}/schedules`                      | POST       | `done`     | **[SỬA]** Hỗ trợ `loai_lich: co_dinh \| khi_can` (Điểm 11)                                       |
| 5.3        | `/schedules/{id}`                            | `/api/v1/schedules/{id}`                                       | PATCH      | `done`     | Sửa giờ uống, bật/tắt nhắc                                                                       |
| 5.4        | _(Mới - Điểm 6, 24)_                         | `/api/v1/schedules/{id}`                                       | DELETE     | `done`     | **[MỚI]** Soft-delete lịch uống (`archived`), không body                                         |
| 5.5        | `/dose-logs/batch-sync`                      | `/api/v1/dose-logs/batch-sync`                                 | POST       | `done`     | **[SỬA]** Trả kết quả chi tiết per-item `{client_uuid, status, error_code}` (Điểm 3)             |
| 5.6        | `/patients/{id}/dose-logs`                   | `/api/v1/patients/{patient_id}/dose-logs`                      | GET        | `done`     | Lịch sử tuân thủ uống thuốc (phân trang)                                                         |
| 5.7        | `/patients/{id}/adherence-summary`           | `/api/v1/patients/{patient_id}/adherence-summary`              | GET        | `done`     | Thống kê % tuân thủ 7 ngày / 30 ngày                                                             |
| **Nhóm 6** | **Drug Safety & Interactions**               |                                                                |            |            |                                                                                                  |
| 6.1        | `/patients/{id}/regimens/analyze`            | `/api/v1/patients/{patient_id}/regimens/analyze`               | POST       | `stub`     | Phân tích an toàn xác định (Bảng A-F, không LLM, quyền READ)                                     |
| 6.2        | `/patients/{id}/regimens/findings`           | `/api/v1/patients/{patient_id}/regimens/findings`              | GET        | `done`     | Danh sách cảnh báo tương tác, mức độ 1-4, chỉ dẫn, disclaimer                                    |
| 6.3        | `/interactions/quick-check`                  | `/api/v1/interactions/quick-check`                             | POST       | `stub`     | Kiểm tra nhanh trước khi lưu thuốc (Preview check)                                               |
| 6.4        | `/recommendations/{id}/acknowledge`          | `/api/v1/recommendations/{id}/acknowledge`                     | PATCH      | `done`     | Đánh dấu bệnh nhân đã đọc khuyến nghị (duy nhất `self`)                                          |
| **Nhóm 7** | **Caregivers & Missed Dose Alerts**          |                                                                |            |            |                                                                                                  |
| 7.1        | `/caregivers/link-codes`                     | `/api/v1/caregivers/link-codes`                                | POST       | `done`     | Sinh mã 6 số / QR mời người thân (hạn 15 phút, Multi-use)                                        |
| 7.2        | `/caregivers/link-codes/redeem`              | `/api/v1/caregivers/link-codes/redeem`                         | POST       | `done`     | **[SỬA]** Rate-limit kép: 5 lần sai/15p theo caller + Hủy mã nếu bị dò sai > 10 lần              |
| 7.3        | `/caregivers/my-caregivers`                  | `/api/v1/caregivers/my-caregivers`                             | GET        | `done`     | Danh sách người thân, cờ `cho_phep_chia_se` và `cho_phep_chinh_sua`                              |
| 7.4        | `/caregivers/{link_id}`                      | `/api/v1/caregivers/{link_id}`                                 | PATCH      | `done`     | **[SỬA]** Bổ sung Admin Emergency Override (chỉ thu hồi, Header X-Admin-Reason, Four-Eyes ≤ 24h) |
| 7.5        | `/caregivers/monitored-patients`             | `/api/v1/caregivers/monitored-patients`                        | GET        | `done`     | Danh sách bệnh nhân đang giám sát (Multi-Patient Switcher)                                       |
| 7.6        | `/notifications`                             | `/api/v1/notifications`                                        | GET        | `done`     | Danh sách thông báo & cảnh báo người thân bỏ liều                                                |
| 7.7        | `/notifications/{id}/read`                   | `/api/v1/notifications/{id}/read`                              | PATCH      | `done`     | Đánh dấu đã đọc thông báo                                                                        |
| **Nhóm 8** | **AI Meal Suggestions**                      |                                                                |            |            |                                                                                                  |
| 8.1        | `/patients/{id}/meal-suggestions/generate`   | `/api/v1/patients/{patient_id}/meal-suggestions/generate`      | POST       | `stub`     | **[SỬA]** Chuyển sang **Async (`202 Accepted`)** trả về `job_id` (Điểm 10)                       |
| 8.2        | _(Mới - Điểm 10)_                            | `/api/v1/patients/{patient_id}/meal-suggestions/jobs/{job_id}` | GET        | `stub`     | **[MỚI]** Endpoint poll tiến độ job LLM                                                          |
| 8.3        | `/patients/{id}/meal-suggestions`            | `/api/v1/patients/{patient_id}/meal-suggestions`               | GET        | `done`     | Lịch sử các bữa ăn đã được gợi ý                                                                 |
| **Nhóm 9** | **Admin Operations & Compliance**            |                                                                |            |            |                                                                                                  |
| 9.1        | `/admin/medications`                         | `/api/v1/admin/medications`                                    | GET/POST   | `done`     | Quản lý catalog thuốc thương mại (Phân trang)                                                    |
| 9.2        | `/admin/medications/{id}`                    | `/api/v1/admin/medications/{id}`                               | PUT/DELETE | `done`     | Cập nhật / xóa thuốc catalog                                                                     |
| 9.3        | `/admin/active-ingredients`                  | `/api/v1/admin/active-ingredients`                             | CRUD       | `stub`     | Quản lý hoạt chất chuẩn hóa (Bảng A)                                                             |
| 9.4        | `/admin/conditions`                          | `/api/v1/admin/conditions`                                     | CRUD       | `done`     | Quản lý điều kiện bệnh lý nền (Bảng B)                                                           |
| 9.5        | `/admin/interactions`                        | `/api/v1/admin/interactions`                                   | CRUD       | `stub`     | Quản lý cặp tương tác thuốc (Bảng C) & ngưỡng liều                                               |
| 9.6        | `/admin/drug-foods`                          | `/api/v1/admin/drug-foods`                                     | CRUD       | `stub`     | Quản lý tương tác thuốc - thực phẩm (Bảng D)                                                     |
| 9.7        | _(Mới - Điểm 14)_                            | `/api/v1/admin/rule-change-logs`                               | GET        | `done`     | **[MỚI]** Tra cứu nhật ký thay đổi luật tương tác & catalog (Phân trang, Rollback)               |
| 9.8        | `/admin/catalog/sync`                        | `/api/v1/admin/catalog/sync`                                   | POST       | `stub`     | Kích hoạt worker đồng bộ dữ liệu Cục Quản lý Dược                                                |
| 9.9        | `/admin/catalog/sync-status`                 | `/api/v1/admin/catalog/sync-status`                            | GET        | `stub`     | Trạng thái tiến trình sync nền                                                                   |
| 9.10       | `/admin/unmatched-scans`                     | `/api/v1/admin/unmatched-scans`                                | GET        | `done`     | Danh sách chuỗi OCR chưa khớp catalog (Phân trang)                                               |
| 9.11       | `/admin/unmatched-scans/{id}/resolve`        | `/api/v1/admin/unmatched-scans/{id}/resolve`                   | PATCH      | `done`     | Đánh dấu đã ánh xạ hoặc thêm catalog                                                             |
| 9.12       | `/admin/audit-logs`                          | `/api/v1/admin/audit-logs`                                     | GET        | `done`     | **[SỬA]** Tra cứu nhật ký `access_logs` kèm phân trang & lọc can thiệp khẩn cấp                  |
| 9.13       | _(Mới - Điểm 26, 27)_                        | `/api/v1/admin/audit-logs/{id}/post-review`                    | POST       | `done`     | **[MỚI]** Hậu kiểm Four-Eyes trong 24h (3 trạng thái, 5 guardrails, chống tự review)             |
| 9.14       | `/admin/data-deletion-requests`              | `/api/v1/admin/data-deletion-requests`                         | GET        | `done`     | Danh sách yêu cầu xóa dữ liệu (Phân trang)                                                       |
| 9.15       | `/admin/data-deletion-requests/{id}/process` | `/api/v1/admin/data-deletion-requests/{id}/process`            | POST       | `done`     | Duyệt / từ chối yêu cầu xóa dữ liệu cá nhân                                                      |
