from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    auth_secret: SecretStr = Field(min_length=32)
    frontend_url: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://xpenziq:xpenziq@localhost:5432/xpenziq"
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    max_upload_mb: int = Field(default=20, ge=1, le=100)
    max_pdf_pages: int = Field(default=40, ge=1, le=200)
    temp_upload_dir: Path = Path("./uploads")
    document_retention_hours: int = Field(default=24, ge=1, le=720)
    tesseract_cmd: str = "tesseract"
    access_token_minutes: int = Field(default=720, ge=5, le=1440)

    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must point to PostgreSQL.")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
