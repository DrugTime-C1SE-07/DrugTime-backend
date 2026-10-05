from enum import StrEnum


class Purpose(StrEnum):
    HEALTH_DATA = "health_data"
    FAMILY_SHARING = "family_sharing"
    AI_MEAL = "ai_meal"
    # Đồng ý Điều khoản dịch vụ và Chính sách quyền riêng tư.
    # Để cuối: GET /consents trả theo thứ tự khai báo.
    TERMS = "terms"
