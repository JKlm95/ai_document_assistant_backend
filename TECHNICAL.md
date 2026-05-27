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

## Documents

The current document lifecycle is metadata-first: users can create document records with title, original filename, MIME type, file size, storage provider placeholder, processing status, and optional content hash. There is no file upload, object storage, parsing, chunking, embedding, or AI processing in this stage.

Documents are owned globally by a user and can be attached to many projects through `project_documents`. Project-document linking is idempotent: repeating the same attach request returns the document without creating a duplicate link. Detach removes only the link, not the document metadata record.

Metadata-first architecture lets the API, ownership boundaries, project linking, and future processing state be validated before introducing storage and RAG complexity. The future RAG pipeline should add upload/storage, text extraction, chunk creation, embedding generation, and project-scoped vector retrieval filtered through `project_documents`.

## Upload Storage

Local upload storage is implemented behind a storage service abstraction in `app/storage`. The current implementation writes files to `storage/documents/{user_id}/{document_id}/original.{ext}` using `pathlib`, UUID-based directories, sanitized original filenames for metadata only, and chunked SHA-256 hashing while streaming the upload.

The upload lifecycle is: authenticate user, validate MIME/extension/size, reject empty files, write to local storage, create document metadata with `processing_status=uploaded`, and optionally attach the document to an owned project. If metadata creation fails after the file is written, the service deletes the stored file.

Security constraints: never trust client filenames for paths, prevent path traversal through storage-root resolution, avoid overwriting generated paths, keep storage outside public static serving, and return `404` for foreign project/document access to avoid resource existence leaks.

Future processing should transition `uploaded -> processing -> ready` or `failed`, then add parser-specific extraction, chunking, embedding generation, and RAG retrieval. S3/MinIO, presigned URLs, OCR, and background workers are intentionally out of scope for the local storage foundation.

## Document Processing

Document processing is synchronous in this stage. The lifecycle is `uploaded -> processing -> parsed -> chunked -> embedded -> indexed -> ready` on success and `uploaded|ready|failed -> processing -> failed` on controlled parser or file errors. Documents already in `processing` are blocked, while `ready` documents can be reprocessed.

Parser implementations live under `app/parsers` and are registered explicitly through `ParserRegistry`. The registry maps known MIME types and extensions to parser instances; unsupported types are handled as controlled failures. There is no dynamic importing, eval, plugin loading, AI call, embedding generation, or vector database interaction.

Current parsers support TXT and Markdown only. They read stored files as UTF-8 with fallback encodings, normalize line endings, and cap extracted text using `MAX_EXTRACTED_TEXT_CHARS`. PDF, DOCX, OCR, embeddings, and background workers are future RAG stages.

The parser abstraction exists before AI so storage, ownership, processing state, and text extraction can be tested independently. Future RAG should build on the extracted text and generated chunks by adding embedding generation, vector indexing, and project-scoped retrieval filtered through `project_documents`.

## Document Chunking

Chunking is implemented before embeddings so the system can validate deterministic text segmentation, ownership boundaries, and future retrieval inputs without calling any model provider or vector database.

The current strategy is `FixedSizeChunkingStrategy` in `app/chunking`. It normalizes whitespace, creates ordered fixed-size chunks with configurable `CHUNK_SIZE_CHARS` and `CHUNK_OVERLAP_CHARS`, ignores empty chunks, and estimates tokens with a simple `chars / 4` heuristic. Overlap must be smaller than chunk size.

Reprocessing deletes old chunks and recreates them from the latest extracted text. `Document.chunk_count` and `Document.chunked_at` are persisted after chunk creation. `GET /api/v1/documents/{document_id}/chunks` returns only chunks for documents owned by the authenticated user.

Future RAG work should add embeddings after chunking, then store vectors for these chunk rows and filter retrieval through `project_documents` so project chat only searches chunks from documents attached to that project.

## Embeddings And pgvector

Embeddings are implemented as a backend-controlled indexing foundation, not as chat or answer generation. `DocumentChunk` stores `embedding_status`, provider/model metadata, embedding dimensions, errors, timestamp, and `embedding_vector Vector(768)`. Chunks move through `pending -> embedded` or `failed`.

The embedding provider abstraction lives under `app/embeddings`. `EmbeddingProviderRegistry` is explicit and supports `mock` for deterministic dev/tests, an OpenAI skeleton that fails when no API key is configured, and a local placeholder for future Ollama/local models. There is no dynamic loading, auto-discovery, LangChain, Haystack, or LlamaIndex.

`DocumentEmbeddingService` reindexes safely by clearing previous vectors, embedding chunks again, recording partial failures per chunk, then moving the document through `embedded -> indexed -> ready` when no chunks exist or at least one chunk is indexed successfully. If all existing chunks fail, the document is marked `failed`.

pgvector is enabled through migrations and indexed with an HNSW cosine index on `document_chunks.embedding_vector`. Repository vector search uses cosine distance and is scoped by `documents.owner_id`, so users cannot retrieve chunks from other owners. `similar-chunks` returns ranked chunks only; it does not build prompts, citations, chat state, or AI answers.

Document metadata now includes classification and processing-mode hooks: `public/internal/confidential` and `local_only/external_allowed/prefer_local`. These fields prepare future AI routing and provider policy decisions but do not enforce a policy engine yet.
