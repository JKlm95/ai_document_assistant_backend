from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    app_name: str = "AI Document Assistant API"
    api_v1_prefix: str = "/api/v1"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_document_assistant"
    )

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str | None = None
    default_llm_provider: str = "ollama"
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    chat_model: str = "llama3.1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
