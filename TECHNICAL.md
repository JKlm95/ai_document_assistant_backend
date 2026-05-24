# Technical Notes

## Architecture

The backend follows a layered FastAPI structure:

- `api` handles HTTP routing and dependency wiring.
- `schemas` contains Pydantic request and response contracts.
- `services` will contain business logic.
- `repositories` will contain database access.
- `models` contains SQLAlchemy ORM models.
- `providers` will contain AI provider abstractions.
- `processing` will contain document extraction and chunking.
- `rag` will contain retrieval, prompt building, and citation mapping.

Endpoints should stay thin. Business logic belongs in services, and database queries belong in repositories.

## Database

The project uses PostgreSQL with `pgvector`, SQLAlchemy async sessions, and Alembic migrations.

Document chunks store embeddings once per document. Project-scoped retrieval should filter chunks through `project_documents` instead of duplicating chunks per project.

## Data Model

Core tables:

- `users`: application users with unique email addresses.
- `projects`: user-owned knowledge-base projects. Project names are unique per user.
- `documents`: global user document library. Documents are not owned by a single project.
- `project_documents`: many-to-many join table that pins global documents to projects.
- `document_chunks`: extracted document chunks with one embedding per chunk.
- `chat_sessions`: project-scoped chat sessions, including optional provider/model metadata.
- `chat_messages`: session messages with role, content, and optional source citations.

Documents are global per user so the same uploaded file can be reused across multiple projects without duplicating storage, extracted text, chunks, or embeddings. Project-specific RAG should filter through `project_documents`, which keeps retrieval scoped to documents pinned to the selected project.

## Embeddings

The MVP uses `nomic-embed-text` for embeddings. Its vector dimension is `768`, so `document_chunks.embedding` is stored as `Vector(768)`.

The initial migration does not create a HNSW/IVFFLAT vector index yet. That index should be added after the RAG search query shape and distance metric are finalized, because pgvector index parameters affect recall, latency, and migration cost.

## Configuration

Runtime configuration is loaded from environment variables through `pydantic-settings`.

Secrets such as `JWT_SECRET` and `GEMINI_API_KEY` must stay outside git-tracked files.

## Authentication

Access tokens are signed JWT bearer tokens. JWT settings, including `JWT_SECRET`, algorithm, and token lifetime, are loaded from environment-backed settings.

Passwords are hashed with `bcrypt`. The password is SHA-256 prehashed before bcrypt to avoid bcrypt's 72-byte input limit and compatibility issues with newer `bcrypt` package behavior. Raw passwords and secrets must never be logged.

## Projects

Projects are strictly user-scoped. Every project endpoint requires the current authenticated user, and service-layer checks prevent reading, updating, or archiving projects owned by another user.

Project deletion is implemented as soft delete via `projects.is_archived`. Archived projects are hidden from list and detail endpoints by default, which preserves future references for documents and chat sessions. Project lists use `limit`/`offset` pagination and sort by `updated_at` descending.
