"""In-memory mock database fixture for DrugTime API scaffolding and contract testing (Schema v9)."""
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

def current_time_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class MockDatabase:
    def __init__(self):
        self.reset()

    def reset(self):
        self.users: Dict[str, Dict[str, Any]] = {
            "usr-patient-1": {
                "id": "usr-patient-1",
                "full_name": "Nguyễn Văn Bệnh Nhân",
                "ho_ten": "Nguyễn Văn Bệnh Nhân",
                "date_of_birth": "1958-04-12",
                "ngay_sinh": "1958-04-12",
                "gender": "nam",
                "gioi_tinh": "nam",
                "phone_number": "+84901234567",
                "so_dien_thoai": "+84901234567",
                "email": "benhnhan@example.com",
                "system_role": "user",
                "vai_tro_he_thong": "user",
                "erased_at": None,
                "created_at": "2026-09-01T08:00:00Z"
            },
            "usr-family-1": {
                "id": "usr-family-1",
                "full_name": "Nguyễn Thị Con Gái",
                "ho_ten": "Nguyễn Thị Con Gái",
                "date_of_birth": "1988-09-20",
                "ngay_sinh": "1988-09-20",
                "gender": "nu",
                "gioi_tinh": "nu",
                "phone_number": "+84909876543",
                "so_dien_thoai": "+84909876543",
                "email": "congai@example.com",
                "system_role": "user",
                "vai_tro_he_thong": "user",
                "erased_at": None,
                "created_at": "2026-09-01T09:00:00Z"
            },
            "usr-family-readonly": {
                "id": "usr-family-readonly",
                "full_name": "Trần Văn Người Thân Xem Thôi",
                "ho_ten": "Trần Văn Người Thân Xem Thôi",
                "date_of_birth": "1990-01-01",
                "ngay_sinh": "1990-01-01",
                "gender": "nam",
                "gioi_tinh": "nam",
                "phone_number": "+84911223344",
                "so_dien_thoai": "+84911223344",
                "email": "readonly@example.com",
                "system_role": "user",
                "vai_tro_he_thong": "user",
                "erased_at": None,
                "created_at": "2026-09-02T08:00:00Z"
            },
            "usr-admin-1": {
                "id": "usr-admin-1",
                "full_name": "Dược Sĩ Quản Trị Viên",
                "ho_ten": "Dược Sĩ Quản Trị Viên",
                "date_of_birth": "1985-11-30",
                "ngay_sinh": "1985-11-30",
                "gender": "nam",
                "gioi_tinh": "nam",
                "phone_number": "+84988888888",
                "so_dien_thoai": "+84988888888",
                "email": "admin1@drugtime.vn",
                "system_role": "admin",
                "vai_tro_he_thong": "admin",
                "erased_at": None,
                "created_at": "2026-08-01T00:00:00Z"
            },
            "usr-admin-2": {
                "id": "usr-admin-2",
                "full_name": "Thanh Tra Pháp Chế",
                "ho_ten": "Thanh Tra Pháp Chế",
                "date_of_birth": "1982-05-15",
                "ngay_sinh": "1982-05-15",
                "gender": "nu",
                "gioi_tinh": "nu",
                "phone_number": "+84977777777",
                "so_dien_thoai": "+84977777777",
                "email": "admin2@drugtime.vn",
                "system_role": "admin",
                "vai_tro_he_thong": "admin",
                "erased_at": None,
                "created_at": "2026-08-01T00:00:00Z"
            }
        }

        self.user_consents: List[Dict[str, Any]] = [
            {"id": 1, "user_id": "usr-patient-1", "consent_type": "health_data", "loai_dong_y": "health_data", "status": "dong_y", "trang_thai": "dong_y", "consented_at": "2026-09-01T08:05:00Z", "thoi_gian_dong_y": "2026-09-01T08:05:00Z", "revoked_at": None, "thoi_gian_thu_hoi": None, "document_version": "v1.0", "phien_ban_van_ban": "v1.0"},
            {"id": 2, "user_id": "usr-patient-1", "consent_type": "family_sharing", "loai_dong_y": "family_sharing", "status": "dong_y", "trang_thai": "dong_y", "consented_at": "2026-09-01T08:05:00Z", "thoi_gian_dong_y": "2026-09-01T08:05:00Z", "revoked_at": None, "thoi_gian_thu_hoi": None, "document_version": "v1.0", "phien_ban_van_ban": "v1.0"},
            {"id": 3, "user_id": "usr-patient-1", "consent_type": "ai_meal", "loai_dong_y": "ai_meal", "status": "dong_y", "trang_thai": "dong_y", "consented_at": "2026-09-01T08:05:00Z", "thoi_gian_dong_y": "2026-09-01T08:05:00Z", "revoked_at": None, "thoi_gian_thu_hoi": None, "document_version": "v1.0", "phien_ban_van_ban": "v1.0"},
        ]

        self.disease_groups: List[Dict[str, Any]] = [
            {"id": 1, "code": "tieu_duong", "name": "Đái tháo đường", "is_active": True},
            {"id": 2, "code": "tang_huyet_ap", "name": "Tăng huyết áp", "is_active": True},
            {"id": 3, "code": "suy_than", "name": "Suy thận", "is_active": True},
            {"id": 4, "code": "loet_da_day", "name": "Loét dạ dày tá tràng", "is_active": True}
        ]

        self.caregiver_links: List[Dict[str, Any]] = [
            {
                "id": 1,
                "patient_user_id": "usr-patient-1",
                "family_user_id": "usr-family-1",
                "status": "active",
                "trang_thai": "active",
                "sharing_enabled": True,
                "cho_phep_chia_se": True,
                "cho_phep_chinh_sua": True,
                "linked_at": "2026-09-02T10:00:00Z",
                "thoi_gian_lien_ket": "2026-09-02T10:00:00Z",
                "revoked_at": None,
                "thoi_gian_thu_hoi": None
            },
            {
                "id": 2,
                "patient_user_id": "usr-patient-1",
                "family_user_id": "usr-family-readonly",
                "status": "active",
                "trang_thai": "active",
                "sharing_enabled": True,
                "cho_phep_chia_se": True,
                "cho_phep_chinh_sua": False,
                "linked_at": "2026-09-03T10:00:00Z",
                "thoi_gian_lien_ket": "2026-09-03T10:00:00Z",
                "revoked_at": None,
                "thoi_gian_thu_hoi": None
            }
        ]

        self.link_codes: List[Dict[str, Any]] = [
            {
                "id": 1,
                "patient_user_id": "usr-patient-1",
                "code": "DT-1234",
                "ma": "DT-1234",
                "expires_at": "2026-12-31T23:59:59Z",
                "het_han_luc": "2026-12-31T23:59:59Z",
                "is_used": False,
                "da_dung": False,
                "family_user_id": None
            }
        ]

        self.conditions: List[Dict[str, Any]] = [
            {"id": 1, "name": "Đái tháo đường type 2", "ten": "Đái tháo đường type 2", "medical_nature": "benh_ly", "ban_chat_y_khoa": "benh_ly", "data_role": "sinh_hoat_chat_dieu_tri", "vai_tro_du_lieu": "sinh_hoat_chat_dieu_tri", "icd10_code": "E11"},
            {"id": 2, "name": "Tăng huyết áp vô căn", "ten": "Tăng huyết áp vô căn", "medical_nature": "benh_ly", "ban_chat_y_khoa": "benh_ly", "data_role": "sinh_hoat_chat_dieu_tri", "vai_tro_du_lieu": "sinh_hoat_chat_dieu_tri", "icd10_code": "I10"},
            {"id": 3, "name": "Suy thận mạn", "ten": "Suy thận mạn", "medical_nature": "benh_ly", "ban_chat_y_khoa": "benh_ly", "data_role": "dieu_chinh_thuoc_khac", "vai_tro_du_lieu": "dieu_chinh_thuoc_khac", "icd10_code": "N18"},
            {"id": 4, "name": "Loét dạ dày tá tràng", "ten": "Loét dạ dày tá tràng", "medical_nature": "benh_ly", "ban_chat_y_khoa": "benh_ly", "data_role": "dieu_chinh_thuoc_khac", "vai_tro_du_lieu": "dieu_chinh_thuoc_khac", "icd10_code": "K27"}
        ]

        self.user_conditions: List[Dict[str, Any]] = [
            {"id": 1, "user_id": "usr-patient-1", "condition_id": 1, "name": "Đái tháo đường type 2", "condition_name": "Đái tháo đường type 2", "subtype": "Type 2", "stage": None, "phan_do": None, "status": "active", "trang_thai": "active"},
            {"id": 2, "user_id": "usr-patient-1", "condition_id": 2, "name": "Tăng huyết áp vô căn", "condition_name": "Tăng huyết áp vô căn", "subtype": None, "stage": "Độ 2", "phan_do": "Độ 2", "status": "active", "trang_thai": "active"}
        ]

        self.medications: List[Dict[str, Any]] = [
            {
                "id": 101,
                "name": "Glucophage 500mg",
                "ten_thuoc": "Glucophage 500mg",
                "raw_active_ingredient": "Metformin hydrochloride 500mg",
                "hoat_chat_raw": "Metformin hydrochloride 500mg",
                "strength_text": "500mg",
                "ham_luong": "500mg",
                "dosage_form": "Viên nén bao phim",
                "dang_bao_che": "Viên nén bao phim",
                "manufacturer_name": "Merck Sante s.a.s",
                "cty_san_xuat_ten": "Merck Sante s.a.s",
                "manufacturer_country": "Pháp",
                "cty_san_xuat_nuoc": "Pháp",
                "packaging_spec": "Hộp 5 vỉ x 10 viên",
                "quy_cach_dong_goi": "Hộp 5 vỉ x 10 viên",
                "deleted_at": None,
                "active_ingredients": [
                    {"id": 1, "standard_name": "Metformin", "ten_hoat_chat_chuan": "Metformin", "strength_value": 500.0, "ham_luong_value": 500.0, "strength_unit": "mg", "ham_luong_unit": "mg", "dosing_unit": "viên", "don_vi_dinh_luong": "viên"}
                ]
            },
            {
                "id": 102,
                "name": "Amlor 5mg",
                "ten_thuoc": "Amlor 5mg",
                "raw_active_ingredient": "Amlodipine besylate 5mg",
                "hoat_chat_raw": "Amlodipine besylate 5mg",
                "strength_text": "5mg",
                "ham_luong": "5mg",
                "dosage_form": "Viên nang cứng",
                "dang_bao_che": "Viên nang cứng",
                "manufacturer_name": "Pfizer",
                "cty_san_xuat_ten": "Pfizer",
                "manufacturer_country": "Mỹ",
                "cty_san_xuat_nuoc": "Mỹ",
                "packaging_spec": "Hộp 3 vỉ x 10 viên",
                "quy_cach_dong_goi": "Hộp 3 vỉ x 10 viên",
                "deleted_at": None,
                "active_ingredients": [
                    {"id": 2, "standard_name": "Amlodipine", "ten_hoat_chat_chuan": "Amlodipine", "strength_value": 5.0, "ham_luong_value": 5.0, "strength_unit": "mg", "ham_luong_unit": "mg", "dosing_unit": "viên", "don_vi_dinh_luong": "viên"}
                ]
            },
            {
                "id": 103,
                "name": "Panadol Extra",
                "ten_thuoc": "Panadol Extra",
                "raw_active_ingredient": "Paracetamol 500mg, Caffeine 65mg",
                "hoat_chat_raw": "Paracetamol 500mg, Caffeine 65mg",
                "strength_text": "500mg + 65mg",
                "ham_luong": "500mg + 65mg",
                "dosage_form": "Viên nén dài",
                "dang_bao_che": "Viên nén dài",
                "manufacturer_name": "GSK",
                "cty_san_xuat_ten": "GSK",
                "manufacturer_country": "Việt Nam",
                "cty_san_xuat_nuoc": "Việt Nam",
                "packaging_spec": "Hộp 15 vỉ x 12 viên",
                "quy_cach_dong_goi": "Hộp 15 vỉ x 12 viên",
                "deleted_at": None,
                "active_ingredients": [
                    {"id": 3, "standard_name": "Paracetamol", "ten_hoat_chat_chuan": "Paracetamol", "strength_value": 500.0, "ham_luong_value": 500.0, "strength_unit": "mg", "ham_luong_unit": "mg", "dosing_unit": "viên", "don_vi_dinh_luong": "viên"},
                    {"id": 4, "standard_name": "Caffeine", "ten_hoat_chat_chuan": "Caffeine", "strength_value": 65.0, "ham_luong_value": 65.0, "strength_unit": "mg", "ham_luong_unit": "mg", "dosing_unit": "viên", "don_vi_dinh_luong": "viên"}
                ]
            }
        ]

        self.prescriptions: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "entry_source": "thu_cong",
                "nguon_nhap": "thu_cong",
                "prescribed_date": "2026-09-10",
                "ngay_ke_don": "2026-09-10",
                "prescribing_facility": "Bệnh viện Đà Nẵng",
                "noi_ke_don": "Bệnh viện Đà Nẵng",
                "status": "dang_dung",
                "trang_thai": "dang_dung"
            }
        ]

        self.user_medications: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "prescription_id": 1,
                "don_thuoc_id": 1,
                "medication_id": 101,
                "name": "Glucophage 500mg",
                "ten_thuoc": "Glucophage 500mg",
                "entry_method": "thu_cong",
                "cach_nhap": "thu_cong",
                "confirmation_status": "da_xac_nhan",
                "trang_thai_xac_nhan": "da_xac_nhan",
                "quantity_per_dose": 1.0,
                "so_luong_moi_lan": 1.0,
                "doses_per_day": 2,
                "so_lan_moi_ngay": 2,
                "dosing_unit": "viên",
                "don_vi_uong": "viên",
                "has_interaction_data": True,
                "co_du_lieu_tuong_tac": True,
                "status": "active",
                "trang_thai": "active"
            },
            {
                "id": 2,
                "user_id": "usr-patient-1",
                "prescription_id": 1,
                "don_thuoc_id": 1,
                "medication_id": 102,
                "name": "Amlor 5mg",
                "ten_thuoc": "Amlor 5mg",
                "entry_method": "thu_cong",
                "cach_nhap": "thu_cong",
                "confirmation_status": "da_xac_nhan",
                "trang_thai_xac_nhan": "da_xac_nhan",
                "quantity_per_dose": 1.0,
                "so_luong_moi_lan": 1.0,
                "doses_per_day": 1,
                "so_lan_moi_ngay": 1,
                "dosing_unit": "viên",
                "don_vi_uong": "viên",
                "has_interaction_data": True,
                "co_du_lieu_tuong_tac": True,
                "status": "active",
                "trang_thai": "active"
            }
        ]

        now_iso = current_time_iso()
        self.medication_schedules: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_medication_id": 1,
                "medication_name": "Glucophage 500mg",
                "ten_thuoc": "Glucophage 500mg",
                "schedule_type": "co_dinh",
                "loai_lich": "co_dinh",
                "intake_time": "08:00",
                "gio_uong": "08:00",
                "days_of_week": "2,3,4,5,6,7,CN",
                "ngay_trong_tuan": "2,3,4,5,6,7,CN",
                "reminder_enabled": True,
                "bat_tat_nhac": True,
                "effective_from": now_iso,
                "status": "active",
                "trang_thai": "active"
            },
            {
                "id": 2,
                "user_medication_id": 1,
                "medication_name": "Glucophage 500mg",
                "ten_thuoc": "Glucophage 500mg",
                "schedule_type": "co_dinh",
                "loai_lich": "co_dinh",
                "intake_time": "18:00",
                "gio_uong": "18:00",
                "days_of_week": "2,3,4,5,6,7,CN",
                "ngay_trong_tuan": "2,3,4,5,6,7,CN",
                "reminder_enabled": True,
                "bat_tat_nhac": True,
                "effective_from": now_iso,
                "status": "active",
                "trang_thai": "active"
            },
            {
                "id": 3,
                "user_medication_id": 2,
                "medication_name": "Amlor 5mg",
                "ten_thuoc": "Amlor 5mg",
                "schedule_type": "co_dinh",
                "loai_lich": "co_dinh",
                "intake_time": "08:00",
                "gio_uong": "08:00",
                "days_of_week": "2,3,4,5,6,7,CN",
                "ngay_trong_tuan": "2,3,4,5,6,7,CN",
                "reminder_enabled": True,
                "bat_tat_nhac": True,
                "effective_from": now_iso,
                "status": "active",
                "trang_thai": "active"
            }
        ]

        self.dose_logs: List[Dict[str, Any]] = [
            {
                "id": 1,
                "medication_schedule_id": 1,
                "medication_name": "Glucophage 500mg",
                "ten_thuoc": "Glucophage 500mg",
                "scheduled_at": "2026-09-21T08:00:00Z",
                "thoi_gian_du_kien": "2026-09-21T08:00:00Z",
                "taken_at": "2026-09-21T08:05:12Z",
                "thoi_gian_thuc_uong": "2026-09-21T08:05:12Z",
                "status": "Đã uống",
                "trang_thai": "Đã uống",
                "client_uuid": "c-uuid-001",
                "synced_at": "2026-09-21T08:06:00Z",
                "dong_bo_luc": "2026-09-21T08:06:00Z"
            }
        ]

        self.regimen_snapshots: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "analyzed_at": "2026-09-21T08:00:00Z",
                "thoi_gian_phan_tich": "2026-09-21T08:00:00Z",
                "finding_count": 1,
                "highest_severity": 2
            }
        ]

        self.regimen_findings: List[Dict[str, Any]] = [
            {
                "id": 1,
                "snapshot_id": 1,
                "warning_type": "Tương tác Thuốc - Thức ăn",
                "loai_canh_bao": "Tương tác Thuốc - Thức ăn",
                "source_table": "drug_food",
                "nguon_bang": "drug_food",
                "source_id": 1,
                "severity_level": 2,
                "muc_do": 2,
                "description": "Amlodipine dùng chung với nước bưởi chùm có thể làm tăng nồng độ thuốc trong máu gây tụt huyết áp.",
                "mo_ta": "Amlodipine dùng chung với nước bưởi chùm có thể làm tăng nồng độ thuốc trong máu gây tụt huyết áp.",
                "handling_type": "tranh_phoi_hop",
                "loai_xu_ly": "tranh_phoi_hop",
                "min_interval_hours": None,
                "khoang_cach_gio": None,
                "disclaimer": "Cảnh báo này có tính chất tham khảo y khoa, không thay thế cho chỉ định trực tiếp của bác sĩ hoặc dược sĩ chuyên môn.",
                "related_medication_ids": [2],
                "is_shown_to_user": True
            }
        ]

        self.meal_suggestions: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "meal_type": "Lunch",
                "bua_an": "Lunch",
                "suggestion_content": "Thực đơn kiểm soát đường huyết cho bệnh nhân đái tháo đường type 2 kết hợp tăng huyết áp.",
                "noi_dung_goi_y": "Thực đơn kiểm soát đường huyết cho bệnh nhân đái tháo đường type 2 kết hợp tăng huyết áp.",
                "based_on_conditions": ["Đái tháo đường type 2", "Tăng huyết áp vô căn"],
                "dua_tren_dieu_kien": ["Đái tháo đường type 2", "Tăng huyết áp vô căn"],
                "recommended_dishes": ["Cơm gạo lứt (1 chén)", "Cá hấp hành ghẹ", "Canh cải ngọt nấu thịt nạc", "Dưa leo"],
                "mon_an_khuyen_nghi": ["Cơm gạo lứt (1 chén)", "Cá hấp hành ghẹ", "Canh cải ngọt nấu thịt nạc", "Dưa leo"],
                "foods_to_avoid": ["Nước ép bưởi chùm (tránh tương tác Amlor)", "Đồ kho mặn, dưa muối"],
                "thuc_pham_tranh": ["Nước ép bưởi chùm (tránh tương tác Amlor)", "Đồ kho mặn, dưa muối"],
                "created_at": "2026-09-21T11:30:00Z",
                "ngay_tao": "2026-09-21T11:30:00Z"
            }
        ]

        self.meal_jobs: Dict[str, Dict[str, Any]] = {}
        self.data_export_jobs: Dict[str, Dict[str, Any]] = {}
        self.device_tokens: List[Dict[str, Any]] = []
        self.notifications: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-family-1",
                "about_patient_user_id": "usr-patient-1",
                "ve_patient_user_id": "usr-patient-1",
                "type": "canh_bao_bo_lo_lieu_nguoi_than",
                "loai": "canh_bao_bo_lo_lieu_nguoi_than",
                "content": "Người thân của bạn (Nguyễn Văn Bệnh Nhân) đã bỏ lỡ liều Glucophage lúc 08:00.",
                "noi_dung": "Người thân của bạn (Nguyễn Văn Bệnh Nhân) đã bỏ lỡ liều Glucophage lúc 08:00.",
                "is_read": False,
                "da_doc": False,
                "dedupe_key": "bo_lo:1:usr-family-1",
                "created_at": "2026-09-21T08:35:00Z",
                "thoi_gian": "2026-09-21T08:35:00Z"
            }
        ]
        self.access_logs: List[Dict[str, Any]] = []
        self.rule_change_logs: List[Dict[str, Any]] = [
            {
                "id": 1,
                "table_name": "active_ingredient_interactions",
                "record_id": 10,
                "action": "UPDATE",
                "old_data": {"severity_level": 3, "min_interval_hours": 2},
                "new_data": {"severity_level": 4, "min_interval_hours": 4},
                "changed_by": "usr-admin-1",
                "changed_at": "2026-09-18T10:00:00Z",
                "reason": "Cập nhật theo Dược thư Quốc gia Việt Nam bản sửa đổi 2026"
            }
        ]
        self.data_deletion_requests: List[Dict[str, Any]] = []
        self.dpia_records: List[Dict[str, Any]] = [
            {
                "id": 1,
                "data_flow_name": "Gửi điều kiện bệnh nền cho LLM sinh gợi ý bữa ăn (meal suggestion)",
                "ten_luong_du_lieu": "Gửi điều kiện bệnh nền cho LLM sinh gợi ý bữa ăn (meal suggestion)",
                "has_cross_border_transfer": True,
                "co_chuyen_du_lieu_xuyen_bien_gioi": True,
                "status": "da_phe_duyet",
                "trang_thai": "da_phe_duyet",
                "approved_by_id": "usr-admin-1",
                "nguoi_phe_duyet_id": "usr-admin-1",
                "approval_date": "2026-09-15",
                "ngay_phe_duyet": "2026-09-15"
            }
        ]

        # Schema v9 Group 8: Worker operational state & health
        self.worker_heartbeats: Dict[str, Dict[str, Any]] = {
            "drugtime-worker": {
                "worker_name": "drugtime-worker",
                "last_beat_at": current_time_iso(),
                "instance_id": "worker-inst-1"
            }
        }
        self.missed_dose_scan_cursor: Dict[str, Dict[str, Any]] = {
            "missed_dose_scan": {
                "job_name": "missed_dose_scan",
                "scanned_until": current_time_iso(),
                "updated_at": current_time_iso()
            }
        }
        self.catalog_sync_runs: List[Dict[str, Any]] = [
            {
                "id": 1,
                "source": "qd_5948",
                "started_at": "2026-09-20T02:00:00Z",
                "finished_at": "2026-09-20T02:05:00Z",
                "status": "thanh_cong",
                "records_inserted": 120,
                "records_updated": 45,
                "records_failed": 0,
                "error_details": None,
                "triggered_by": "scheduler"
            }
        ]

# Global singleton
db = MockDatabase()
