from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://api_role:postgres@127.0.0.1:54322/postgres"
    redis_url: str = "redis://127.0.0.1:6379/0"

    supabase_url: str = "http://127.0.0.1:54321"
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_secret: str = ""

    notification_channel: str = "mock"
    fcm_project_id: str = ""

    llm_api_url: str = ""
    llm_api_key: str = ""

    session_jwt_secret: str = ""
    mobile_session_days: int = 10
    admin_session_idle_minutes: int = 20

    timezone: str = "Asia/Ho_Chi_Minh"
    tick_interval_seconds: int = 300
    missed_dose_grace_minutes: int = 60
    missed_dose_overlap_minutes: int = 30
    heartbeat_max_age_seconds: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
