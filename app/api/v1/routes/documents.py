from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.deps import (
    get_current_user,
    get_document_processing_service,
    get_document_service,
    get_local_storage_service,
)
from app.models.user import User
from app.schemas.document import (
    DocumentContentResponse,
    DocumentCreateRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from app.services.document_processing_service import (
    DocumentAlreadyProcessingError,
    DocumentProcessingService,
)
from app.services.document_processing_service import (
    DocumentNotFoundError as ProcessingDocumentNotFoundError,
)
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentService,
    ProjectDocumentLinkNotFoundError,
    ProjectNotFoundError,
)
from app.storage.local_storage import (
    EmptyUploadError,
    LocalStorageService,
    StorageConflictError,
    UnsupportedUploadTypeError,
    UploadTooLargeError,
)

router = APIRouter()


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    document = await document_service.create_document(
        owner_id=current_user.id,
        title=payload.title,
        original_filename=payload.original_filename,
        mime_type=payload.mime_type,
        file_size_bytes=payload.file_size_bytes,
        storage_provider=payload.storage_provider,
        content_hash=payload.content_hash,
    )
    return DocumentResponse.model_validate(document)


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    documents, total = await document_service.list_documents(
        owner_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return _document_list_response(documents, total=total, limit=limit, offset=offset)


@router.post("/documents/{document_id}/process", response_model=DocumentResponse)
async def process_document(
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    processing_service: Annotated[
        DocumentProcessingService,
        Depends(get_document_processing_service),
    ],
) -> DocumentResponse:
    try:
        document = await processing_service.process_document(
            document_id=document_id,
            owner_id=current_user.id,
        )
    except ProcessingDocumentNotFoundError as exc:
        raise _not_found() from exc
    except DocumentAlreadyProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already processing",
        ) from exc
    return DocumentResponse.model_validate(document)


@router.get("/documents/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    processing_service: Annotated[
        DocumentProcessingService,
        Depends(get_document_processing_service),
    ],
) -> DocumentContentResponse:
    try:
        document = await processing_service.get_document_content(
            document_id=document_id,
            owner_id=current_user.id,
        )
    except ProcessingDocumentNotFoundError as exc:
        raise _not_found() from exc
    return DocumentContentResponse(
        document=DocumentResponse.model_validate(document),
        extracted_text=document.extracted_text,
        extracted_text_length=document.extracted_text_length,
    )


@router.post(
    "/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
    storage_service: Annotated[LocalStorageService, Depends(get_local_storage_service)],
    file: Annotated[UploadFile, File()],
    project_id: Annotated[UUID | None, Form()] = None,
) -> DocumentUploadResponse:
    try:
        document, linked_project_id = await document_service.upload_document(
            owner_id=current_user.id,
            upload_file=file,
            storage_service=storage_service,
            project_id=project_id,
        )
    except ProjectNotFoundError as exc:
        raise _not_found() from exc
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Uploaded file is too large",
        ) from exc
    except EmptyUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        ) from exc
    except UnsupportedUploadTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported upload file type",
        ) from exc
    except StorageConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generated storage path already exists",
        ) from exc

    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(document),
        linked_project_id=linked_project_id,
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    try:
        document = await document_service.get_document(
            document_id=document_id,
            owner_id=current_user.id,
        )
    except DocumentNotFoundError as exc:
        raise _not_found() from exc
    return DocumentResponse.model_validate(document)


@router.post(
    "/projects/{project_id}/documents/{document_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
)
async def attach_document_to_project(
    project_id: UUID,
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentResponse:
    try:
        document = await document_service.attach_document_to_project(
            project_id=project_id,
            document_id=document_id,
            owner_id=current_user.id,
        )
    except (DocumentNotFoundError, ProjectNotFoundError) as exc:
        raise _not_found() from exc
    return DocumentResponse.model_validate(document)


@router.delete(
    "/projects/{project_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_document_from_project(
    project_id: UUID,
    document_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
) -> Response:
    try:
        await document_service.detach_document_from_project(
            project_id=project_id,
            document_id=document_id,
            owner_id=current_user.id,
        )
    except (DocumentNotFoundError, ProjectNotFoundError, ProjectDocumentLinkNotFoundError) as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/documents", response_model=DocumentListResponse)
async def list_project_documents(
    project_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    try:
        documents, total = await document_service.list_project_documents(
            project_id=project_id,
            owner_id=current_user.id,
            limit=limit,
            offset=offset,
        )
    except ProjectNotFoundError as exc:
        raise _not_found() from exc
    return _document_list_response(documents, total=total, limit=limit, offset=offset)


def _document_list_response(
    documents: list,
    *,
    total: int,
    limit: int,
    offset: int,
) -> DocumentListResponse:
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(document) for document in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
