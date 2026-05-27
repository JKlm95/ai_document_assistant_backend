from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_current_user, get_project_retriever, get_project_service
from app.embeddings.base import EmbeddingProviderError, InvalidEmbeddingDimensionsError
from app.models.user import User
from app.rag.retriever import ProjectNotFoundError as RetrievalProjectNotFoundError
from app.rag.retriever import ProjectRetriever
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.schemas.rag import (
    ProjectSearchRequest,
    ProjectSearchResponse,
    ProjectSearchResultResponse,
    SourceReferenceResponse,
)
from app.services.project_service import (
    ProjectAccessDeniedError,
    ProjectNameAlreadyExistsError,
    ProjectNotFoundError,
    ProjectService,
)

router = APIRouter()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    try:
        project = await project_service.create_project(
            user_id=current_user.id,
            name=payload.name,
            description=payload.description,
        )
    except ProjectNameAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project name is already used",
        ) from exc
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    projects, total = await project_service.list_projects(
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(project) for project in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    try:
        project = await project_service.get_project(project_id=project_id, user_id=current_user.id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except ProjectAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project access denied",
        ) from exc
    return ProjectResponse.model_validate(project)


@router.post("/{project_id}/search", response_model=ProjectSearchResponse)
async def search_project(
    project_id: UUID,
    payload: ProjectSearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    project_retriever: Annotated[ProjectRetriever, Depends(get_project_retriever)],
) -> ProjectSearchResponse:
    try:
        result = await project_retriever.search_project(
            project_id=project_id,
            owner_id=current_user.id,
            query=payload.query,
            limit=payload.limit,
            include_context=payload.include_context,
        )
    except RetrievalProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except (EmbeddingProviderError, InvalidEmbeddingDimensionsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider unavailable",
        ) from exc

    return ProjectSearchResponse(
        query=result.query,
        project_id=result.project_id,
        results=[
            ProjectSearchResultResponse(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_title=item.document_title,
                chunk_index=item.chunk_index,
                text=item.text,
                similarity_score=item.similarity_score,
                source_reference=SourceReferenceResponse(**item.source_reference.__dict__),
                metadata=item.metadata,
            )
            for item in result.results
        ],
        context=result.context,
        citations=[
            SourceReferenceResponse(**citation.__dict__) for citation in result.citations
        ],
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectResponse:
    try:
        project = await project_service.update_project(
            project_id=project_id,
            user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            description_set="description" in payload.model_fields_set,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except ProjectAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project access denied",
        ) from exc
    except ProjectNameAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project name is already used",
        ) from exc
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    project_service: Annotated[ProjectService, Depends(get_project_service)],
) -> Response:
    try:
        await project_service.archive_project(project_id=project_id, user_id=current_user.id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc
    except ProjectAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project access denied",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
