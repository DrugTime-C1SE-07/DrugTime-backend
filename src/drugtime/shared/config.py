from functools import lru_cache
from threading import BoundedSemaphore

from pydantic_settings import BaseSettings, SettingsConfigDict

EMAIL_SEND_SLOTS = BoundedSemaphore(5)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://api_role:postgres@127.0.0.1:54322/postgres"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "amqp://guest:guest@127.0.0.1:5672//"
    catalog_dav_drugbank_url: str = (
        "https://dichvucong.dav.gov.vn/api/services/app/soDangKy/GetAllPublicServerPaging"
    )

    supabase_url: str = "http://127.0.0.1:54321"
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_secret: str = ""

    notification_channel: str = "mock"
    fcm_project_id: str = ""
    # Đường dẫn file JSON service account (Render Secret File); không đặt nội dung vào biến.
    fcm_credentials_file: str = ""

    deletion_otp_hmac_key: str = ""
    email_change_otp_hmac_key: str = ""
    deletion_smtp_host: str = ""
    deletion_smtp_port: int = 465
    deletion_smtp_sender: str = ""
    deletion_smtp_username: str = ""
    deletion_smtp_password: str = ""

    llm_api_url: str = ""
    llm_api_key: str = ""

    session_jwt_secret: str = ""
    mobile_session_days: int = 10
    admin_session_idle_minutes: int = 20

    # Origin trình duyệt được gọi API (ví dụ Flutter web khi dev), cách nhau bởi dấu phẩy.
    # Rỗng = không bật CORS. Admin Web gọi qua route handler phía server nên không cần.
    cors_allowed_origins: str = ""

    # Gửi yêu cầu liên kết (task 3.13): khóa tài khoản nhập sai mã (QD-34 (c)),
    # giới hạn ngày (QD-34 (e)), chặn sau nhiều lần bị từ chối (BS-04).
    link_fail_window_minutes: int = 15
    link_fail_account_limit: int = 5
    link_lock_minutes: int = 15
    link_daily_request_limit: int = 10
    link_reject_streak_limit: int = 5
    link_reject_cooldown_hours: int = 24

    # Khớp văn bản OCR với danh mục (task 4.13, B4/B5/B7). Đổi cần khởi động lại;
    # giá trị sẽ được hiệu chỉnh ở 4.17. Kiểm tra ràng buộc ở catalog MatchPolicy.
    ocr_match_threshold: float = 0.7
    ocr_match_low_threshold: float = 0.4
    ocr_match_margin: float = 0.05
    ocr_match_default_limit: int = 5
    ocr_match_weight_name: float = 0.5
    ocr_match_weight_strength: float = 0.3
    ocr_match_weight_ingredient: float = 0.15
    ocr_match_weight_vote: float = 0.05
    ocr_match_fuzzy_similarity: float = 0.3
    ocr_match_fuzzy_limit: int = 50
    # R2 (03-plan §1): an OCR line this similar to a candidate's active ingredient text is an
    # ingredient line, not a brand line.
    ocr_match_ingredient_line_similarity: float = 0.6

    timezone: str = "Asia/Ho_Chi_Minh"
    tick_interval_seconds: int = 900
    missed_dose_grace_minutes: int = 120
    missed_dose_overlap_minutes: int = 30
    heartbeat_max_age_seconds: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
