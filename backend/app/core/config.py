from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str | None = None
    JWT_SECRET: str | None = None
    ALLOWED_ORIGIN: str | None = None
    GROQ_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    SUPABASE_URL: str | None = None
    SUPABASE_KEY: str | None = None
    SPREADSHEAT_BUCKET_NAME: str | None = None
    IMAGE_BUCKET_NAME: str | None = None
    SUPABASE_PROJECT_ID: str | None = None
    SUPABASE_SECRET_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH, env_file_encoding="utf-8", extra="ignore"
    )


env_config = Settings()
