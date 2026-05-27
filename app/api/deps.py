from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking.fixed_size_chunker import FixedSizeChunkingStrategy
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.embeddings.base import EmbeddingProvider
from app.embeddings.registry import EmbeddingProviderRegistry
from app.llm.base import LLMProvider
from app.llm.registry import LLMProviderRegistry
from app.models.user import User
from app.parsers.registry import ParserRegistry
from app.rag.context_builder import ContextBuilder
from app.rag.prompt_builder import PromptBuilder
from app.rag.retriever import ProjectRetriever
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService, InvalidCredentialsError
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_processing_service import DocumentProcessingService
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService
from app.services.rag_answer_service import RagAnswerService
from app.storage.local_storage import LocalStorageService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRepository:
    return UserRepository(session)


def get_auth_service(
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(user_repository=user_repository, settings=settings)


def get_project_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProjectRepository:
    return ProjectRepository(session)


def get_document_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentRepository:
    return DocumentRepository(session)


def get_project_service(
    project_repository: Annotated[ProjectRepository, Depends(get_project_repository)],
) -> ProjectService:
    return ProjectService(project_repository=project_repository)


def get_document_service(
    document_repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    project_repository: Annotated[ProjectRepository, Depends(get_project_repository)],
) -> DocumentService:
    return DocumentService(
        document_repository=document_repository,
        project_repository=project_repository,
    )


def get_local_storage_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LocalStorageService:
    return LocalStorageService(
        storage_root=Path(settings.storage_root),
        max_upload_size_bytes=settings.max_upload_size_bytes,
        allowed_extensions=_split_csv_setting(settings.allowed_upload_extensions),
        allowed_mime_types=_split_csv_setting(settings.allowed_upload_mime_types),
    )


def get_parser_registry() -> ParserRegistry:
    return ParserRegistry()


def get_chunking_strategy(
    settings: Annotated[Settings, Depends(get_settings)],
) -> FixedSizeChunkingStrategy:
    return FixedSizeChunkingStrategy(
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
    )


def get_document_processing_service(
    document_repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    parser_registry: Annotated[ParserRegistry, Depends(get_parser_registry)],
    chunking_strategy: Annotated[FixedSizeChunkingStrategy, Depends(get_chunking_strategy)],
    storage_service: Annotated[LocalStorageService, Depends(get_local_storage_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentProcessingService:
    return DocumentProcessingService(
        document_repository=document_repository,
        parser_registry=parser_registry,
        chunking_strategy=chunking_strategy,
        storage_service=storage_service,
        max_extracted_text_chars=settings.max_extracted_text_chars,
    )


def get_embedding_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmbeddingProvider:
    return EmbeddingProviderRegistry(
        provider_name=settings.embedding_provider,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        openai_api_key=settings.openai_api_key,
    ).get_provider()


def get_document_embedding_service(
    document_repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentEmbeddingService:
    return DocumentEmbeddingService(
        document_repository=document_repository,
        embedding_provider=embedding_provider,
        embedding_dimensions=settings.embedding_dimensions,
    )


def get_context_builder(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContextBuilder:
    return ContextBuilder(max_chars=settings.context_max_chars)


def get_project_retriever(
    project_repository: Annotated[ProjectRepository, Depends(get_project_repository)],
    document_repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    context_builder: Annotated[ContextBuilder, Depends(get_context_builder)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProjectRetriever:
    return ProjectRetriever(
        project_repository=project_repository,
        document_repository=document_repository,
        embedding_provider=embedding_provider,
        embedding_dimensions=settings.embedding_dimensions,
        context_builder=context_builder,
        default_limit=settings.retrieval_default_limit,
        max_limit=settings.retrieval_max_limit,
    )


def get_llm_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMProvider:
    return LLMProviderRegistry(
        provider_name=settings.llm_provider,
        model_name=settings.llm_model,
        openai_api_key=settings.openai_api_key,
    ).get_provider()


def get_prompt_builder() -> PromptBuilder:
    return PromptBuilder()


def get_rag_answer_service(
    project_retriever: Annotated[ProjectRetriever, Depends(get_project_retriever)],
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    prompt_builder: Annotated[PromptBuilder, Depends(get_prompt_builder)],
) -> RagAnswerService:
    return RagAnswerService(
        project_retriever=project_retriever,
        llm_provider=llm_provider,
        prompt_builder=prompt_builder,
    )


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    try:
        return await auth_service.get_user_from_token(token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _split_csv_setting(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}
