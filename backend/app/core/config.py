from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str | None = None
    JWT_SECRET: str | None = None
    ALLOWED_ORIGIN: list[str] = []

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH, env_file_encoding="utf-8", extra="ignore"
    )


env_config = Settings()
