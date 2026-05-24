from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService, InvalidCredentialsError
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService
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
