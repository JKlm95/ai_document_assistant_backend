from app.db.base import Base
from app.models import (
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    Project,
    ProjectDocument,
    User,
)


def test_models_import_successfully() -> None:
    assert User.__tablename__ == "users"
    assert Project.__tablename__ == "projects"
    assert Document.__tablename__ == "documents"
    assert ProjectDocument.__tablename__ == "project_documents"
    assert DocumentChunk.__tablename__ == "document_chunks"
    assert ChatSession.__tablename__ == "chat_sessions"
    assert ChatMessage.__tablename__ == "chat_messages"


def test_metadata_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "projects",
        "documents",
        "project_documents",
        "document_chunks",
        "chat_sessions",
        "chat_messages",
    }


def test_document_chunk_columns_match_chunking_contract() -> None:
    chunk_columns = DocumentChunk.__table__.columns

    assert "text" in chunk_columns
    assert "char_count" in chunk_columns
    assert "token_count_estimate" in chunk_columns
    assert "start_offset" in chunk_columns
    assert "end_offset" in chunk_columns
    assert "embedding" not in chunk_columns
    assert "chunk_metadata" not in chunk_columns


def test_document_metadata_columns_match_current_api_contract() -> None:
    document_columns = Document.__table__.columns

    assert "owner_id" in document_columns
    assert "title" in document_columns
    assert "original_filename" in document_columns
    assert "mime_type" in document_columns
    assert "file_size_bytes" in document_columns
    assert "processing_status" in document_columns
    assert "storage_path" in document_columns
    assert "file_extension" in document_columns
    assert "uploaded_at" in document_columns
    assert "chunk_count" in document_columns
    assert "chunked_at" in document_columns
