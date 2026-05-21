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


def test_document_chunk_embedding_dimension_is_768() -> None:
    embedding_column = DocumentChunk.__table__.columns["embedding"]

    assert embedding_column.type.dim == 768


def test_document_chunk_uses_chunk_metadata_column_name() -> None:
    assert "chunk_metadata" in DocumentChunk.__table__.columns
    assert "metadata" not in DocumentChunk.__table__.columns
