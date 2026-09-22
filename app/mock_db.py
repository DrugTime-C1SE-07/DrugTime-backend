"""In-memory mock database fixture for DrugTime API scaffolding and contract testing."""
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
                "ho_ten": "Nguyễn Văn Bệnh Nhân",
                "ngay_sinh": "1958-04-12",
                "gioi_tinh": "nam",
                "so_dien_thoai": "0901234567",
                "che_do_nguoi_cao_tuoi": True,
                "vai_tro_he_thong": "user",
                "created_at": "2026-09-01T08:00:00Z"
            },
            "usr-family-1": {
                "id": "usr-family-1",
                "ho_ten": "Nguyễn Thị Con Gái",
                "ngay_sinh": "1988-09-20",
                "gioi_tinh": "nu",
                "so_dien_thoai": "0909876543",
                "che_do_nguoi_cao_tuoi": False,
                "vai_tro_he_thong": "user",
                "created_at": "2026-09-01T09:00:00Z"
            },
            "usr-family-readonly": {
                "id": "usr-family-readonly",
                "ho_ten": "Trần Văn Người Thân Xem Thôi",
                "ngay_sinh": "1990-01-01",
                "gioi_tinh": "nam",
                "so_dien_thoai": "0911223344",
                "che_do_nguoi_cao_tuoi": False,
                "vai_tro_he_thong": "user",
                "created_at": "2026-09-02T08:00:00Z"
            },
            "usr-admin-1": {
                "id": "usr-admin-1",
                "ho_ten": "Dược Sĩ Quản Trị Viên",
                "ngay_sinh": "1985-11-30",
                "gioi_tinh": "nam",
                "so_dien_thoai": "0988888888",
                "che_do_nguoi_cao_tuoi": False,
                "vai_tro_he_thong": "admin",
                "created_at": "2026-08-01T00:00:00Z"
            },
            "usr-admin-2": {
                "id": "usr-admin-2",
                "ho_ten": "Thanh Tra Pháp Chế",
                "ngay_sinh": "1982-05-15",
                "gioi_tinh": "nu",
                "so_dien_thoai": "0977777777",
                "che_do_nguoi_cao_tuoi": False,
                "vai_tro_he_thong": "admin",
                "created_at": "2026-08-01T00:00:00Z"
            }
        }

        self.user_consents: List[Dict[str, Any]] = [
            {"id": 1, "user_id": "usr-patient-1", "loai_dong_y": "health_data", "trang_thai": "dong_y", "thoi_gian_dong_y": "2026-09-01T08:05:00Z", "thoi_gian_thu_hoi": None, "phien_ban_van_ban": "v1.0"},
            {"id": 2, "user_id": "usr-patient-1", "loai_dong_y": "family_sharing", "trang_thai": "dong_y", "thoi_gian_dong_y": "2026-09-01T08:05:00Z", "thoi_gian_thu_hoi": None, "phien_ban_van_ban": "v1.0"},
            {"id": 3, "user_id": "usr-patient-1", "loai_dong_y": "ai_meal", "trang_thai": "dong_y", "thoi_gian_dong_y": "2026-09-01T08:05:00Z", "thoi_gian_thu_hoi": None, "phien_ban_van_ban": "v1.0"},
        ]

        self.caregiver_links: List[Dict[str, Any]] = [
            {
                "id": 1,
                "patient_user_id": "usr-patient-1",
                "family_user_id": "usr-family-1",
                "trang_thai": "active",
                "cho_phep_chia_se": True,
                "cho_phep_chinh_sua": True,  # Quyền ghi được bật
                "thoi_gian_lien_ket": "2026-09-02T10:00:00Z",
                "thoi_gian_thu_hoi": None
            },
            {
                "id": 2,
                "patient_user_id": "usr-patient-1",
                "family_user_id": "usr-family-readonly",
                "trang_thai": "active",
                "cho_phep_chia_se": True,
                "cho_phep_chinh_sua": False, # Chỉ được xem, không được ghi
                "thoi_gian_lien_ket": "2026-09-03T10:00:00Z",
                "thoi_gian_thu_hoi": None
            }
        ]

        self.link_codes: List[Dict[str, Any]] = [
            {"id": 1, "patient_user_id": "usr-patient-1", "ma": "DT-1234", "het_han_luc": "2026-12-31T23:59:59Z", "da_dung": False, "family_user_id": None}
        ]

        self.conditions: List[Dict[str, Any]] = [
            {"id": 1, "ten": "Đái tháo đường type 2", "ban_chat_y_khoa": "benh_ly", "vai_tro_du_lieu": "sinh_hoat_chat_dieu_tri", "icd10_code": "E11"},
            {"id": 2, "ten": "Tăng huyết áp vô căn", "ban_chat_y_khoa": "benh_ly", "vai_tro_du_lieu": "sinh_hoat_chat_dieu_tri", "icd10_code": "I10"},
            {"id": 3, "ten": "Suy thận mạn", "ban_chat_y_khoa": "benh_ly", "vai_tro_du_lieu": "dieu_chinh_thuoc_khac", "icd10_code": "N18"},
            {"id": 4, "ten": "Loét dạ dày tá tràng", "ban_chat_y_khoa": "benh_ly", "vai_tro_du_lieu": "dieu_chinh_thuoc_khac", "icd10_code": "K27"}
        ]

        self.user_conditions: List[Dict[str, Any]] = [
            {"id": 1, "user_id": "usr-patient-1", "condition_id": 1, "condition_name": "Đái tháo đường type 2", "subtype": "Type 2", "phan_do": None, "trang_thai": "active"},
            {"id": 2, "user_id": "usr-patient-1", "condition_id": 2, "condition_name": "Tăng huyết áp vô căn", "subtype": None, "phan_do": "Độ 2", "trang_thai": "active"}
        ]

        self.medications: List[Dict[str, Any]] = [
            {
                "id": 101,
                "ten_thuoc": "Glucophage 500mg",
                "hoat_chat_raw": "Metformin hydrochloride 500mg",
                "ham_luong": "500mg",
                "dang_bao_che": "Viên nén bao phim",
                "cty_san_xuat_ten": "Merck Sante s.a.s",
                "cty_san_xuat_nuoc": "Pháp",
                "quy_cach_dong_goi": "Hộp 5 vỉ x 10 viên",
                "active_ingredients": [
                    {"id": 1, "ten_hoat_chat_chuan": "Metformin", "ham_luong_value": 500.0, "ham_luong_unit": "mg", "don_vi_dinh_luong": "viên"}
                ]
            },
            {
                "id": 102,
                "ten_thuoc": "Amlor 5mg",
                "hoat_chat_raw": "Amlodipine besylate 5mg",
                "ham_luong": "5mg",
                "dang_bao_che": "Viên nang cứng",
                "cty_san_xuat_ten": "Pfizer",
                "cty_san_xuat_nuoc": "Mỹ",
                "quy_cach_dong_goi": "Hộp 3 vỉ x 10 viên",
                "active_ingredients": [
                    {"id": 2, "ten_hoat_chat_chuan": "Amlodipine", "ham_luong_value": 5.0, "ham_luong_unit": "mg", "don_vi_dinh_luong": "viên"}
                ]
            },
            {
                "id": 103,
                "ten_thuoc": "Panadol Extra",
                "hoat_chat_raw": "Paracetamol 500mg, Caffeine 65mg",
                "ham_luong": "500mg + 65mg",
                "dang_bao_che": "Viên nén dài",
                "cty_san_xuat_ten": "GSK",
                "cty_san_xuat_nuoc": "Việt Nam",
                "quy_cach_dong_goi": "Hộp 15 vỉ x 12 viên",
                "active_ingredients": [
                    {"id": 3, "ten_hoat_chat_chuan": "Paracetamol", "ham_luong_value": 500.0, "ham_luong_unit": "mg", "don_vi_dinh_luong": "viên"},
                    {"id": 4, "ten_hoat_chat_chuan": "Caffeine", "ham_luong_value": 65.0, "ham_luong_unit": "mg", "don_vi_dinh_luong": "viên"}
                ]
            }
        ]

        self.prescriptions: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "nguon_nhap": "thu_cong",
                "ngay_ke_don": "2026-09-10",
                "noi_ke_don": "Bệnh viện Đà Nẵng",
                "trang_thai": "dang_dung"
            }
        ]

        self.user_medications: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "don_thuoc_id": 1,
                "medication_id": 101,
                "ten_thuoc": "Glucophage 500mg",
                "cach_nhap": "thu_cong",
                "trang_thai_xac_nhan": "da_xac_nhan",
                "so_luong_moi_lan": 1.0,
                "so_lan_moi_ngay": 2,
                "don_vi_uong": "viên",
                "co_du_lieu_tuong_tac": True,
                "trang_thai": "active"
            },
            {
                "id": 2,
                "user_id": "usr-patient-1",
                "don_thuoc_id": 1,
                "medication_id": 102,
                "ten_thuoc": "Amlor 5mg",
                "cach_nhap": "thu_cong",
                "trang_thai_xac_nhan": "da_xac_nhan",
                "so_luong_moi_lan": 1.0,
                "so_lan_moi_ngay": 1,
                "don_vi_uong": "viên",
                "co_du_lieu_tuong_tac": True,
                "trang_thai": "active"
            }
        ]

        self.medication_schedules: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_medication_id": 1,
                "ten_thuoc": "Glucophage 500mg",
                "loai_lich": "co_dinh",
                "gio_uong": "08:00",
                "ngay_trong_tuan": "2,3,4,5,6,7,CN",
                "bat_tat_nhac": True,
                "trang_thai": "active"
            },
            {
                "id": 2,
                "user_medication_id": 1,
                "ten_thuoc": "Glucophage 500mg",
                "loai_lich": "co_dinh",
                "gio_uong": "18:00",
                "ngay_trong_tuan": "2,3,4,5,6,7,CN",
                "bat_tat_nhac": True,
                "trang_thai": "active"
            },
            {
                "id": 3,
                "user_medication_id": 2,
                "ten_thuoc": "Amlor 5mg",
                "loai_lich": "co_dinh",
                "gio_uong": "08:00",
                "ngay_trong_tuan": "2,3,4,5,6,7,CN",
                "bat_tat_nhac": True,
                "trang_thai": "active"
            }
        ]

        self.dose_logs: List[Dict[str, Any]] = [
            {
                "id": 1,
                "medication_schedule_id": 1,
                "ten_thuoc": "Glucophage 500mg",
                "thoi_gian_du_kien": "2026-09-21T08:00:00Z",
                "thoi_gian_thuc_uong": "2026-09-21T08:05:12Z",
                "trang_thai": "Đã uống",
                "client_uuid": "c-uuid-001",
                "dong_bo_luc": "2026-09-21T08:06:00Z"
            }
        ]

        self.regimen_snapshots: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "thoi_gian_phan_tich": "2026-09-21T08:00:00Z",
                "finding_count": 1,
                "highest_severity": 2
            }
        ]

        self.regimen_findings: List[Dict[str, Any]] = [
            {
                "id": 1,
                "snapshot_id": 1,
                "loai_canh_bao": "Tương tác Thuốc - Thức ăn",
                "nguon_bang": "drug_food",
                "muc_do": 2,
                "mo_ta": "Amlodipine dùng chung với nước bưởi chùm có thể làm tăng nồng độ thuốc trong máu gây tụt huyết áp.",
                "loai_xu_ly": "tranh_phoi_hop",
                "khoang_cach_gio": None,
                "disclaimer": "Cảnh báo này có tính chất tham khảo y khoa, không thay thế cho chỉ định trực tiếp của bác sĩ hoặc dược sĩ chuyên môn.",
                "related_medication_ids": [2]
            }
        ]

        self.meal_suggestions: List[Dict[str, Any]] = [
            {
                "id": 1,
                "user_id": "usr-patient-1",
                "bua_an": "Trưa",
                "noi_dung_goi_y": "Thực đơn kiểm soát đường huyết cho bệnh nhân đái tháo đường type 2 kết hợp tăng huyết áp.",
                "dua_tren_dieu_kien": ["Đái tháo đường type 2", "Tăng huyết áp vô căn"],
                "mon_an_khuyen_nghi": ["Cơm gạo lứt (1 chén)", "Cá hấp hành ghẹ", "Canh cải ngọt nấu thịt nạc", "Dưa leo"],
                "thuc_pham_tranh": ["Nước ép bưởi chùm (tránh tương tác Amlor)", "Đồ kho mặn, dưa muối"],
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
                "ve_patient_user_id": "usr-patient-1",
                "loai": "canh_bao_bo_lo_lieu_nguoi_than",
                "noi_dung": "Người thân của bạn (Nguyễn Văn Bệnh Nhân) đã bỏ lỡ liều Glucophage lúc 08:00.",
                "da_doc": False,
                "thoi_gian": "2026-09-21T08:35:00Z"
            }
        ]
        self.unmatched_scans: List[Dict[str, Any]] = [
            {"id": 1, "user_id": "usr-patient-1", "chuoi_nhan_dien": "METFORMIN HYDROCLORID 850MG STADA", "thoi_gian": "2026-09-20T14:30:00Z", "admin_da_xem_xet": False}
        ]
        self.access_logs: List[Dict[str, Any]] = []
        self.rule_change_logs: List[Dict[str, Any]] = [
            {
                "id": 1,
                "table_name": "drug_interactions",
                "record_id": 10,
                "action": "UPDATE",
                "old_data": {"muc_do": 3, "khoang_cach_gio": 2},
                "new_data": {"muc_do": 4, "khoang_cach_gio": 4},
                "changed_by": "usr-admin-1",
                "changed_at": "2026-09-18T10:00:00Z",
                "reason": "Cập nhật theo Dược thư Quốc gia Việt Nam bản sửa đổi 2026"
            }
        ]
        self.data_deletion_requests: List[Dict[str, Any]] = []
        self.dpia_records: List[Dict[str, Any]] = [
            {
                "id": 1,
                "ten_luong_du_lieu": "Gửi điều kiện bệnh nền cho LLM sinh gợi ý bữa ăn (meal suggestion)",
                "co_chuyen_du_lieu_xuyen_bien_gioi": True,
                "trang_thai": "da_phe_duyet",
                "nguoi_phe_duyet_id": "usr-admin-1",
                "ngay_phe_duyet": "2026-09-15"
            }
        ]

# Global singleton
db = MockDatabase()
