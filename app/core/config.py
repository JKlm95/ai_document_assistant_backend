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
    embedding_provider: str = "mock"
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    openai_api_key: str | None = None
    vector_search_limit: int = 5
    chat_model: str = "llama3.1"

    storage_root: str = "storage"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    allowed_upload_extensions: str = "pdf,txt,md,docx"
    allowed_upload_mime_types: str = (
        "application/pdf,text/plain,text/markdown,application/markdown,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    max_extracted_text_chars: int = 1_000_000
    chunk_size_chars: int = 1_200
    chunk_overlap_chars: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
